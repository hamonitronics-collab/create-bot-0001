import asyncio
from typing import Dict, Callable
from datetime import datetime
from web3 import Web3
import importlib

# 必要なクラスをインポート
from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier
from .opportunity_detector import OpportunityDetector
from .profitability import ProfitabilityCalculator
from .executor import Executor

class PriceMonitor:
    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier, stop_callback: Callable = None):
        self.config = config
        self.logger = logger
        self.telegram = telegram
        self.stop_callback = stop_callback
        self.monitoring_interval = config['bot'].get('monitoring_interval', 2.0)
        self.pairs = config.get('pairs', [])
        self.is_running = False
        self.w3 = None

        self.detector = OpportunityDetector(config, logger, telegram)
        self.profitability = ProfitabilityCalculator(config, logger, telegram)
        self.executor = Executor(config, logger, telegram)

        # 💡 アダプターの格納場所だけ準備
        self.dex_adapters = {}

    def _init_adapters(self):
        """Web3接続成功後にアダプターをロードする"""
        for dex_name in self.config.get('dexes', {}).keys():
            try:
                module_name = f"src.dex.Individual.{dex_name}"
                parts = dex_name.split('_')
                class_name = "".join(p.capitalize() for p in parts) + "Adapter"

                module = importlib.import_module(module_name)
                adapter_class = getattr(module, class_name)
                # 💡 ここで w3 が確実に存在する状態で注入！
                self.dex_adapters[dex_name] = adapter_class(self.w3, self.logger, self.config)
            except Exception as e:
                self.logger.error(f"DEXアダプター {dex_name} のロード失敗: {e}")

    async def _connect_rpc(self):
        """非同期でRPCに接続し、成功したらアダプターを初期化する"""
        try:
            chain = self.config['bot']['chain']
            rpc_url = self.config['rpc'][chain]['url']

            def connect():
                w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 5}))
                return w3 if w3.is_connected() else None

            self.w3 = await asyncio.to_thread(connect)

            if self.w3:
                self.logger.info(f"✅ RPC接続成功 | Chain ID: {self.w3.eth.chain_id}")
                # 💡 接続成功したので、ここでアダプターを作る！
                self._init_adapters()
            else:
                self.logger.error("❌ RPC接続失敗")
        except Exception as e:
            self.logger.error(f"RPC接続エラー: {e}")

    async def get_prices(self) -> Dict[str, Dict[str, float]]:
        # 接続がなければ再接続を試みる
        if not self.w3 or not (await asyncio.to_thread(self.w3.is_connected)):
            await self._connect_rpc()
            if not self.w3: return {}

        prices = {}
        for pair in self.pairs:
            base_sym, quote_sym = pair.split("/")
            base_data = self.config.get('tokens', {}).get(base_sym)
            quote_data = self.config.get('tokens', {}).get(quote_sym)

            if not base_data or not quote_data: continue

            token_in = self.w3.to_checksum_address(base_data['address'])
            token_out = self.w3.to_checksum_address(quote_data['address'])

            dex_data = {}
            for dex_name, adapter in self.dex_adapters.items():
                price = adapter.get_price(pair, token_in, token_out, {})
                if price: dex_data[dex_name] = price

            if dex_data: prices[pair] = dex_data
        return prices

    async def start_monitoring(self):
        self.is_running = True
        self.logger.info("Price monitoring started")
        await self.telegram.send_message("🟢 PriceMonitor started")

        while self.is_running:
            prices = await self.get_prices()
            if prices:
                opportunities = self.detector.detect_opportunities(prices)
                if opportunities:
                    for opp in opportunities:
                        calc = self.profitability.calculate_profitability(opp)
                        if calc and calc.get("is_profitable"):
                            self.executor.execute(calc)
            await asyncio.sleep(self.monitoring_interval)