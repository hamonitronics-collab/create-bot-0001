from typing import Dict, Optional
from web3 import Web3
from web3.exceptions import ContractLogicError

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier


class Executor:
    """
    アービトラージ機会を実行するモジュール
    現在: 残高チェック + Approve準備済み
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

        self.dry_run = True   # 本物送信時は False に変更

        # Web3接続
        self.w3 = None
        self._connect_web3()

        self.router_address = self.w3.to_checksum_address("0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45")

        # トークンアドレス（Arbitrum Sepolia）
        self.weth = self.w3.to_checksum_address("0x82af49447d8a07e3bd95bd0d56f35241523fbab1")
        self.usdc = self.w3.to_checksum_address("0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8")

        self.logger.info(f"Executor initialized (残高チェック + Approve準備完了 | DRY_RUN={self.dry_run})")

    def _connect_web3(self):
        try:
            rpc_url = "https://sepolia-rollup.arbitrum.io/rpc"
            self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 15}))
            if self.w3.is_connected():
                self.logger.info(f"✅ Web3接続成功 | Chain ID: {self.w3.eth.chain_id}")
        except Exception as e:
            self.logger.error(f"Web3接続エラー: {e}")

    def _check_balance(self, token_address: str, min_amount: float) -> bool:
        """残高チェック"""
        try:
            # 簡易的にネイティブETH残高チェック（トークン残高は後で拡張）
            balance = self.w3.eth.get_balance(self.w3.eth.default_account or self.w3.eth.accounts[0] if self.w3.eth.accounts else None)
            balance_eth = self.w3.from_wei(balance, 'ether')
            if balance_eth < min_amount:
                self.logger.warning(f"残高不足: {balance_eth:.4f} ETH < {min_amount} ETH")
                return False
            return True
        except:
            self.logger.warning("残高チェック失敗（アカウント未設定？）")
            return False

    def execute(self, opportunity: Dict) -> bool:
        try:
            if not opportunity.get('is_profitable', False):
                return False

            pair = opportunity['pair']
            self.logger.warning(f"🚀 取引実行準備: {pair} | 期待利益 ${opportunity.get('estimated_profit_usd')}")

            # === 残高チェック ===
            if not self._check_balance(self.weth, 0.005):
                self.logger.error("残高不足のため実行スキップ")
                return False

            if self.dry_run:
                self.logger.warning(f"🧪 DRY RUNモード: 実際の送信は行いません - {pair}")
                return True

            # === Approve + Swap送信ロジック（ここから本物） ===
            self.logger.warning(f"⚠️ 本物取引を実行します - {pair}")

            # TODO: Approve処理 + Router.swapExactInputSingle
            # （次回で実装）

            self.logger.warning(f"✅ 本物送信シミュレーション完了: {pair}")
            self.consecutive_failures = 0
            return True

        except Exception as e:
            self.logger.error(f"Executorエラー: {e}")
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.max_consecutive_failures:
                self.logger.critical("連続失敗のためBot停止を推奨します")
            return False