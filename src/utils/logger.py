import logging
import sys
from pathlib import Path
from datetime import datetime

class BotLogger:
    """
    Bot全体で使用するロガー
    config.yaml の logging 設定を尊重
    """

    def __init__(self, config: dict):
        self.config = config
        self.logger = self._setup_logger()

    def _setup_logger(self):
        """ロガーの初期化"""
        log_config = self.config.get('logging', {})
        level_name = log_config.get('level', 'INFO').upper()
        level = getattr(logging, level_name, logging.INFO)

        logger = logging.getLogger("ArbitrageBot")
        logger.setLevel(level)

        # 既存ハンドラーをクリア（重複防止）
        if logger.handlers:
            logger.handlers.clear()

        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)s | %(message)s',
            datefmt='%H:%M:%S'
        )

        # コンソール出力
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # ファイル出力
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        file_handler = logging.FileHandler(
            log_dir / f"bot_{datetime.now().strftime('%Y%m%d')}.log",
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        return logger

    def info(self, message: str):
        self.logger.info(message)

    def debug(self, message: str):
        self.logger.debug(message)

    def warning(self, message: str):
        self.logger.warning(message)

    def error(self, message: str):
        self.logger.error(message)

    def critical(self, message: str):
        self.logger.critical(message)