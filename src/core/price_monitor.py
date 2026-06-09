import asyncio
from typing import Dict, Callable
from datetime import datetime
from web3 import Web3
import importlib

# 必要なクラスを正しくインポート
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

        # 初期化順序を確定させる
        self._connect_rpc()
        self.detector = OpportunityDetector(config, logger, telegram)
        self.profitability = ProfitabilityCalculator(config, logger, telegram)
        self.executor = Executor(config, logger, telegram)

        # DEXアダプターの自動ロード
        self.dex_adapters = {}
        for dex_name in config.get('dexes', {}).keys():
            try:
                module_name = f"src.dex.Individual.{dex_name}"
                parts = dex_name.split('_')
                class_name = "".join(p.capitalize() for p in parts) + "Adapter"

                module = importlib.import_module(module_name)
                adapter_class = getattr(module, class_name)
                self.dex_adapters[dex_name] = adapter_class(self.w3, self.logger, self.config)
            except Exception as e:
                self.logger.error(f"DEXアダプター {dex_name} のロード失敗: {e}")

        self.logger.info(f"PriceMonitor initialized (監視対象: {self.pairs})")

    def _connect_rpc(self):
        try:
            # configの構造に合わせて修正
            chain = self.config['bot']['chain']
            rpc_url = self.config['rpc'][chain]['url']
            self.w3 = Web3(Web3.HTTPProvider(rpc_url))
            if self.w3.is_connected():
                self.logger.info(f"✅ PriceMonitor RPC接続成功 | Chain ID: {self.w3.eth.chain_id}")
        except Exception as e:
            self.logger.error(f"RPC接続エラー: {e}")

    async def get_prices(self) -> Dict[str, Dict[str, float]]:
        prices = {}
        for pair in self.pairs:
            if not self.w3.is_connected():
                self._connect_rpc()

            base_sym, quote_sym = pair.split("/")
            base_data = self.config.get('tokens', {}).get(base_sym)
            quote_data = self.config.get('tokens', {}).get(quote_sym)

            if not base_data or not quote_data:
                continue

            token_in = self.w3.to_checksum_address(base_data['address'])
            token_out = self.w3.to_checksum_address(quote_data['address'])

            dex_data = {}
            for dex_name, adapter in self.dex_adapters.items():
                price = adapter.get_price(pair, token_in, token_out, {})
                if price:
                    dex_data[dex_name] = price

            if dex_data:
                prices[pair] = dex_data
        return prices

    async def start_monitoring(self):
        self.is_running = True
        self.logger.info("Price monitoring started")
        await self.telegram.send_message("🟢 PriceMonitor started")

        try:
            while self.is_running:
                start_time = datetime.now()
                prices = await self.get_prices()

                # ここで self.detector が確実に存在することを確認
                opportunities = self.detector.detect_opportunities(prices)

                if opportunities:
                    for opp in opportunities:
                        calculated = self.profitability.calculate_profitability(opp)
                        if calculated and calculated.get("is_profitable"):
                            self.executor.execute(calculated)

                await asyncio.sleep(self.monitoring_interval)
        except Exception as e:
            self.logger.error(f"Monitoring error: {e}")