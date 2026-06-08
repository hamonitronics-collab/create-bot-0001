import os
from dotenv import load_dotenv
from typing import Dict, Optional
from web3 import Web3
import time

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier


class Executor:
    """
    アービトラージ機会を実行するモジュール
    WETH → USDT版（ロジックはそのまま）
    """

    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier):
        self.config = config
        self.logger = logger
        self.telegram = telegram

        load_dotenv(override=True)
        self.private_key = os.getenv("PRIVATE_KEY")

        trading = config.get('trading', {})
        self.max_slippage = trading.get('max_slippage', 0.5)

        self.consecutive_failures = 0
        self.max_consecutive_failures = config.get('risk_management', {}).get('stop_on_consecutive_failures', 3)

        self.dry_run = False

        self.w3 = None
        self.account = None
        self._connect_web3()

        self.router_address = self.w3.to_checksum_address("0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45")
        self.weth = self.w3.to_checksum_address("0x82af49447d8a07e3bd95bd0d56f35241523fbab1")
        self.usdt = self.w3.to_checksum_address("0x1be207f7ae412c6deb0505485a36bfbdbd921d89")  # Arbitrum Sepolia USDT

        self.logger.info("Executor initialized (WETH → USDT版)")

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

            success = self._perform_swap(opportunity)

            if success:
                self.logger.warning(f"✅ 本物取引送信完了: {pair}")
                self.consecutive_failures = 0
                return True
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
        """WETH → USDT Swap（amountOutMin改善）"""
        try:
            amount_in = self.w3.to_wei(0.005, 'ether')

            router = self.w3.eth.contract(address=self.router_address, abi=self._get_router_abi())

            self.logger.warning(f"Swapを実行します: {amount_in} WETH → USDT")

            deadline = int(time.time()) + 600

            # amountOutMinを価格差から簡易計算
            price_diff = opportunity.get('price_diff_percent', 0.5)
            expected_out = int(amount_in * (1 + price_diff / 100) * (1 - self.max_slippage / 100))

            tx = router.functions.swapExactTokensForTokens(
                amount_in,
                expected_out,
                [self.weth, self.usdt],   # ← USDTに変更
                self.account.address,
                deadline
            ).build_transaction({
                'from': self.account.address,
                'gas': 350000,
                'gasPrice': self.w3.eth.gas_price,
                'nonce': self.w3.eth.get_transaction_count(self.account.address),
            })

            signed_tx = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)

            self.logger.critical(f"✅ トランザクション送信完了! Tx Hash: {tx_hash.hex()}")

            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
            status = '成功' if receipt.status == 1 else '失敗'
            self.logger.warning(f"✅ トランザクション確認完了! Status: {status}")

            return receipt.status == 1

        except Exception as e:
            self.logger.error(f"Swap実行エラー: {e}")
            return False

    def _get_router_abi(self):
        return [{
            "inputs": [
                {"name": "amountIn", "type": "uint256"},
                {"name": "amountOutMin", "type": "uint256"},
                {"name": "path", "type": "address[]"},
                {"name": "to", "type": "address"},
                {"name": "deadline", "type": "uint256"}
            ],
            "name": "swapExactTokensForTokens",
            "outputs": [{"name": "amounts", "type": "uint256[]"}],
            "stateMutability": "nonpayable",
            "type": "function"
        }]