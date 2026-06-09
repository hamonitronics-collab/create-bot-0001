import os
import time
from dotenv import load_dotenv
from typing import Dict, Optional
from web3 import Web3

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier


class Executor:
    """
    アービトラージ機会を実行するモジュール
    サンドイッチ防御壁（amountOutMin動的ハメ込み）完全対応版
    """

    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier):
        self.config = config
        self.logger = logger
        self.telegram = telegram

        load_dotenv(override=True)
        self.private_key = os.getenv("PRIVATE_KEY")

        self.dry_run = True # 🛡️ 安全装置（Trueの時はシミュレーションのみ）

        self.w3 = None
        self.account = None
        self._connect_web3()

        self.weth = self.w3.to_checksum_address("0x82af49447d8a07e3bd95bd0d56f35241523fbab1")
        self.usdc = self.w3.to_checksum_address("0xaf88d065e77c8cC2239327C5EDb3A432268e5831") # Native USDC

        self.logger.info(f"Executor initialized (DryRun: {'ON' if self.dry_run else 'OFF'})")

    def _connect_web3(self):
        try:
            rpc_url = self.config.get('rpc', {}).get(self.config['bot'].get('chain', 'arbitrum'), {}).get('url', "https://arb1.arbitrum.io/rpc")
            self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 15}))
            if self.w3.is_connected() and self.private_key:
                self.account = self.w3.eth.account.from_key(self.private_key)
                self.w3.eth.default_account = self.account.address
        except Exception as e:
            self.logger.error(f"Executor Web3接続エラー: {e}")

    def execute(self, opportunity: Dict) -> bool:
        """収益性のある機会を順番に実行（連結データを使用）"""
        try:
            if not opportunity.get('is_profitable', False):
                return False

            buy_dex = opportunity.get('buy_dex')
            sell_dex = opportunity.get('sell_dex')
            pair = opportunity['pair']

            self.logger.critical(f"🚀 完全アービトラージ開始: {buy_dex} ➔ {sell_dex} | {pair}")
            if self.dry_run:
                self.logger.warning("🛡️ Dry Runモード有効: トランザクションを送信せず、ログ出力のみ行います")

            # 1. 買う（USDC ➔ WETH）
            success1 = self._perform_swap(buy_dex, pair, is_buy=True, opp_data=opportunity)
            if not success1:
                self.logger.error(f"❌ {buy_dex} での買いに失敗したため、後半の売りを中止します")
                return False

            # 2. 売る（WETH ➔ USDC）
            success2 = self._perform_swap(sell_dex, pair, is_buy=False, opp_data=opportunity)
            if success2:
                self.logger.warning(f"🎯 完全アービトラージ成功終了！: {pair}")
                return True

            return False

        except Exception as e:
            self.logger.error(f"Executorエラー: {e}")
            return False

    def _check_and_approve(self, token_address: str, spender_address: str, amount: int) -> bool:
        try:
            token_contract = self.w3.eth.contract(address=token_address, abi=self._get_erc20_abi())
            allowance = token_contract.functions.allowance(self.account.address, spender_address).call()
            if allowance >= amount:
                return True

            if self.dry_run:
                self.logger.info(f"🛡️ Dry Run Approve: Spender {spender_address}")
                return True

            tx = token_contract.functions.approve(spender_address, 2**256 - 1).build_transaction({
                'from': self.account.address,
                'nonce': self.w3.eth.get_transaction_count(self.account.address),
                'maxFeePerGas': self.w3.eth.get_block('latest')['baseFeePerGas'] * 2,
                'maxPriorityFeePerGas': self.w3.to_wei(1, 'gwei'),
            })
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            return True
        except Exception as e:
            self.logger.error(f"Approve失敗: {e}")
            return False

    def _perform_swap(self, dex_name: str, pair: str, is_buy: bool, opp_data: Dict) -> bool:
        """1回のスワップ実行（🛡️ サンドイッチ防御パラメータ対応版）"""
        try:
            dex_config = self.config.get('dexes', {}).get(dex_name, {})
            router_address_raw = dex_config.get('router_address')
            if not router_address_raw:
                return False

            router_address = self.w3.to_checksum_address(router_address_raw)
            router = self.w3.eth.contract(address=router_address, abi=self._get_router_abi())

            # 🛡️ 連結パラメータから、スリッページ対応済みの数量を引き出す
            if is_buy:
                path = [self.usdc, self.weth]
                amount_in = int(opp_data['buy_amount_in'])
                expected_out = int(opp_data['buy_min_amount_out']) # 👈 0から本物の防御数値へ！
                token_to_approve = self.usdc
                direction_text = f"USDC ➔ WETH (買い) | 最小保証: {expected_out / 10**18:.5f} WETH"
            else:
                path = [self.weth, self.usdc]
                amount_in = int(opp_data['sell_amount_in'])
                expected_out = int(opp_data['sell_min_amount_out']) # 👈 0から本物の防御数値へ！
                token_to_approve = self.weth
                direction_text = f"WETH ➔ USDC (売り) | 最小保証: {expected_out / 10**6:.2f} USDC"

            self.logger.warning(f"[{dex_name}] {direction_text} トランザクション構築中...")

            # Approve確認
            if not self._check_and_approve(token_to_approve, router_address, amount_in):
                return False

            if self.dry_run:
                self.logger.info(f"🛡️ Dry Run: {dex_name} での注文送信をシミュレーション（成功判定）")
                return True

            # 本番トランザクション送信
            deadline = int(time.time()) + 180 # 3分以内
            tx = router.functions.swapExactTokensForTokens(
                amount_in,
                expected_out, # 👈 ここに防御壁をセット！MEVに価格をズラされていたら自動リバート
                path,
                self.account.address,
                deadline
            ).build_transaction({
                'from': self.account.address,
                'nonce': self.w3.eth.get_transaction_count(self.account.address),
                'maxFeePerGas': int(self.w3.eth.get_block('latest')['baseFeePerGas'] * 1.5),
                'maxPriorityFeePerGas': self.w3.to_wei(0.1, 'gwei'),
                'gas': 400000,
            })

            signed_tx = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)

            self.logger.critical(f"🚀 トランザクション送信完了! Hash: {tx_hash.hex()}")
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

            return receipt.status == 1

        except Exception as e:
            self.logger.error(f"{dex_name} Swap実行エラー: {e}")
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

    def _get_erc20_abi(self):
        return [
            {"constant": False, "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "payable": False, "stateMutability": "nonpayable", "type": "function"},
            {"constant": True, "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "payable": False, "stateMutability": "view", "type": "function"}
        ]