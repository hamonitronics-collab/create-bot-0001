import asyncio
import random
from typing import Dict
from datetime import datetime

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier


class PriceMonitor:
    """
    DEXから価格情報を監視するモジュール
    要件定義: 設定ファイルで監視間隔・対象ペアを管理
    """

    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier):
        self.config = config
        self.logger = logger
        self.telegram = telegram
        self.monitoring_interval = config['bot'].get('monitoring_interval', 2.0)
        self.pairs = config.get('pairs', ['WETH/USDC'])
        self.is_running = False

        self.logger.info("PriceMonitor initialized")

    async def get_prices(self) -> Dict[str, Dict[str, float]]:
        """
        各DEXの価格を取得（現在はモック。将来的にWeb3 RPC + DEX Contractに置き換え）
        """
        prices = {}

        for pair in self.pairs:
            # モック価格（実際はRPCでリアルタイム取得）
            base_price = random.uniform(2400, 2600)

            prices[pair] = {
                "uniswap_v3": round(base_price * (1 + random.uniform(-0.003, 0.003)), 4),
                "sushiswap": round(base_price * (1 + random.uniform(-0.003, 0.003)), 4),
            }

        self.logger.debug(f"取得価格: {prices}")
        return prices

    async def start_monitoring(self):
        """価格監視ループを開始"""
        self.is_running = True
        self.logger.info("Price monitoring started")
        await self.telegram.send_message("🟢 PriceMonitor started")

        try:
            while self.is_running:
                start_time = datetime.now()

                prices = await self.get_prices()

                # 将来的にここでOpportunityDetectorに価格を渡す
                # await self.detector.detect_opportunities(prices)

                self.logger.info(f"[{start_time.strftime('%H:%M:%S')}] {len(self.pairs)}ペアを監視完了")

                await asyncio.sleep(self.monitoring_interval)

        except asyncio.CancelledError:
            self.logger.info("Price monitoring stopped gracefully")
        except Exception as e:
            self.logger.error(f"Monitoring error: {e}")
            await self.telegram.send_message(f"❌ PriceMonitor エラー: {e}")
        finally:
            self.is_running = False

    def stop(self):
        """監視を停止"""
        self.is_running = False
        self.logger.info("PriceMonitor stopped")