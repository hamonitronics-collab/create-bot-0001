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
    完全DEX間アービトラージ版（買って→売る2ステップ）
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

        self.dry_run = True   # 安全のため一旦True（テスト後Falseに変更）

        self.w3 = None
        self.account = None
        self._connect_web3()

        self.router_address = self.w3.to_checksum_address("0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45")
        self.weth = self.w3.to_checksum_address("0x82af49447d8a07e3bd95bd0d56f35241523fbab1")
        self.usdt = self.w3.to_checksum_address("0x1be207f7ae412c6deb0505485a36bfbdbd921d89")

        self.logger.info("Executor initialized (完全DEX間アービトラージ版)")

    def _connect_web3(self):
        try:
            rpc_url = "https://arb1.arbitrum.io/rpc"   # Arbitrum Mainnet公式RPC
            self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 15}))

            if self.w3.is_connected():
                self.logger.info(f"✅ Web3接続成功 (Mainnet) | Chain ID: {self.w3.eth.chain_id}")
                if self.private_key:
                    self.account = self.w3.eth.account.from_key(self.private_key)
                    self.w3.eth.default_account = self.account.address
                    self.logger.info(f"✅ アカウント設定完了: {self.account.address[:10]}...")
            else:
                self.logger.error("Web3接続失敗")
        except Exception as e:
            self.logger.error(f"Web3接続エラー: {e}")

    def execute(self, opportunity: Dict) -> bool:
        try:
            if not opportunity.get('is_profitable', False):
                return False

            buy_dex = opportunity.get('buy_dex')
            sell_dex = opportunity.get('sell_dex')
            pair = opportunity['pair']

            self.logger.critical(f"🚀 完全アービトラージ実行: {buy_dex}で買って → {sell_dex}で売る | {pair}")

            if not self._check_balance(0.005):
                return False

            # 2ステップ実行
            success1 = self._perform_swap(buy_dex, opportunity, is_buy=True)
            if not success1:
                return False

            success2 = self._perform_swap(sell_dex, opportunity, is_buy=False)
            if success2:
                self.logger.warning(f"✅ 完全アービトラージ完了: {pair}")
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

    def _perform_swap(self, dex: str, opportunity: Dict, is_buy: bool) -> bool:
        """1回のSwap実行（ガス料金強化版）"""
        try:
            amount_in = self.w3.to_wei(0.005, 'ether')

            router = self.w3.eth.contract(address=self.router_address, abi=self._get_router_abi())

            direction = "買う" if is_buy else "売る"
            self.logger.warning(f"[{dex}] {direction}を実行: {amount_in} WETH → USDT")

            deadline = int(time.time()) + 600

            # amountOutMin計算
            price_diff = opportunity.get('price_diff_percent', 0.5)
            expected_out = int(amount_in * (1 + price_diff / 100) * (1 - self.max_slippage / 100))

            # === ガス料金をより強めに動的設定 ===
            base_fee = self.w3.eth.get_block('latest')['baseFeePerGas']
            max_priority_fee = self.w3.to_wei(3, 'gwei')   # 少し高めに
            max_fee_per_gas = base_fee * 2 + max_priority_fee

            self.logger.info(f"ガス料金設定: baseFee={base_fee}, maxFeePerGas={max_fee_per_gas}")

            tx = router.functions.swapExactTokensForTokens(
                amount_in,
                expected_out,
                [self.weth, self.usdt],
                self.account.address,
                deadline
            ).build_transaction({
                'from': self.account.address,
                'nonce': self.w3.eth.get_transaction_count(self.account.address),
                'maxFeePerGas': max_fee_per_gas,
                'maxPriorityFeePerGas': max_priority_fee,
                'gas': 400000,   # 少し余裕を持たせる
            })

            signed_tx = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)

            self.logger.critical(f"✅ {dex} Tx送信完了: {tx_hash.hex()}")

            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
            status = '成功' if receipt.status == 1 else '失敗'
            self.logger.warning(f"✅ {dex} トランザクション確認完了! Status: {status}")

            return receipt.status == 1

        except Exception as e:
            self.logger.error(f"{dex} Swapエラー: {e}")
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