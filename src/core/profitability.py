import os
from typing import Dict, Optional
from web3 import Web3

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier


class ProfitabilityCalculator:
    """
    アービトラージ機会の収益性を計算するモジュール
    精密計算版（リアルタイムガス代・スリッページ・取引額考慮）
    """

    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier):
        self.config = config
        self.logger = logger
        self.telegram = telegram

        trading = config.get('trading', {})
        self.min_profit_usd = trading.get('min_profit_usd', 0.1)
        self.max_slippage = trading.get('max_slippage', 0.5)

        # 💡 アービトラージで使用する1回あたりの標準取引金額（USD想定）
        # config.yamlに 'trade_amount_usd: 100' などがあれば取得、なければデフォルト100ドル
        self.trade_amount_usd = trading.get('trade_amount_usd', 100.0)

        # Web3の初期化（ガス代取得用）
        self.w3 = None
        self._connect_web3()

        self.logger.info(f"ProfitabilityCalculator initialized (min_profit: ${self.min_profit_usd}, trade_amount: ${self.trade_amount_usd})")

    def _connect_web3(self):
        """ガス代計算のためにRPCへ接続"""
        try:
            rpc_url = self.config.get('rpc', {}).get(self.config['bot'].get('chain', 'arbitrum'), {}).get('url', "https://arb1.arbitrum.io/rpc")
            self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 10}))
            if not self.w3.is_connected():
                self.logger.error("ProfitabilityCalculator: Web3接続に失敗しました")
        except Exception as e:
            self.logger.error(f"ProfitabilityCalculator Web3エラー: {e}")

    def calculate_profitability(self, opportunity: Dict) -> Optional[Dict]:
        """
        機会の収益性を正確に計算し、実行可否を判断
        """
        try:
            price_diff_percent = opportunity.get('price_diff_percent', 0.0)
            pair = opportunity.get('pair', 'UNKNOWN')

            # === 1. 粗利の計算 (Gross Profit) ===
            # 取引額に対して、価格差のパーセンテージ分が理論上の利益
            gross_profit_usd = self.trade_amount_usd * (price_diff_percent / 100)

            # === 2. スリッページによる損失見込み ===
            # 最大スリッページを全額引くのは保守的すぎるため、設定値の半分を想定損失とする
            slippage_loss_usd = self.trade_amount_usd * ((self.max_slippage / 2) / 100)

            # === 3. ガス代の計算 (Network Gas Fee) ===
            gas_cost_usd = 0.0
            if self.w3 and self.w3.is_connected():
                # 2回のSwapとApproveを考慮した推定ガスリミット (Arbitrum想定)
                estimated_gas_limit = 500000

                # 現在のネットワークガス価格を取得（Wei）
                gas_price_wei = self.w3.eth.gas_price

                # Arbitrum上の推定ガス代 (ETH)
                gas_cost_eth = float(self.w3.from_wei(estimated_gas_limit * gas_price_wei, 'ether'))

                # ETH価格を簡易的に掛けてUSD換算 (※暫定的に$2500計算。精査時は動的取得を推奨)
                eth_price_usd = 2500.0
                gas_cost_usd = gas_cost_eth * eth_price_usd
            else:
                # 接続エラー時のフォールバック値（Arbitrumの平均的なガス代を少し高めに見積もる）
                self.logger.warning("Web3未接続のため、デフォルトのガス代($0.1)を使用します")
                gas_cost_usd = 0.1

            # === 4. 純利益の計算 (Net Profit) ===
            net_profit_usd = gross_profit_usd - slippage_loss_usd - gas_cost_usd

            # 設定した最低利益（min_profit_usd）を超えているか判定
            is_profitable = net_profit_usd >= self.min_profit_usd

            result = {
                **opportunity,
                "trade_amount_usd": self.trade_amount_usd,
                "gross_profit_usd": round(gross_profit_usd, 3),
                "gas_cost_usd": round(gas_cost_usd, 3),
                "slippage_loss_usd": round(slippage_loss_usd, 3),
                "estimated_profit_usd": round(net_profit_usd, 3),
                "is_profitable": is_profitable,
                "reason": "実行可能" if is_profitable else f"純利益未達 (${net_profit_usd:.2f} < ${self.min_profit_usd})"
            }

            if is_profitable:
                self.logger.warning(
                    f"✅ 収益性OK: 純利益 ${net_profit_usd:.2f} "
                    f"(粗利 ${gross_profit_usd:.2f} - ガス代 ${gas_cost_usd:.3f} - 損失見込 ${slippage_loss_usd:.2f}) | {pair}"
                )
            else:
                self.logger.debug(
                    f"利益不足: 純利益 ${net_profit_usd:.2f} "
                    f"(粗利 ${gross_profit_usd:.2f} - ガス代 ${gas_cost_usd:.3f} - 損失見込 ${slippage_loss_usd:.2f})"
                )

            return result

        except Exception as e:
            self.logger.error(f"収益性計算エラー: {e}")
            return None