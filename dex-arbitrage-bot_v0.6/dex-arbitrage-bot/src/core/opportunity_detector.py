import asyncio
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier


class OpportunityDetector:
    """
    DEX間の価格差を監視し、アービトラージ機会を検知するモジュール
    要件定義: price_difference_threshold を使用
    """
    
    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier):
        self.config = config
        self.logger = logger
        self.telegram = telegram
        
        self.price_difference_threshold = config['trading'].get('price_difference_threshold', 0.5)
        self.pairs = config.get('pairs', ['WETH/USDC'])
        
        self.logger.info(f"OpportunityDetector initialized (threshold: {self.price_difference_threshold}%)")
    
    def calculate_price_difference(self, price1: float, price2: float) -> float:
        """2つの価格の差をパーセントで計算"""
        if price1 == 0 or price2 == 0:
            return 0.0
        return abs((price2 - price1) / price1) * 100
    
    def detect_opportunities(self, prices: Dict[str, Dict[str, float]]) -> List[Dict]:
        """
        価格データからアービトラージ機会を検知
        """
        opportunities = []
        
        for pair in self.pairs:
            if pair not in prices:
                continue
                
            dex_prices = prices[pair]
            dex_list = list(dex_prices.keys())
            
            # すべてのDEXペアを比較
            for i in range(len(dex_list)):
                for j in range(i + 1, len(dex_list)):
                    dex_a = dex_list[i]
                    dex_b = dex_list[j]
                    
                    price_a = dex_prices[dex_a]
                    price_b = dex_prices[dex_b]
                    
                    diff_percent = self.calculate_price_difference(price_a, price_b)
                    
                    if diff_percent >= self.price_difference_threshold:
                        # 機会を記録（安い方で買って高い方で売る）
                        if price_a < price_b:
                            buy_dex, sell_dex = dex_a, dex_b
                            buy_price, sell_price = price_a, price_b
                        else:
                            buy_dex, sell_dex = dex_b, dex_a
                            buy_price, sell_price = price_b, price_a
                        
                        opportunity = {
                            'pair': pair,
                            'buy_dex': buy_dex,
                            'sell_dex': sell_dex,
                            'buy_price': buy_price,
                            'sell_price': sell_price,
                            'price_difference_percent': round(diff_percent, 4),
                            'timestamp': datetime.now().isoformat()
                        }
                        
                        opportunities.append(opportunity)
                        
                        self.logger.info(f"Opportunity detected! {pair} {buy_dex} → {sell_dex} ({diff_percent:.3f}%)")
                        asyncio.create_task(self.telegram.send_message(
                            f"🔍 **Opportunity Detected!**\n"
                            f"Pair: {pair}\n"
                            f"Buy @ {buy_dex} ({buy_price}) → Sell @ {sell_dex} ({sell_price})\n"
                            f"Diff: {diff_percent:.3f}%"
                        ))
        
        return opportunities