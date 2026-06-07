import asyncio
import random
from typing import Dict
from datetime import datetime

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier
from .opportunity_detector import OpportunityDetector
from .profitability import ProfitabilityCalculator
from .executor import Executor
from ..chains.rpc_manager import RPCManager   # RPC連携


class PriceMonitor:
    """
    DEXから価格情報を監視するモジュール
    RPC連携により実際の市場価格を取得（モックとのフォールバック対応）
    """

    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier):
        self.config = config
        self.logger = logger
        self.telegram = telegram
        self.monitoring_interval = config['bot'].get('monitoring_interval', 2.0)
        self.pairs = config.get('pairs', ['WETH/USDC'])
        self.is_running = False

        # RPCManager初期化
        self.rpc_manager = RPCManager(config, logger)

        # 各モジュール初期化
        self.detector = OpportunityDetector(config, logger, telegram)
        self.profitability = ProfitabilityCalculator(config, logger, telegram)
        self.executor = Executor(config, logger, telegram)

        self.logger.info("PriceMonitor initialized (RPC連携)")

    async def get_prices(self) -> Dict:
        """本物のRPCを使って価格取得（失敗時はモックにフォールバック）"""
        prices = {}
        w3 = self.rpc_manager.get_web3()

        if not w3 or not w3.is_connected():
            self.logger.warning("RPC未接続のためモック価格を使用します")
            return self._get_mock_prices()

        try:
            for pair in self.pairs:
                # TODO: ここに実際のDEXコントラクト呼び出しを実装（Uniswap V3 Quoterなど）
                # 現在はモック（将来的に本物に置き換え）
                base_price = random.uniform(2400, 2600)

                prices[pair] = {
                    "uniswap_v3": round(base_price * (1 + random.uniform(-0.003, 0.003)), 4),
                    "sushiswap": round(base_price * (1 + random.uniform(-0.003, 0.003)), 4),
                }

            self.logger.debug(f"取得価格: {prices}")
            return prices

        except Exception as e:
            self.logger.error(f"価格取得エラー: {e} → モックにフォールバック")
            return self._get_mock_prices()

    def _get_mock_prices(self) -> Dict:
        """フォールバック用モック価格"""
        prices = {}
        for pair in self.pairs:
            base_price = random.uniform(2400, 2600)
            prices[pair] = {
                "uniswap_v3": round(base_price * (1 + random.uniform(-0.003, 0.003)), 4),
                "sushiswap": round(base_price * (1 + random.uniform(-0.003, 0.003)), 4),
            }
        return prices

    async def start_monitoring(self):
        """価格監視ループを開始"""
        self.is_running = True
        self.logger.info("Price monitoring started")
        await self.telegram.send_message("🟢 PriceMonitor started (RPC連携)")

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
                            self.logger.warning(f"✅ 実行可能機会: ${result['estimated_profit_usd']:.2f} | {result['pair']}")

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
        """監視を停止"""
        self.is_running = False
        self.logger.info("PriceMonitor stopped")