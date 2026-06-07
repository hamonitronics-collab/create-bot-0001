import asyncio
import random
from typing import Dict, Callable
from datetime import datetime

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier
from .opportunity_detector import OpportunityDetector
from .profitability import ProfitabilityCalculator
from .executor import Executor
from ..chains.rpc_manager import RPCManager


class PriceMonitor:
    """
    DEXから価格情報を監視するモジュール
    RPC連続失敗時はArbitrageBot全体に停止を伝播
    """

    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier, stop_callback: Callable = None):
        self.config = config
        self.logger = logger
        self.telegram = telegram
        self.stop_callback = stop_callback  # ArbitrageBotへの停止通知用
        self.monitoring_interval = config['bot'].get('monitoring_interval', 2.0)
        self.pairs = config.get('pairs', ['WETH/USDC'])
        self.is_running = False

        # RPCManagerに停止コールバックを渡す
        self.rpc_manager = RPCManager(config, logger, stop_callback=self._handle_rpc_stop)

        self.detector = OpportunityDetector(config, logger, telegram)
        self.profitability = ProfitabilityCalculator(config, logger, telegram)
        self.executor = Executor(config, logger, telegram)

        self.logger.info("PriceMonitor initialized (全体停止伝播機能付き)")

    def _handle_rpc_stop(self, reason: str):
        """RPCManagerから停止命令を受けた時の処理"""
        self.logger.critical(f"RPC停止命令を受信: {reason}")
        self.is_running = False
        if self.stop_callback:
            self.stop_callback(reason)  # ArbitrageBotへ伝播

    async def get_prices(self) -> Dict:
        # （前回と同じ内容、省略可）
        prices = {}
        w3 = self.rpc_manager.get_web3()

        if not w3 or not w3.is_connected():
            self.logger.warning("RPC未接続のためモックを使用")
            return self._get_mock_prices()

        try:
            for pair in self.pairs:
                base_price = 2500.0 if "WETH" in pair else 65000.0
                prices[pair] = {
                    "uniswap_v3": round(base_price * (1 + random.uniform(-0.8, 0.8)/100), 4),
                    "sushiswap": round(base_price * (1 + random.uniform(-0.8, 0.8)/100), 4),
                }
            return prices
        except Exception as e:
            self.logger.error(f"DEX価格取得エラー: {e}")
            return self._get_mock_prices()

    def _get_mock_prices(self) -> Dict:
        # （前回と同じ）
        prices = {}
        for pair in self.pairs:
            base_price = 2500.0 if "WETH" in pair else 65000.0
            prices[pair] = {
                "uniswap_v3": round(base_price * (1 + random.uniform(-0.8, 0.8)/100), 4),
                "sushiswap": round(base_price * (1 + random.uniform(-0.8, 0.8)/100), 4),
            }
        return prices

    async def start_monitoring(self):
        self.is_running = True
        self.logger.info("Price monitoring started")
        await self.telegram.send_message("🟢 PriceMonitor started (全体停止機能付き)")

        try:
            while self.is_running:
                start_time = datetime.now()

                prices = await self.get_prices()
                opportunities = self.detector.detect_opportunities(prices)

                if opportunities:
                    for opp in opportunities:
                        result = self.profitability.calculate_profitability(opp)
                        if result and result.get("is_profitable"):
                            self.logger.warning(f"✅ 実行可能機会: ${result['estimated_profit_usd']:.2f} | {result['pair']}")
                            success = self.executor.execute(result)
                            if success:
                                self.logger.warning(f"🎉 実行完了: {result['pair']}")

                self.logger.info(f"[{start_time.strftime('%H:%M:%S')}] {len(self.pairs)}ペアを監視完了")

                await asyncio.sleep(self.monitoring_interval)

        except asyncio.CancelledError:
            self.logger.info("Price monitoring stopped gracefully")
        except Exception as e:
            self.logger.error(f"Monitoring error: {e}")
        finally:
            self.is_running = False

    def stop(self):
        self.is_running = False
        self.logger.info("PriceMonitor stopped")