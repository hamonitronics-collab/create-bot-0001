import asyncio
import sys
from datetime import datetime

# 設定
from config.config_loader import load_config

# ユーティリティ
from src.utils.logger import BotLogger
from src.utils.telegram import TelegramNotifier

# コアモジュール
from src.core.price_monitor import PriceMonitor
from src.core.profitability import ProfitabilityCalculator  # ← 追加


class ArbitrageBot:
    """
    DEX間アービトラージBotのメインクラス
    要件定義 v0.3 に準拠
    """

    def __init__(self):
        try:
            # 設定読み込み
            self.config = load_config()

            # LoggerとTelegram初期化
            self.logger = BotLogger(self.config)
            self.telegram = TelegramNotifier(self.config, self.logger)

            # モジュール初期化
            self.price_monitor = PriceMonitor(self.config, self.logger, self.telegram)
            # ProfitabilityCalculatorもここで初期化（PriceMonitor内で使われるので必須）
            self.profitability = ProfitabilityCalculator(self.config, self.logger, self.telegram)

            self.logger.info("✅ ArbitrageBot initialized successfully")
            self.running = True

        except Exception as e:
            print(f"❌ 初期化エラー: {e}")
            sys.exit(1)

    async def run(self):
        """メイン実行ループ"""
        await self.telegram.send_message("🚀 **Arbitrage Bot Started**")
        self.logger.info("Bot main loop started")

        try:
            # 価格監視タスク開始
            monitor_task = asyncio.create_task(self.price_monitor.start_monitoring())

            # メインループ（将来的に他の処理を追加）
            while self.running:
                await asyncio.sleep(60)  # 軽めの監視

        except asyncio.CancelledError:
            self.logger.info("Bot shutting down gracefully...")
        except Exception as e:
            self.logger.critical(f"Critical error: {e}")
            await self.telegram.send_message(f"❌ **Critical Error**: {e}")
        finally:
            self.running = False
            await self.telegram.send_message("⛔ **Bot Stopped**")


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