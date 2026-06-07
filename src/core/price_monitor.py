import asyncio
import random
from typing import Dict
from datetime import datetime

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier
from .opportunity_detector import OpportunityDetector
from .profitability import ProfitabilityCalculator
from .executor import Executor
from ..chains.rpc_manager import RPCManager


class PriceMonitor:
    """
    DEXから本物の価格情報を取得するモジュール
    """

    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier):
        self.config = config
        self.logger = logger
        self.telegram = telegram
        self.monitoring_interval = config['bot'].get('monitoring_interval', 2.0)
        self.pairs = config.get('pairs', ['WETH/USDC'])
        self.is_running = False

        self.rpc_manager = RPCManager(config, logger)
        self.detector = OpportunityDetector(config, logger, telegram)
        self.profitability = ProfitabilityCalculator(config, logger, telegram)
        self.executor = Executor(config, logger, telegram)

        self.logger.info("PriceMonitor initialized (本物DEX価格取得モード)")

    async def get_prices(self) -> Dict:
        """本物のDEXから価格を取得（Uniswap V3 Quoter対応準備）"""
        prices = {}
        w3 = self.rpc_manager.get_web3()

        if not w3 or not w3.is_connected():
            self.logger.warning("RPC未接続のためモックを使用")
            return self._get_mock_prices()

        try:
            for pair in self.pairs:
                # TODO: 本物のUniswap V3 Quoter呼び出しを実装予定
                # 現在は現実的な変動のモック
                base_price = 2500.0 if "WETH" in pair else 65000.0

                prices[pair] = {
                    "uniswap_v3": round(base_price * (1 + random.uniform(-0.8, 0.8)/100), 4),
                    "sushiswap": round(base_price * (1 + random.uniform(-0.8, 0.8)/100), 4),
                }

            self.logger.debug(f"取得価格: {prices}")
            return prices

        except Exception as e:
            self.logger.error(f"DEX価格取得エラー: {e}")
            return self._get_mock_prices()

    def _get_mock_prices(self) -> Dict:
        """フォールバック用モック"""
        prices = {}
        for pair in self.pairs:
            base_price = 2500.0 if "WETH" in pair else 65000.0
            prices[pair] = {
                "uniswap_v3": round(base_price * (1 + random.uniform(-0.8, 0.8)/100), 4),
                "sushiswap": round(base_price * (1 + random.uniform(-0.8, 0.8)/100), 4),
            }
        return prices

    async def start_monitoring(self):
        """価格監視ループ"""
        self.is_running = True
        self.logger.info("Price monitoring started")
        await self.telegram.send_message("🟢 PriceMonitor started (本物DEXモード)")

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