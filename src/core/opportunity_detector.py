import logging
from typing import List, Dict

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier


class OpportunityDetector:
    """
    価格情報からアービトラージ機会を検知するモジュール
    DEXアダプター構造・生価格引き渡し対応版
    """

    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier):
        self.config = config
        self.logger = logger
        self.telegram = telegram

        trading = config.get('trading', {})
        self.threshold = trading.get('price_difference_threshold', 0.3) # 例: 0.3%

        self.logger.info(f"OpportunityDetector initialized (threshold: {self.threshold}%)")

    def detect_opportunities(self, prices: Dict[str, Dict[str, Dict[str, float]]]) -> List[Dict]:
        """
        価格データから往復見積もり(Round-Trip)ベースのアービトラージ機会を検知する
        """
        opportunities = []

        for pair, dex_prices in prices.items():
            buy_prices = dex_prices.get("buy", {})
            sell_prices = dex_prices.get("sell", {})

            if len(buy_prices) < 2 or len(sell_prices) < 2:
                continue

            # 全DEXの組み合わせ（Aで買ってBで売る）を総当たりで検証
            for buy_dex, buy_price in buy_prices.items():
                for sell_dex, sell_price in sell_prices.items():
                    if buy_dex == sell_dex:
                        continue

                    # 💡 往復見積もりロジック:
                    # buy_price = 1 USDC あたりの獲得 Base トークン量（スリッページ考慮済）
                    # sell_price = 1 Base トークンあたりの獲得 USDC 量（スリッページ考慮済）
                    # したがって、1 USDC を投入した場合の最終的な手残り USDC は、
                    # buy_price * sell_price となる。
                    # ※ 注: get_price の戻り値の定義に依存します。現在の get_price は
                    # effective_price = real_amount_in / real_amount_out を返しています。
                    # これは「1 Base を買うのに必要な USDC」または「1 USDC を買うのに必要な Base」です。

                    # 【重要】現在の get_price の仕様に合わせた計算
                    # buy_price (USDC -> ARB): 1 ARB を手に入れるための USDC コスト
                    # sell_price (ARB -> USDC): 1 USDC を手に入れるための ARB コスト

                    # 100 USDC 投入した場合の獲得 ARB 数:
                    amount_in_usd = self.config.get('trading', {}).get('trade_amount_usd', 100.0)
                    obtained_base = amount_in_usd / buy_price

                    # 獲得した ARB を全て売却して得られる USDC 数:
                    final_usdc = obtained_base / sell_price

                    # 最終的な USDC が、初期の 100 USDC より多ければ利益！
                    profit_ratio = (final_usdc - amount_in_usd) / amount_in_usd

                    if profit_ratio > self.threshold:
                        opp = {
                            "pair": pair,
                            "buy_dex": buy_dex,
                            "sell_dex": sell_dex,
                            "buy_price": buy_price,
                            "sell_price": sell_price,
                            "price_diff_pct": profit_ratio * 100, # 往復の真の利益率
                            "buy_fee": 500 if "uniswap" in buy_dex else 3000, # 簡易的なFee付与
                            "sell_fee": 500 if "uniswap" in sell_dex else 3000,
                            "timestamp": time.time()
                        }
                        self.logger.info(
                            f"✅ [真の機会検知] {pair} | 利益率: {profit_ratio * 100:.3f}% "
                            f"({buy_dex} で買 ➔ {sell_dex} で売) | 投入: ${amount_in_usd:.2f} ➔ 最終: ${final_usdc:.2f}"
                        )
                        opportunities.append(opp)
                    else:
                        # 幻の利益だった場合は、裏でひっそりログを残す（デバッグ用）
                        if (buy_price - sell_price) / sell_price > self.threshold:
                            self.logger.debug(
                                f"👻 [幻の利益を粉砕] {pair} | {buy_dex}➔{sell_dex} | "
                                f"看板上は差があるが、往復すると赤字 (最終: ${final_usdc:.2f})"
                            )

        return opportunities