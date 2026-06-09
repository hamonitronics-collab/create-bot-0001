import os
from typing import Dict, Optional
from web3 import Web3

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier


class ProfitabilityCalculator:
    """
    アービトラージ機会の収益性を計算するモジュール
    精密計算 ＆ サンドイッチ防御壁（最低保証量計算）搭載版
    """

    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier):
        self.config = config
        self.logger = logger
        self.telegram = telegram

        trading = config.get('trading', {})
        self.min_profit_usd = trading.get('min_profit_usd', 0.1)
        self.max_slippage = trading.get('max_slippage', 0.5) # 例: 0.5%
        self.trade_amount_usd = trading.get('trade_amount_usd', 100.0)

        self.w3 = None
        self._connect_web3()

        self.logger.info(f"ProfitabilityCalculator initialized (min_profit: ${self.min_profit_usd}, trade_amount: ${self.trade_amount_usd})")

    def _connect_web3(self):
        try:
            rpc_url = self.config.get('rpc', {}).get(self.config['bot'].get('chain', 'arbitrum'), {}).get('url', "https://arb1.arbitrum.io/rpc")
            self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 10}))
        except Exception as e:
            self.logger.error(f"ProfitabilityCalculator Web3接続エラー: {e}")

    def calculate_profitability(self, opportunity: Dict) -> Optional[Dict]:
        """
        機会の収益性を正確に計算し、サンドイッチ防御用の最低保証出力量（amountOutMin）を算出
        """
        try:
            price_diff_percent = opportunity.get('price_diff_percent', 0.0)
            pair = opportunity.get('pair', 'UNKNOWN')
            buy_price = opportunity.get('buy_price', 0.0)
            sell_price = opportunity.get('sell_price', 0.0)

            if buy_price == 0 or sell_price == 0:
                return None

            # === 1. 粗利・スリッページ・ガス代のUSD計算 ===
            gross_profit_usd = self.trade_amount_usd * (price_diff_percent / 100)
            slippage_loss_usd = self.trade_amount_usd * ((self.max_slippage / 2) / 100)

            # ガス代（フォールバック：$0.05。Web3接続時はリアルタイム）
            gas_cost_usd = 0.05
            if self.w3 and self.w3.is_connected():
                try:
                    gas_price_wei = self.w3.eth.gas_price
                    gas_cost_eth = float(self.w3.from_wei(250000 * 2, 'ether')) * gas_price_wei # 2スワップ分
                    gas_cost_usd = gas_cost_eth * 2500.0 # ETH=$2500換算
                except:
                    pass

            net_profit_usd = gross_profit_usd - slippage_loss_usd - gas_cost_usd
            is_profitable = net_profit_usd >= self.min_profit_usd

            # === 2. 🛡️ サンドイッチ防御壁：amountOutMin（最低保証量）の算出 (Wei単位) ===
            # ① 1ステップ目（買い: USDC → WETH）の計算
            # 投入するUSDCの量 (100ドル = 100 * 10^6 Wei)
            buy_amount_in_raw = int(self.trade_amount_usd * 10**6)
            # 期待されるWETHの量 = 投入USDC / 買い価格 (1 ETHあたりのUSDC)
            expected_weth_out = buy_amount_in_raw / buy_price # 単位はUSDCと同等スケール
            # WETHのDecimals(18)に調整してWei化
            buy_expected_out_wei = int(expected_weth_out * 10**12)
            # スリッページを引いた「最低保証量」
            buy_min_amount_out = int(buy_expected_out_wei * (1 - (self.max_slippage / 100)))

            # ② 2ステップ目（売り: WETH → USDC）の計算
            # 投入するWETHは、1ステップ目で「期待されたWETH量（スリッページ前）」と仮定
            sell_amount_in_wei = buy_expected_out_wei
            # 期待されるUSDCの量 = 投入WETH(ETH単位) * 売り価格
            expected_usdc_out = (sell_amount_in_wei / 10**18) * sell_price
            sell_expected_out_mwei = int(expected_usdc_out * 10**6)
            # スリッページを引いた「最低保証量」
            sell_min_amount_out = int(sell_expected_out_mwei * (1 - (self.max_slippage / 100)))

            result = {
                **opportunity,
                "trade_amount_usd": self.trade_amount_usd,
                "estimated_profit_usd": round(net_profit_usd, 3),
                "is_profitable": is_profitable,
                # 🛡️ 実行エンジンに引き渡す防御壁パラメータ
                "buy_amount_in": buy_amount_in_raw,
                "buy_min_amount_out": buy_min_amount_out,
                "sell_amount_in": sell_amount_in_wei,
                "sell_min_amount_out": sell_min_amount_out,
                "reason": "実行可能" if is_profitable else f"純利益未達 (${net_profit_usd:.2f})"
            }

            if is_profitable:
                self.logger.warning(f"✅ 収益性OK: 純利益 ${net_profit_usd:.2f} (ガス代 ${gas_cost_usd:.3f}) | {pair}")
            return result

        except Exception as e:
            self.logger.error(f"収益性計算エラー: {e}")
            return None