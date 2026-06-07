import asyncio
import sys
from datetime import datetime

from config.config_loader import load_config

from src.utils.logger import BotLogger
from src.utils.telegram import TelegramNotifier

from src.core.price_monitor import PriceMonitor
# from src.core.profitability import ProfitabilityCalculator  # 将来的に直接使用する場合

class ArbitrageBot:
    """
    DEX間アービトラージBotのメインクラス
    RPC連続失敗時などに全体停止できるように強化
    """

    def __init__(self):
        try:
            self.config = load_config()

            self.logger = BotLogger(self.config)
            self.telegram = TelegramNotifier(self.config, self.logger)

            # 停止フラグ
            self.running = True

            # PriceMonitorに全体停止コールバックを渡す
            self.price_monitor = PriceMonitor(
                self.config,
                self.logger,
                self.telegram,
                stop_callback=self.stop_bot
            )

            self.logger.info("✅ ArbitrageBot initialized successfully")

        except Exception as e:
            print(f"❌ 初期化エラー: {e}")
            sys.exit(1)

    def stop_bot(self, reason: str = "不明な理由"):
        """全体停止処理"""
        self.logger.critical(f"🚨 Bot全体停止命令を受信: {reason}")
        self.running = False
        # 将来的に他のモジュールの停止もここで呼ぶ

    async def run(self):
        await self.telegram.send_message("🚀 **Arbitrage Bot Started**")
        self.logger.info("Bot main loop started")

        try:
            monitor_task = asyncio.create_task(self.price_monitor.start_monitoring())

            while self.running:
                await asyncio.sleep(30)

        except asyncio.CancelledError:
            self.logger.info("Bot shutting down gracefully...")
        except Exception as e:
            self.logger.critical(f"Critical error: {e}")
        finally:
            self.running = False
            await self.telegram.send_message("⛔ **Bot Stopped**")
            self.logger.info("ArbitrageBot stopped")


async def main():
    bot = ArbitrageBot()
    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user.")
    except Exception as e:
        print(f"Unexpected error: {e}")


if __name__ == "__main__":
    asyncio.run(main())