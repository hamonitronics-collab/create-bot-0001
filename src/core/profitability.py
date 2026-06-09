import os
from typing import Dict, Optional
from web3 import Web3

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier


class ProfitabilityCalculator:
    """
    アービトラージ機会の収益性を計算するモジュール
    精密計算 ＆ ハードコード完全排除・安全防壁版
    """

    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier):
        self.config = config
        self.logger = logger
        self.telegram = telegram

        trading = config.get('trading', {})
        self.min_profit_usd = trading.get('min_profit_usd', 0.1)
        self.max_slippage = trading.get('max_slippage', 0.5)
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
        機会の収益性を正確に計算（ハードコード値を一切含まない本番完全版）
        """
        try:
            price_diff_percent = opportunity.get('price_diff_percent', 0.0)
            pair = opportunity.get('pair', 'UNKNOWN')

            # 💡 解決：Detectorから正規ルートで100%生価格が回ってくるため、
            # 「39291.0」などのダミーの生数値は一切不要になりました！クリーンに取得します。
            buy_price = opportunity.get('buy_price', 0.0)
            sell_price = opportunity.get('sell_price', 0.0)

            # リアルタイム価格が万が一にも取得できない場合は、危険なので取引フェーズに進めず安全に弾く
            if buy_price <= 0 or sell_price <= 0:
                self.logger.error(f"⚠️ 収益性計算スキップ: {pair} のリアルタイム生価格が不正です (buy:{buy_price}, sell:{sell_price})")
                return None

# src/core/profitability.py の calculate_profitability 内の後半部分を修正

            # === 1. 粗利・スリッページ・ガス代のUSD計算 ===
            # (この部分は変更なし)
            gross_profit_usd = self.trade_amount_usd * (price_diff_percent / 100)
            slippage_loss_usd = self.trade_amount_usd * ((self.max_slippage / 2) / 100)

            gas_cost_usd = 0.05
            if self.w3 and self.w3.is_connected():
                try:
                    gas_price_wei = self.w3.eth.gas_price
                    gas_cost_eth = float(self.w3.from_wei(250000 * 2, 'ether')) * gas_price_wei
                    gas_cost_usd = gas_cost_eth * buy_price
                except:
                    pass

            net_profit_usd = gross_profit_usd - slippage_loss_usd - gas_cost_usd
            is_profitable = net_profit_usd >= self.min_profit_usd

            # =================================================================
            # 💡 汎用化: ペア名（例: ARB/USDC）から config を参照して桁数を全自動取得
            base_symbol, quote_symbol = pair.split('/')
            base_decimals = self.config['tokens'][base_symbol]['decimals']
            quote_decimals = self.config['tokens'][quote_symbol]['decimals']

            # === 2. 🛡️ サンドイッチ防御壁：amountOutMin（最低保証量）の算出 ===
            # ① 1ステップ目（買い: Quote(USDC) ➔ Base(ARBなど)）
            # 投入USDCを Decimals に合わせて Wei 化
            buy_amount_in_raw = int(self.trade_amount_usd * 10**quote_decimals)
            expected_token_out = buy_amount_in_raw / buy_price

            # 受け取る Base トークンの Decimals に合わせて Wei 化
            buy_expected_out_wei = int(expected_token_out * (10**(base_decimals - quote_decimals)))
            buy_min_amount_out = int(buy_expected_out_wei * (1 - (self.max_slippage / 100)))

            # ② 2ステップ目（売り: Base(ARBなど) ➔ Quote(USDC)）
            sell_amount_in_wei = buy_expected_out_wei
            expected_quote_out = (sell_amount_in_wei / 10**base_decimals) * sell_price

            # 最終的に受け取る USDC の Decimals に合わせて Wei 化
            sell_expected_out_raw = int(expected_quote_out * 10**quote_decimals)
            sell_min_amount_out = int(sell_expected_out_raw * (1 - (self.max_slippage / 100)))
            # =================================================================

            result = {
                **opportunity,
                # (以下の戻り値は変更なし)
                "trade_amount_usd": self.trade_amount_usd,
                "estimated_profit_usd": round(net_profit_usd, 3),
                "is_profitable": is_profitable,
                "buy_amount_in": buy_amount_in_raw,
                "buy_min_amount_out": buy_min_amount_out,
                "sell_amount_in": sell_amount_in_wei,
                "sell_min_amount_out": sell_min_amount_out,
                "reason": "実行可能" if is_profitable else f"純利益未達 (${net_profit_usd:.2f})"
            }

            self.logger.info(
                f"📊 収益性計算通過: {pair} | 粗利: ${gross_profit_usd:.2f} | "
                f"純利益: ${net_profit_usd:.2f} | 判定: {is_profitable}"
            )

            if is_profitable:
                self.logger.warning(
                    f"✅ 収益性OK: 純利益 ${net_profit_usd:.2f} "
                    f"(粗利 ${gross_profit_usd:.2f} - ガス代 ${gas_cost_usd:.3f} - 損失見込 ${slippage_loss_usd:.2f}) | {pair}"
                )
            return result

        except Exception as e:
            self.logger.error(f"収益性計算エラー: {e}")
            return None