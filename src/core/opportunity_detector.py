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

    def detect_opportunities(self, prices: Dict[str, Dict[str, float]]) -> List[Dict]:
        """
        各ペアごとに、すべてのDEXの価格を総当たりで比較し、閾値以上の価格差を検知する
        """
        opportunities = []

        for pair, dex_data in prices.items():
            # 2つ以上のDEXで価格が取れていないなら比較できないのでスキップ
            if len(dex_data) < 2:
                continue

            dex_names = list(dex_data.keys())

            # 総当たり比較 (DEX A と DEX B)
            for i in range(len(dex_names)):
                for j in range(len(dex_names)):
                    if i == j:
                        continue

                    buy_dex = dex_names[i]
                    sell_dex = dex_names[j]

                    buy_price = dex_data[buy_index_price := buy_dex]
                    sell_price = dex_data[sell_index_price := sell_dex]

                    # 100%安全弁
                    if buy_price <= 0 or sell_price <= 0:
                        continue

                    # 価格差（％）の計算
                    # buy_dex で買って、sell_dex で売る。 sellの方が高ければ利益
                    if sell_price > buy_price:
                        price_diff_percent = ((sell_price - buy_price) / buy_price) * 100

                        # 設定された閾値（0.3%など）を超えているか
                        if price_diff_percent >= self.threshold:
                            self.logger.info(
                                f"機会検知: {pair} | {price_diff_percent:.3f}% "
                                f"({buy_dex}: {buy_price:.4f} ➔ {sell_dex}: {sell_price:.4f})"
                            )

                            # 💡 修正ポイント：利益計算モジュールがハードコードなしで100%動くように、
                            # 検知に使ったリアルタイムの生価格を辞書に完全にパッキングしてバトンを渡す
                            opp = {
                                "pair": pair,
                                "buy_dex": buy_dex,
                                "sell_dex": sell_dex,
                                "buy_price": float(buy_price),   # 👈 確実に渡す
                                "sell_price": float(sell_price), # 👈 確実に渡す
                                "price_diff_percent": round(price_diff_percent, 4)
                            }
                            opportunities.append(opp)

        if opportunities:
            self.logger.warning(f"検知された機会: {len(opportunities)}件")
        return opportunities