from typing import Dict, Optional

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier


class ProfitabilityCalculator:
    """
    アービトラージ機会の収益性を計算するモジュール
    要件定義: ガス代・スリッページ・最低利益を考慮
    """

    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier):
        self.config = config
        self.logger = logger
        self.telegram = telegram

        trading = config.get('trading', {})
        self.min_profit_usd = trading.get('min_profit_usd', 5.0)
        self.max_slippage = trading.get('max_slippage', 0.5)

        self.logger.info(f"ProfitabilityCalculator initialized (min_profit: ${self.min_profit_usd})")

    def calculate_profitability(self, opportunity: Dict) -> Optional[Dict]:
        """
        機会の収益性を計算し、実行可否を判断
        """
        try:
            price_diff = opportunity.get('price_diff_percent', 0.0)

            # 簡易収益計算（実際はガス代見積もりや流動性を精密に計算する）
            estimated_profit = price_diff * 20   # 仮の係数（後で調整）

            # スリッページ考慮
            after_slippage = estimated_profit * (1 - self.max_slippage / 100)

            is_profitable = after_slippage >= self.min_profit_usd

            result = {
                **opportunity,
                "estimated_profit_usd": round(after_slippage, 2),
                "is_profitable": is_profitable,
                "reason": "実行可能" if is_profitable else f"最低利益未達 (${after_slippage:.2f})"
            }

            if is_profitable:
                self.logger.warning(f"✅ 収益性OK: ${after_slippage:.2f} | {opportunity.get('pair')}")
            else:
                self.logger.debug(f"利益不足: ${after_slippage:.2f}")

            return result

        except Exception as e:
            self.logger.error(f"収益性計算エラー: {e}")
            return None