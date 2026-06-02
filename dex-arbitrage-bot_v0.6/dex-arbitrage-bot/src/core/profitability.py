import asyncio
from typing import Dict, Optional
from datetime import datetime

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
        
        self.min_profit_usd = config['trading'].get('min_profit_usd', 5.0)
        self.max_slippage = config['trading'].get('max_slippage', 0.8)
        self.max_gas_price_gwei = config['trading'].get('max_gas_price_gwei', 30)
        
        self.logger.info(f"ProfitabilityCalculator initialized (min_profit: ${self.min_profit_usd})")
    
    def estimate_gas_cost(self, chain: str = "arbitrum") -> float:
        """ガス代の見積もり（USD換算） - モック実装"""
        # 実際はガス価格API + トランザクションシミュレーションで計算
        if chain == "arbitrum":
            return 0.8  # 例: $0.8程度
        elif chain == "solana":
            return 0.01
        return 2.0  # Ethereumなど
    
    def calculate_expected_profit(self, opportunity: Dict) -> Dict:
        """
        期待利益を計算（ガス代 + スリッページ考慮）
        """
        try:
            price_diff_percent = opportunity['price_difference_percent']
            buy_price = opportunity['buy_price']
            sell_price = opportunity['sell_price']
            
            # 簡易的な取引額想定（$1000相当）
            trade_amount_usd = 1000.0
            
            # 粗利益
            gross_profit = trade_amount_usd * (price_diff_percent / 100)
            
            # スリッページによる損失見込み
            slippage_loss = trade_amount_usd * (self.max_slippage / 100)
            
            # ガス代
            gas_cost = self.estimate_gas_cost(self.config['bot'].get('chain', 'arbitrum'))
            
            # 最終期待利益
            expected_profit_usd = gross_profit - slippage_loss - gas_cost
            
            result = {
                'expected_profit_usd': round(expected_profit_usd, 4),
                'gross_profit': round(gross_profit, 4),
                'slippage_loss': round(slippage_loss, 4),
                'gas_cost': round(gas_cost, 4),
                'is_profitable': expected_profit_usd >= self.min_profit_usd,
                'timestamp': datetime.now().isoformat()
            }
            
            self.logger.debug(f"Profitability calculated: ${expected_profit_usd:.2f} (Profitable: {result['is_profitable']})")
            
            return result
            
        except Exception as e:
            self.logger.error(f"Profitability calculation error: {e}")
            return {
                'expected_profit_usd': 0.0,
                'is_profitable': False,
                'error': str(e)
            }
    
    async def is_executable(self, opportunity: Dict) -> bool:
        """実行可能かどうかを判定"""
        calc_result = self.calculate_expected_profit(opportunity)
        
        if calc_result.get('is_profitable', False):
            self.logger.info(f"✅ Profitable opportunity! Expected profit: ${calc_result['expected_profit_usd']:.2f}")
            await self.telegram.send_message(
                f"💰 **Profitable Opportunity!**\n"
                f"Expected Profit: ${calc_result['expected_profit_usd']:.2f}\n"
                f"Gas: ${calc_result['gas_cost']:.2f}"
            )
            return True
        else:
            self.logger.debug("Opportunity not profitable enough")
            return False