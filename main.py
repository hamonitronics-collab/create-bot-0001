import asyncio
import sys
from datetime import datetime

# 設定ローダー
from config.config_loader import load_config

# ユーティリティ
from src.utils.logger import BotLogger
from src.utils.telegram import TelegramNotifier

# コアモジュール
from src.core.price_monitor import PriceMonitor
from src.core.opportunity_detector import OpportunityDetector
from src.core.profitability import ProfitabilityCalculator
from src.core.executor import Executor


class ArbitrageBot:
    """
    DEX間アービトラージBotのメインクラス
    要件定義 v0.3 に準拠した統合クラス
    """

    def __init__(self):
        # 設定読み込み
        self.config = load_config()

        # LoggerとTelegram初期化
        self.logger = BotLogger(self.config)
        self.telegram = TelegramNotifier(self.config, self.logger)

        # 各モジュールの初期化
        self.price_monitor = PriceMonitor(self.config, self.logger, self.telegram)
        self.detector = OpportunityDetector(self.config, self.logger, self.telegram)
        self.profitability = ProfitabilityCalculator(self.config, self.logger, self.telegram)
        self.executor = Executor(self.config, self.logger, self.telegram)

        self.logger.info("✅ ArbitrageBot initialized successfully with all modules")

    async def run(self):
        """メイン実行ループ"""
        await self.telegram.send_message("🚀 **Arbitrage Bot Started Successfully**")
        self.logger.info("Bot main loop started")

        # 並行実行するタスク一覧
        tasks = [
            asyncio.create_task(self.price_monitor.start_monitoring(), name="PriceMonitor"),
            # 将来ここに追加予定：
            # asyncio.create_task(self.detector.start_detecting(), name="OpportunityDetector"),
            # asyncio.create_task(self.executor.start_executor(), name="Executor"),
        ]

        try:
            # 全タスクを並行実行（1つが例外を起こしても他は継続）
            await asyncio.gather(*tasks, return_exceptions=True)

        except asyncio.CancelledError:
            self.logger.info("Bot shutting down gracefully...")
        except Exception as e:
            self.logger.critical(f"Critical error in main loop: {e}")
            await self.telegram.send_message(f"❌ **Critical Error**: {e}")
        finally:
            # タスクのクリーンアップ
            for task in tasks:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            await self.telegram.send_message("⛔ **Bot Stopped**")
            self.logger.info("Bot shutdown completed")

    def stop(self):
        """安全停止"""
        self.logger.info("Bot stopped by user request")


async def main():
    bot = ArbitrageBot()

    try:
        await bot.run()
    except KeyboardInterrupt:
        bot.logger.info("Keyboard interrupt received. Shutting down...")
        bot.stop()
    except Exception as e:
        if hasattr(bot, 'logger'):
            bot.logger.critical(f"Unhandled exception: {e}")


if __name__ == "__main__":
    asyncio.run(main())