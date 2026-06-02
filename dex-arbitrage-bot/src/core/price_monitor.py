import asyncio
import random
from typing import Dict, List, Tuple
from datetime import datetime

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier


class PriceMonitor:
    """
    DEXから価格情報を監視するモジュール
    要件定義: 設定ファイルで監視間隔・対象ペアを管理
    """
    
    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier):
        self.config = config
        self.logger = logger
        self.telegram = telegram
        self.monitoring_interval = config['bot'].get('monitoring_interval', 2.0)
        self.pairs = config.get('pairs', ['WETH/USDC'])
        self.is_running = False
        
        self.logger.info("PriceMonitor initialized")
    
    async def get_prices(self) -> Dict[str, Dict[str, float]]:
        """
        各DEXの価格を取得（現在はモックデータ。将来的にWeb3 RPC接続に置き換え）
        """
        prices = {}
        
        for pair in self.pairs:
            # モック価格データ（実際はRPC + DEX Contractから取得）
            base_price = random.uniform(2400, 2600)  # ETH/USDC などの例
            
            prices[pair] = {
                "uniswap_v3": round(base_price * (1 + random.uniform(-0.003, 0.003)), 4),
                "sushiswap": round(base_price * (1 + random.uniform(-0.003, 0.003)), 4),
            }
        
        self.logger.debug(f"Current prices: {prices}")
        return prices
    
    async def start_monitoring(self):
        """価格監視ループを開始"""
        self.is_running = True
        self.logger.info("Price monitoring started")
        await self.telegram.send_message("🟢 PriceMonitor started")
        
        try:
            while self.is_running:
                start_time = datetime.now()
                
                prices = await self.get_prices()
                
                # 監視結果をログ
                self.logger.info(f"[{start_time.strftime('%H:%M:%S')}] Monitored {len(self.pairs)} pairs")
                
                # 次の監視まで待機
                await asyncio.sleep(self.monitoring_interval)
                
        except asyncio.CancelledError:
            self.logger.info("Price monitoring stopped")
        except Exception as e:
            self.logger.error(f"Monitoring error: {e}")
            await self.telegram.send_message(f"❌ PriceMonitor error: {e}")
    
    def stop(self):
        """監視を停止"""
        self.is_running = False
        self.logger.info("PriceMonitor stopped")