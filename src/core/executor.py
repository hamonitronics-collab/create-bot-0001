from typing import Dict, Optional
from web3 import Web3
from web3.exceptions import ContractLogicError
import json

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier


class Executor:
    """
    アービトラージ機会を実行するモジュール
    現在: Uniswap V3 Quoterによる本物見積もり段階
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

        # Checksumアドレスに統一
        self.router_address = self.w3.to_checksum_address("0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45")
        self.quoter_address = self.w3.to_checksum_address("0x61fFE014bA17989E743c5F6cB21bF9697530B21e")

        # トークンアドレス（Sepolia）
        self.weth = self.w3.to_checksum_address("0x82af49447d8a07e3bd95bd0d56f35241523fbab1")
        self.usdc = self.w3.to_checksum_address("0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8")

        self.logger.info("Executor initialized (Uniswap V3 Quoter連携完了)")

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
        try:
            if not opportunity.get('is_profitable', False):
                return False

            pair = opportunity['pair']
            self.logger.warning(f"🚀 Quoter本物見積もり開始: {pair}")

            quoter_contract = self.w3.eth.contract(address=self.quoter_address, abi=self._get_quoter_abi())

            # Quoter呼び出し
            amount_in = self.w3.to_wei(0.01, 'ether')  # 0.01 ETH分で見積もり

            amount_out = quoter_contract.functions.quoteExactInputSingle(
                self.weth,
                self.usdc,
                3000,          # 0.3% fee
                amount_in,
                0
            ).call()

            amount_out_human = self.w3.from_wei(amount_out, 'mwei')  # USDCは6 decimals

            self.logger.info(f"Quoter見積もり結果: {amount_out_human:.4f} USDC")

            # ガス代見積もり
            gas_estimate = 250000
            gas_price = self.w3.eth.gas_price
            gas_cost_eth = self.w3.from_wei(gas_price * gas_estimate, 'ether')
            gas_cost_usd = float(gas_cost_eth) * 2500

            final_profit = opportunity.get('estimated_profit_usd', 0) - gas_cost_usd

            if final_profit > 0.5:
                self.logger.warning(f"✅ Quoter本物見積もり完了 | 最終期待利益 ${final_profit:.2f} | {pair}")
                self.consecutive_failures = 0
                return True
            else:
                self.logger.warning(f"❌ ガス代考慮後赤字の見込み: {pair}")
                return False

        except Exception as e:
            self.logger.error(f"Quoter実行エラー: {e}")
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.max_consecutive_failures:
                self.logger.critical("連続失敗のためBot停止を推奨します")
            return False

    def _get_quoter_abi(self):
        """Quoter ABI（簡易版）"""
        return [{
            "inputs": [
                {"name": "tokenIn", "type": "address"},
                {"name": "tokenOut", "type": "address"},
                {"name": "fee", "type": "uint24"},
                {"name": "amountIn", "type": "uint256"},
                {"name": "sqrtPriceLimitX96", "type": "uint160"}
            ],
            "name": "quoteExactInputSingle",
            "outputs": [{"name": "amountOut", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function"
        }]