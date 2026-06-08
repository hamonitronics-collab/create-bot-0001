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
    完全DEX間アービトラージ版（Approve対応・動的パス切り替え・DryRun保護）
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

        # 🛡️ 安全装置：Trueの時は実際の送金を行わない
        self.dry_run = True

        self.w3 = None
        self.account = None
        self._connect_web3()

        # トークンアドレス（Mainnet/Arbitrum想定）
        self.weth = self.w3.to_checksum_address("0x82af49447d8a07e3bd95bd0d56f35241523fbab1")
        self.usdc = self.w3.to_checksum_address("0xaf88d065e77c8cC2239327C5EDb3A432268e5831") # Native USDC

        self.logger.info(f"Executor initialized (DryRun: {'ON' if self.dry_run else 'OFF'})")

    def _connect_web3(self):
        try:
            rpc_url = self.config.get('rpc', {}).get(self.config['bot'].get('chain', 'arbitrum'), {}).get('url', "https://arb1.arbitrum.io/rpc")
            self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 15}))

            if self.w3.is_connected():
                self.logger.info(f"✅ Executor Web3接続成功 | Chain ID: {self.w3.eth.chain_id}")
                if self.private_key:
                    self.account = self.w3.eth.account.from_key(self.private_key)
                    self.w3.eth.default_account = self.account.address
                    self.logger.info(f"✅ アカウント設定完了: {self.account.address[:10]}...")
                else:
                    self.logger.warning("PRIVATE_KEYが設定されていません。実行にはキーが必要です。")
            else:
                self.logger.error("Executor Web3接続失敗")
        except Exception as e:
            self.logger.error(f"Executor Web3接続エラー: {e}")

    def execute(self, opportunity: Dict) -> bool:
        try:
            if not opportunity.get('is_profitable', False):
                return False

            buy_dex = opportunity.get('buy_dex')
            sell_dex = opportunity.get('sell_dex')
            pair = opportunity['pair']

            self.logger.critical(f"🚀 完全アービトラージ開始: {buy_dex} で買い → {sell_dex} で売り | {pair}")

            if self.dry_run:
                self.logger.warning("⚠️ Dry Runモード有効: トランザクションのシミュレーションのみ行います")

            # 1. 買う（USDC → WETH）
            success1 = self._perform_swap(buy_dex, pair, is_buy=True)
            if not success1:
                self.logger.error(f"❌ {buy_dex} での買いに失敗したため、アービトラージを中止します")
                return False

            # 2. 売る（WETH → USDC）
            success2 = self._perform_swap(sell_dex, pair, is_buy=False)
            if success2:
                self.logger.warning(f"✅ 完全アービトラージ完了: {pair}")
                self.consecutive_failures = 0
                return True

            return False

        except Exception as e:
            self.logger.error(f"Executorエラー: {e}")
            self.consecutive_failures += 1
            return False

    def _check_and_approve(self, token_address: str, spender_address: str, amount: int) -> bool:
        """ルーターに対してトークンの使用許可（Approve）を出す"""
        try:
            token_contract = self.w3.eth.contract(address=token_address, abi=self._get_erc20_abi())

            # 現在の許可額を確認
            allowance = token_contract.functions.allowance(self.account.address, spender_address).call()

            if allowance >= amount:
                self.logger.debug("✅ 十分なApproveが既にされています")
                return True

            self.logger.info("🔄 Approveトランザクションを送信します...")

            if self.dry_run:
                self.logger.info(f"🛡️ Dry Run: Approveシミュレーション完了 (Spender: {spender_address})")
                return True

            # 無限の許可を与える（2**256 - 1）
            max_amount = 2**256 - 1
            tx = token_contract.functions.approve(spender_address, max_amount).build_transaction({
                'from': self.account.address,
                'nonce': self.w3.eth.get_transaction_count(self.account.address),
                'maxFeePerGas': self.w3.eth.get_block('latest')['baseFeePerGas'] * 2,
                'maxPriorityFeePerGas': self.w3.to_wei(1, 'gwei'),
            })

            signed_tx = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)

            self.logger.info(f"⏳ Approve Tx送信: {tx_hash.hex()}")
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

            return receipt.status == 1

        except Exception as e:
            self.logger.error(f"Approve失敗: {e}")
            return False

    def _perform_swap(self, dex_name: str, pair: str, is_buy: bool) -> bool:
        """1回のSwap実行"""
        try:
            # 1. 対象DEXのルーターアドレスを config から取得
            dex_config = self.config.get('dexes', {}).get(dex_name, {})
            router_address_raw = dex_config.get('router_address')

            if not router_address_raw:
                self.logger.error(f"{dex_name} のルーターアドレスが設定されていません")
                return False

            router_address = self.w3.to_checksum_address(router_address_raw)
            router = self.w3.eth.contract(address=router_address, abi=self._get_router_abi())

            # 2. パスと入金額の決定
            # 買うとき(USDC→WETH): USDCを支払う / 売るとき(WETH→USDC): WETHを支払う
            if is_buy:
                path = [self.usdc, self.weth]
                amount_in = int(1 * 10**6) # テスト: 1 USDC (decimals=6)
                token_to_approve = self.usdc
                direction_text = "USDC → WETH (買い)"
            else:
                path = [self.weth, self.usdc]
                amount_in = self.w3.to_wei(0.001, 'ether') # テスト: 0.001 WETH
                token_to_approve = self.weth
                direction_text = "WETH → USDC (売り)"

            self.logger.warning(f"[{dex_name}] {direction_text} を準備中...")

            # 3. ルーターへのApprove確認
            if not self._check_and_approve(token_to_approve, router_address, amount_in):
                return False

            # 4. ガス代の設定
            base_fee = self.w3.eth.get_block('latest')['baseFeePerGas']
            max_priority_fee = self.w3.to_wei(1, 'gwei')
            max_fee_per_gas = base_fee * 2 + max_priority_fee

            deadline = int(time.time()) + 300 # 5分後
            expected_out = 0 # 将来的にProfitabilityから正確な amountOutMin を渡す

            if self.dry_run:
                self.logger.info(f"🛡️ Dry Run: {dex_name} での {direction_text} スワップ成功判定")
                return True

            # 5. スワップの送信
            tx = router.functions.swapExactTokensForTokens(
                amount_in,
                expected_out, # ⚠️ スリッページ許容額
                path,
                self.account.address,
                deadline
            ).build_transaction({
                'from': self.account.address,
                'nonce': self.w3.eth.get_transaction_count(self.account.address),
                'maxFeePerGas': max_fee_per_gas,
                'maxPriorityFeePerGas': max_priority_fee,
                'gas': 500000,
            })

            signed_tx = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)

            self.logger.critical(f"✅ {dex_name} Tx送信完了: {tx_hash.hex()}")

            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
            status = '成功' if receipt.status == 1 else '失敗'
            self.logger.warning(f"🏁 {dex_name} トランザクション結果: {status}")

            return receipt.status == 1

        except Exception as e:
            self.logger.error(f"{dex_name} Swapエラー: {e}")
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
        """トークンのApproveや残高確認用ABI"""
        return [
            {"constant": False, "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "payable": False, "stateMutability": "nonpayable", "type": "function"},
            {"constant": True, "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "payable": False, "stateMutability": "view", "type": "function"},
            {"constant": True, "inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "payable": False, "stateMutability": "view", "type": "function"}
        ]