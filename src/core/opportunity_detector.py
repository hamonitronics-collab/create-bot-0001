import asyncio
from typing import Dict, List, Optional
from datetime import datetime

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier


class OpportunityDetector:
    """
    価格差を検知してアービトラージ機会を見つけるモジュール
    要件定義: price_difference_threshold を使用
    """

    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier):
        self.config = config
        self.logger = logger
        self.telegram = telegram

        trading_config = config.get('trading', {})
        self.price_difference_threshold = trading_config.get('price_difference_threshold', 0.5)
        self.logger.info(f"OpportunityDetector initialized (threshold: {self.price_difference_threshold}%)")

    def detect_opportunities(self, prices: Dict) -> List[Dict]:
        """
        価格情報からアービトラージ機会を検知
        prices: PriceMonitorから渡される価格データ
        """
        opportunities = []

        for pair, dex_prices in prices.items():
            if len(dex_prices) < 2:
                continue

            # 価格差を計算（全DEXペア比較）
            dex_list = list(dex_prices.items())
            for i in range(len(dex_list)):
                for j in range(i + 1, len(dex_list)):
                    dex1_name, price1 = dex_list[i]
                    dex2_name, price2 = dex_list[j]

                    if price1 == 0 or price2 == 0:
                        continue

                    diff_percent = abs(price1 - price2) / min(price1, price2) * 100

                    if diff_percent >= self.price_difference_threshold:
                        opportunity = {
                            "pair": pair,
                            "buy_dex": dex1_name if price1 < price2 else dex2_name,
                            "sell_dex": dex2_name if price1 < price2 else dex1_name,
                            "price_diff_percent": round(diff_percent, 4),
                            "timestamp": datetime.now().isoformat(),
                            "expected_profit_usd": None  # 後でProfitabilityCalculatorで計算
                        }
                        opportunities.append(opportunity)

                        self.logger.info(f"機会検知: {pair} | {diff_percent:.3f}% ({dex1_name} vs {dex2_name})")

        if opportunities:
            self.logger.warning(f"検知された機会: {len(opportunities)}件")
            # 将来的にTelegram通知

        return opportunities