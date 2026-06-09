# src/core/executor.py
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
    【完全自動ルーティング・汎用化対応版】
    """

    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier):
        self.config = config
        self.logger = logger
        self.telegram = telegram

        load_dotenv(override=True)
        self.private_key = os.getenv("PRIVATE_KEY")
        self.dry_run = True  # 🛡️ シミュレーション継続

        self.w3 = None
        self.account = None
        self._connect_web3()

        # 💡 WETHやUSDCのハードコードアドレス宣言を完全に削除しました！

        self.logger.info(f"🚀 Executor initialized (🚨 DryRun: {'ON' if self.dry_run else 'OFF'})")

    # (_connect_web3, execute, _check_and_approve メソッドは変更なし)
    def _connect_web3(self):
        try:
            rpc_url = self.config.get('rpc', {}).get(self.config['bot'].get('chain', 'arbitrum'), {}).get('url', "https://arb1.arbitrum.io/rpc")
            self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 5}))
            if self.w3.is_connected() and self.private_key:
                self.account = self.w3.eth.account.from_key(self.private_key)
                self.w3.eth.default_account = self.account.address
        except Exception as e:
            self.logger.error(f"Executor Web3接続エラー: {e}")

    def execute(self, opportunity: Dict) -> bool:
        try:
            if not opportunity.get('is_profitable', False):
                return False

            buy_dex = opportunity.get('buy_dex')
            sell_dex = opportunity.get('sell_dex')
            pair = opportunity['pair']

            # 🚨 ⚠️ 修正ポイント2: 最初の実弾テストにおける「絶対無敵のセーフティロック」
            # 万が一利益計算がバグって巨大な注文を出そうとしても、1回あたり最大2ドル以下に強制カットします。
            trade_amount_usd = opportunity.get('trade_amount_usd', 100.0)
            if trade_amount_usd > 2.0:
                self.logger.warning(f"🛡️ セーフティ作動: 投入額が ${trade_amount_usd} になっています。初回テストのため $2.0 に強制縮小します。")
                # 金額に合わせて、引き渡された Wei 単位のパラメータも2ドル分（2%分）に縮小デスケールする
                scale = 2.0 / trade_amount_usd
                opportunity['buy_amount_in'] = int(opportunity['buy_amount_in'] * scale)
                opportunity['buy_min_amount_out'] = int(opportunity['buy_min_amount_out'] * scale)
                opportunity['sell_amount_in'] = int(opportunity['sell_amount_in'] * scale)
                opportunity['sell_min_amount_out'] = int(opportunity['sell_min_amount_out'] * scale)

            self.logger.critical(f"🔥 【実弾注文】完全アービトラージ送信開始: {buy_dex} ➔ {sell_dex} | {pair}")

            # 1. 買う（USDC ➔ WETH）
            success1 = self._perform_swap(buy_dex, pair, is_buy=True, opp_data=opportunity)
            if not success1:
                self.logger.error(f"❌ {buy_dex} での買いトランザクションが失敗（またはリバート）したため、後半の売りを安全に中止します")
                return False

            # 2. 売る（WETH ➔ USDC）
            success2 = self._perform_swap(sell_dex, pair, is_buy=False, opp_data=opportunity)
            if success2:
                self.logger.warning(f"🎯 空間アービトラージの2ステップがオンチェーンで完全成功しました！: {pair}")
                return True

            return False

        except Exception as e:
            self.logger.error(f"Executor実弾実行エラー: {e}")
            return False

    def _check_and_approve(self, token_address: str, spender_address: str, amount: int) -> bool:
        """必要に応じてDEXルーターへの無限Approveトランザクションを本当に送信する"""
        try:
            token_contract = self.w3.eth.contract(address=token_address, abi=self._get_erc20_abi())
            allowance = token_contract.functions.allowance(self.account.address, spender_address).call()

            if allowance >= amount:
                self.logger.info("✅ すでに十分な許容量（Approve）がルーターに与えられています")
                return True

            self.logger.warning(f"🔄 Approveが必要（現在値:{allowance} < 必要数:{amount}）。オンチェーンにTxを送信します...")

            # ガス代の設定
            base_fee = self.w3.eth.get_block('latest')['baseFeePerGas']
            max_priority_fee = self.w3.to_wei(1, 'gwei') # 少し強めにして確実に通す
            max_fee_per_gas = int(base_fee * 2 + max_priority_fee)

            # 無限承認 (2^256 - 1)
            max_amount = 2**256 - 1
            tx = token_contract.functions.approve(spender_address, max_amount).build_transaction({
                'from': self.account.address,
                'nonce': self.w3.eth.get_transaction_count(self.account.address),
                'maxFeePerGas': max_fee_per_gas,
                'maxPriorityFeePerGas': max_priority_fee,
            })

            signed_tx = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)

            self.logger.warning(f"⏳ Approveトランザクションを送信しました。ハッシュ: {tx_hash.hex()}")
            self.logger.warning("⏳ ブロックに取り込まれるのを待機中（最大60秒）...")

            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

            if receipt.status == 1:
                self.logger.warning("✅ ルーターへのApprove（トークン使用許可）が正常に完了しました！")
                return True
            else:
                self.logger.error("❌ Approveトランザクションがリバート（失敗）しました")
                return False

        except Exception as e:
            self.logger.error(f"Approveオンチェーン送信エラー: {e}")
            return False

    def _perform_swap(self, dex_name: str, pair: str, is_buy: bool, opp_data: Dict) -> bool:
        """オンチェーンスワップ実行（動的パス対応）"""
        try:
            dex_config = self.config.get('dexes', {}).get(dex_name, {})
            router_address_raw = dex_config.get('router_address')
            if not router_address_raw:
                return False

            router_address = self.w3.to_checksum_address(router_address_raw)
            router = self.w3.eth.contract(address=router_address, abi=self._get_router_abi())

            # 💡 汎用化: ペア名から config に登録されたアドレスを動的に引っ張る
            base_symbol, quote_symbol = pair.split('/')
            base_token_address = self.w3.to_checksum_address(self.config['tokens'][base_symbol]['address'])
            quote_token_address = self.w3.to_checksum_address(self.config['tokens'][quote_symbol]['address'])

            if is_buy:
                # 買い: Quote(USDC) ➔ Base(ARB)
                path = [quote_token_address, base_token_address]
                amount_in = int(opp_data['buy_amount_in'])
                expected_out = int(opp_data['buy_min_amount_out'])
                token_to_approve = quote_token_address
                direction_text = f"{quote_symbol} ➔ {base_symbol} (買い)"
            else:
                # 売り: Base(ARB) ➔ Quote(USDC)
                path = [base_token_address, quote_token_address]
                amount_in = int(opp_data['sell_amount_in'])
                expected_out = int(opp_data['sell_min_amount_out'])
                token_to_approve = base_token_address
                direction_text = f"{base_symbol} ➔ {quote_symbol} (売り)"

            self.logger.warning(f"[{dex_name}] {direction_text} トランザクション構築中...")

            # 1. ルーターへApprove（足りなければ自動送信）
            if not self._check_and_approve(token_to_approve, router_address, amount_in):
                return False

            # 2. 最新のブロックから動的ガス代を算出
            base_fee = self.w3.eth.get_block('latest')['baseFeePerGas']
            max_priority_fee = self.w3.to_wei(0.1, 'gwei') # Arbitrumの標準
            max_fee_per_gas = int(base_fee * 1.3 + max_priority_fee)

            deadline = int(time.time()) + 180 # 3分間有効

            # 3. リアルタイムトランザクションの組み立て
            tx = router.functions.swapExactTokensForTokens(
                amount_in,
                expected_out, # 🛡️ サンドイッチ防御パラメータ（最低保証）
                path,
                self.account.address,
                deadline
            ).build_transaction({
                'from': self.account.address,
                'nonce': self.w3.eth.get_transaction_count(self.account.address),
                'maxFeePerGas': max_fee_per_gas,
                'maxPriorityFeePerGas': max_priority_fee,
                'gas': 450000, # スワップに十分な上限
            })

            # 4. 署名と送信
            signed_tx = self.w3.eth.account.sign_transaction(tx, self.private_key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)

            self.logger.critical(f"🚀 オンチェーンへTx送信完了! ハッシュ: {tx_hash.hex()}")
            self.logger.warning("⏳ スワップがブロックに格納されるのを待っています...")

            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

            status = '成功（SUCCESS）' if receipt.status == 1 else '失敗（REVERTED）'
            self.logger.warning(f"🏁 {dex_name} スワップ結果: {status} | Block: {receipt.blockNumber}")

            return receipt.status == 1

        except Exception as e:
            self.logger.error(f"{dex_name} オンチェーンSwap実行エラー: {e}")
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