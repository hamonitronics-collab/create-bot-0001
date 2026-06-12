import asyncio
import sys
import argparse
from datetime import datetime

from config.config_loader import load_config
from src.utils.logger import BotLogger
from src.utils.telegram import TelegramNotifier

from src.core.price_monitor import PriceMonitor
from src.core.opportunity_detector import OpportunityDetector
from src.core.triangular_detector import TriangularDetector
from src.core.profitability import ProfitabilityCalculator
from src.core.executor import Executor

class ArbitrageBot:
    """
    DEX間アービトラージBotのメインクラス
    """

    def __init__(self, mode: str):
        try:
            if mode == "spatial":
                self.config = load_config("config_spatial.yaml")
            elif mode == "triangular":
                self.config = load_config("config_triangular.yaml")
            else:
                raise ValueError(f"不明なモードです: {mode}")

            self.logger = BotLogger(self.config)
            self.telegram = TelegramNotifier(self.config, self.logger)
            self.mode = mode
            self.running = True
            self.w3 = None
            # PriceMonitorに全体停止コールバックを渡す
            self.price_monitor = PriceMonitor(
                self.config,
                self.logger,
                self.telegram,
                stop_callback=self.stop_bot
            )
            self.detector = OpportunityDetector(self.config, self.logger, self.telegram)
            self.profitability = ProfitabilityCalculator(self.config, self.logger, self.telegram)
            self.triangular_detector = TriangularDetector(self.config, self.logger, self.profitability) # 💡ここに足す！

            self.executor = Executor(self.config, self.logger, self.telegram, self.mode)

            # configから監視間隔を取得（なければデフォルト2.0秒）
            self.monitoring_interval = self.config.get('bot', {}).get('monitoring_interval', 2.0)

            self.logger.info("✅ ArbitrageBot initialized successfully")

        except Exception as e:
            print(f"❌ 初期化エラー: {e}")
            sys.exit(1)

    def stop_bot(self, reason: str = "不明な理由"):
        """全体停止処理"""
        self.logger.critical(f"🚨 Bot全体停止命令を受信: {reason}")
        self.running = False

    async def run(self):
        await self.telegram.send_message(f"🚀 **Arbitrage Bot Started ({self.mode} mode)**")
        self.logger.info(f"Bot main loop started in {self.mode} mode")

        try:
            while self.running:
                # ----------------------------------------------------
                # ① 空間アビトラ（spatial）の処理
                # ----------------------------------------------------
                if self.mode == "spatial":
                    # start_monitoring() ではなく get_prices() を1回だけ呼ぶ
                    prices = await self.price_monitor.get_prices()
                    if prices:
                        opportunities = self.detector.detect_opportunities(prices)
                        if opportunities:
                            self.logger.warning(f"検知された機会: {len(opportunities)}件")

                            for opp in opportunities:
                                async def process_opportunity_async(opportunity_data):
                                    try:
                                        calc = self.profitability.calculate_profitability(opportunity_data)
                                        if calc and calc.get("is_profitable"):
                                            await self.executor.execute(calc)
                                    except Exception as e:
                                        self.logger.error(f"❌ 機会処理中にエラーが発生: {e}")

                                asyncio.create_task(process_opportunity_async(opp))

                # ----------------------------------------------------
                # ② 三角アビトラ（triangular）の処理
                # ----------------------------------------------------
                # ----------------------------------------------------
                # ② 三角アビトラ（triangular）の処理
                # ----------------------------------------------------
                elif self.mode == "triangular":
                    if not self.price_monitor.w3:
                        await self.price_monitor._connect_rpc()
                        if not self.price_monitor.w3:
                            await asyncio.sleep(self.monitoring_interval)
                            continue

                    # w3 インスタンスを main 側にも同期しておく
                    self.w3 = self.price_monitor.w3

                    # 💡 【追加】現在のネットワークのガス代を動的に計算してセットする
                    try:
                        # ガス価格をWeiで取得
                        gas_price_wei = await asyncio.to_thread(lambda: self.w3.eth.gas_price)

                        # 最初のアダプターを使ってWETH/USDC価格を取得し、ETHのドル価格を出す
                        first_dex = list(self.price_monitor.dex_adapters.values())[0]
                        weth_addr = self.config['tokens']['WETH']['address']
                        usdc_addr = self.config['tokens']['USDC']['address']

                        params = {"amount_in": 10**18, "quote_decimals": 18, "base_decimals": 6}
                        eth_price_data = await asyncio.to_thread(first_dex.get_price, "WETH/USDC", weth_addr, usdc_addr, params)

                        if eth_price_data:
                            eth_price_usd = eth_price_data['amount_out_wei'] / (10**6)
                            gas_limit = self.config.get('trading', {}).get('estimated_gas_limit', 1500000)

                           # ガス代（USD）を算出
                            dynamic_gas_usd = (gas_price_wei * gas_limit / (10**18)) * eth_price_usd

                            # 💡 【追加】WeiをGwei（10億分の1）に変換
                            gas_price_gwei = gas_price_wei / (10**9)

                            # 💡 profitabilityに最新のガス代とGweiの両方を教える！
                            self.profitability.set_dynamic_gas_usd(dynamic_gas_usd, gas_price_gwei)
                        else:
                            self.logger.warning("⚠️ 動的ガス計算: WETHの価格取得に失敗しました")

                    except Exception as e:
                        # 💡 エラーを隠さずログに出力して犯人を特定する！
                        self.logger.error(f"❌ 動的ガス計算エラー: {e}")

                    # 安全になった detector を呼び出す
                    triangular_opps = await self.triangular_detector.detect_opportunities(self.price_monitor.dex_adapters)

                    if triangular_opps:
                        self.logger.warning(f"🔺 検知された三角機会: {len(triangular_opps)}件")

                        # 💡 修正：見つかった儲かるルートをループで回して、Executorへ非同期で投げる！
                        for opp in triangular_opps:
                            async def process_triangular_opportunity_async(opp_data):
                                try:
                                    # 実行部（Executor）の execute メソッドを呼び出す
                                    await self.executor.execute(opp_data)
                                except Exception as e:
                                    self.logger.error(f"❌ 三角アビトラ実行タスクエラー: {e}")

                            # バックグラウンドで超高速に処理を実行
                            asyncio.create_task(process_triangular_opportunity_async(opp))

                # ----------------------------------------------------
                # ループの最後に指定秒数だけ待機
                # ----------------------------------------------------
                await asyncio.sleep(self.monitoring_interval)

        except asyncio.CancelledError:
            self.logger.info("Bot shutting down gracefully...")
        except Exception as e:
            self.logger.critical(f"Critical error: {e}")
        finally:
            self.running = False
            await self.telegram.send_message("⛔ **Bot Stopped**")
            self.logger.info("ArbitrageBot stopped")

if __name__ == "__main__":
    # 引数の解析
    parser = argparse.ArgumentParser(description="Arbitrage Bot")
    parser.add_argument("--mode", choices=["spatial", "triangular"], required=True, help="起動モードを選択")
    args = parser.parse_args()

    print(f"{args.mode}モードでBotを起動します...")

    bot = ArbitrageBot(mode=args.mode)

    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user.")
    except Exception as e:
        print(f"Unexpected error: {e}")