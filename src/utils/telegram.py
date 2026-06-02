import asyncio
import aiohttp
from typing import Optional

class TelegramNotifier:
    """
    Telegram通知を送信するモジュール
    config.yaml で有効/無効を切り替え可能
    """
    
    def __init__(self, config: dict, logger):
        self.config = config
        self.logger = logger
        self.telegram_config = config.get('telegram', {})
        self.enabled = self.telegram_config.get('enabled', False)
        self.token = self.telegram_config.get('token', '')
        self.chat_id = self.telegram_config.get('chat_id', '')
        
        if self.enabled and self.token and self.chat_id:
            self.logger.info("TelegramNotifier enabled")
        elif self.enabled:
            self.logger.warning("Telegram enabled but token or chat_id is missing")
    
    async def send_message(self, message: str):
        """Telegramにメッセージを送信"""
        if not self.enabled or not self.token or not self.chat_id:
            self.logger.debug("Telegram notification skipped (not configured)")
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as response:
                    if response.status == 200:
                        self.logger.debug("Telegram message sent")
                        return True
                    else:
                        self.logger.warning(f"Telegram API error: {response.status}")
                        return False
                        
        except Exception as e:
            self.logger.error(f"Failed to send Telegram message: {e}")
            return False