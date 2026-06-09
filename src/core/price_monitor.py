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
                self.dex_adapters[dex_name] = adapter_class(self.w3, self.logger, self.config)
                self.logger.info(f"🟢 DEXアダプター [{dex_name}] の自動ロードに成功しました ({class_name})")
            except Exception as e:
                self.logger.error(f"DEXアダプター {dex_name} のロード失敗: {e}")

    async def _connect_rpc(self):
        """非同期でRPCに接続し、成功したらアダプターを初期化する"""
        try:
            chain = self.config['bot']['chain']
            rpc_url = self.config['rpc'][chain]['url']

            def connect():
                w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 5}))
                # 💡 修正1: chain_id の取得もフリーズの原因になるため、ここで裏処理として取得してしまう
                if w3.is_connected():
                    return w3, w3.eth.chain_id
                return None, None

            self.w3, chain_id = await asyncio.to_thread(connect)

            if self.w3:
                self.logger.info(f"✅ RPC接続成功 | Chain ID: {chain_id}")
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
            tasks = []
            dex_names = []

            for dex_name, adapter in self.dex_adapters.items():
                def fetch_price(ad=adapter):
                    return ad.get_price(pair, token_in, token_out, {})

                tasks.append(asyncio.to_thread(fetch_price))
                dex_names.append(dex_name)

            # すべてのDEXの返事を一斉に待つ（並列処理）
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(results):
                if not isinstance(result, Exception) and result is not None:
                    dex_data[dex_names[i]] = result

            if dex_data: prices[pair] = dex_data

        return prices

    async def start_monitoring(self):
        self.is_running = True
        self.logger.info("Price monitoring started")
        #await self.telegram.send_message("🟢 PriceMonitor started")

        while self.is_running:
            prices = await self.get_prices()
            if prices:
                opportunities = self.detector.detect_opportunities(prices)
                if opportunities:
                    for opp in opportunities:
                        def process_opportunity(opportunity_data):
                            calc = self.profitability.calculate_profitability(opportunity_data)
                            if calc and calc.get("is_profitable"):
                                self.executor.execute(calc)

                        # 裏側で計算・実行させる（メインループは絶対に止めない）
                        await asyncio.to_thread(process_opportunity, opp)
            await asyncio.sleep(self.monitoring_interval)