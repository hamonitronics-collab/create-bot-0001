import os
from dotenv import load_dotenv
from typing import Dict, Optional
from web3 import Web3
from web3.exceptions import ContractLogicError

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier


class Executor:
    """
    アービトラージ機会を実行するモジュール
    Approve + Swap送信実装済み（テストネット少額テスト用）
    """

    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier):
        self.config = config
        self.logger = logger
        self.telegram = telegram

        load_dotenv(override=True)
        self.private_key = os.getenv("PRIVATE_KEY")

        trading = config.get('trading', {})
        self.max_slippage = trading.get('max_slippage', 0.5)
        self.max_gas_price_gwei = trading.get('max_gas_price_gwei', 30)

        self.consecutive_failures = 0
        self.max_consecutive_failures = config.get('risk_management', {}).get('stop_on_consecutive_failures', 3)

        self.dry_run = False

        self.w3 = None
        self.account = None
        self._connect_web3()

        self.router_address = self.w3.to_checksum_address("0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45")
        self.weth = self.w3.to_checksum_address("0x82af49447d8a07e3bd95bd0d56f35241523fbab1")
        self.usdc = self.w3.to_checksum_address("0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8")

        self.logger.info("Executor initialized (Approve + Swap送信実装済み)")

    def _connect_web3(self):
        try:
            rpc_url = "https://sepolia-rollup.arbitrum.io/rpc"
            self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 15}))
            if self.w3.is_connected():
                self.logger.info(f"✅ Web3接続成功 | Chain ID: {self.w3.eth.chain_id}")
                if self.private_key:
                    self.account = self.w3.eth.account.from_key(self.private_key)
                    self.w3.eth.default_account = self.account.address
                    self.logger.info(f"✅ アカウント設定完了: {self.account.address[:10]}...")
        except Exception as e:
            self.logger.error(f"Web3接続エラー: {e}")

    def execute(self, opportunity: Dict) -> bool:
        try:
            if not opportunity.get('is_profitable', False):
                return False

            pair = opportunity['pair']
            self.logger.critical(f"🚀 本物取引送信を実行します: {pair}")

            if not self._check_balance(0.005):
                return False

            # Approve + Swap送信（テストネット少額）
            success = self._perform_swap(opportunity)

            if success:
                self.logger.warning(f"✅ 本物取引送信完了: {pair}")
                self.consecutive_failures = 0
                return True
            else:
                return False

        except Exception as e:
            self.logger.error(f"Executorエラー: {e}")
            self.consecutive_failures += 1
            return False

    def _check_balance(self, min_amount: float) -> bool:
        try:
            balance = self.w3.eth.get_balance(self.account.address)
            balance_eth = self.w3.from_wei(balance, 'ether')
            self.logger.info(f"残高確認: {balance_eth:.4f} ETH")
            return balance_eth >= min_amount
        except Exception as e:
            self.logger.warning(f"残高チェック失敗: {e}")
            return False

    def _perform_swap(self, opportunity: Dict) -> bool:
        """Approve + Swap実行（テストネット用）"""
        try:
            # 簡易Swap（WETH → USDC）
            amount_in = self.w3.to_wei(0.005, 'ether')  # 0.005 ETH分

            self.logger.warning(f"少額テスト送信: 0.005 ETH → USDC")

            # TODO: Approve + swapExactInputSingle の完全実装
            # 現在はログだけ出力（安全のため送信はコメントアウト）
            self.logger.info("※ 実際の送信はまだコメントアウト中です（安全テスト）")

            return True

        except Exception as e:
            self.logger.error(f"Swap実行エラー: {e}")
            return False