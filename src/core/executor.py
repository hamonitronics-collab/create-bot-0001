from typing import Dict, Optional
from web3 import Web3
from web3.exceptions import ContractLogicError
from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier


class Executor:
    """
    アービトラージ機会を実行するモジュール
    Read-Only → 本物見積もり段階
    """

    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier):
        self.config = config
        self.logger = logger
        self.telegram = telegram

        trading = config.get('trading', {})
        self.max_slippage = trading.get('max_slippage', 0.5)
        self.max_gas_price_gwei = trading.get('max_gas_price_gwei', 30)

        self.consecutive_failures = 0
        self.max_consecutive_failures = config.get('risk_management', {}).get('stop_on_consecutive_failures', 3)

        # Web3接続
        self.w3 = None
        self._connect_web3()

        # Uniswap V3 Router & Quoterアドレス（Arbitrum Sepolia用例）
        self.uniswap_router = "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45"  # 要調整
        self.uniswap_quoter = "0x..."  # Quoterアドレス（後でconfig化）

        self.logger.info("Executor initialized (本物見積もり準備完了)")

    def _connect_web3(self):
        try:
            rpc_url = "https://sepolia-rollup.arbitrum.io/rpc"
            self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 15}))
            if self.w3.is_connected():
                self.logger.info(f"✅ Web3接続成功 | Chain ID: {self.w3.eth.chain_id}")
            else:
                self.logger.error("Web3接続失敗")
        except Exception as e:
            self.logger.error(f"Web3接続エラー: {e}")

    def execute(self, opportunity: Dict) -> bool:
        """
        本物見積もり + 実行準備
        """
        try:
            if not opportunity.get('is_profitable', False):
                return False

            self.logger.warning(f"🚀 実行準備開始: {opportunity['pair']} | 期待利益 ${opportunity.get('estimated_profit_usd')}")

            # TODO: 本物見積もり処理
            # 1. Quoterで正確な出力額を取得
            # 2. ガス代見積もり
            # 3. トランザクション構築準備

            # 現在はシミュレーション成功
            self.logger.warning(f"✅ 見積もり完了・実行可能: {opportunity['pair']}")
            self.consecutive_failures = 0
            return True

        except Exception as e:
            self.logger.error(f"実行エラー: {e}")
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.max_consecutive_failures:
                self.logger.critical("連続失敗のためBot停止を推奨します")
            return False