import asyncio
import random
from typing import Dict
from datetime import datetime

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier
from .opportunity_detector import OpportunityDetector
from .profitability import ProfitabilityCalculator
from .executor import Executor   # ← 追加


class PriceMonitor:
    """
    DEXから価格情報を監視するモジュール
    """

    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier):
        self.config = config
        self.logger = logger
        self.telegram = telegram
        self.monitoring_interval = config['bot'].get('monitoring_interval', 2.0)
        self.pairs = config.get('pairs', ['WETH/USDC'])
        self.is_running = False

        # 各モジュールの初期化
        self.detector = OpportunityDetector(config, logger, telegram)
        self.profitability = ProfitabilityCalculator(config, logger, telegram)
        self.executor = Executor(config, logger, telegram)  # ← 追加

        self.logger.info("PriceMonitor initialized")

    async def get_prices(self) -> Dict[str, Dict[str, float]]:
        prices = {}
        for pair in self.pairs:
            base_price = random.uniform(2400, 2600)
            prices[pair] = {
                "uniswap_v3": round(base_price * (1 + random.uniform(-0.003, 0.003)), 4),
                "sushiswap": round(base_price * (1 + random.uniform(-0.003, 0.003)), 4),
            }
        self.logger.debug(f"取得価格: {prices}")
        return prices

    async def start_monitoring(self):
        self.is_running = True
        self.logger.info("Price monitoring started")
        await self.telegram.send_message("🟢 PriceMonitor started")

        try:
            while self.is_running:
                start_time = datetime.now()

                prices = await self.get_prices()
                opportunities = self.detector.detect_opportunities(prices)

                # Profitability + Executor連携
                if opportunities:
                    for opp in opportunities:
                        result = self.profitability.calculate_profitability(opp)
                        if result and result.get("is_profitable"):
                            self.logger.warning(f"✅ 実行可能機会: ${result['estimated_profit_usd']} | {result['pair']}")

                            # Executorで実行（現在はシミュレーション）
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