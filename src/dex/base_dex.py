# src/dex/base_dex.py
from abc import ABC, abstractmethod
from web3 import Web3

class BaseDEX(ABC):
    """
    すべてのDEXアダプターが継承するベースクラス。
    一括管理・拡張を容易にするための共通インターフェースを定義。
    """
    def __init__(self, w3: Web3, logger):
        self.w3 = w3
        self.logger = logger

    @abstractmethod
    def get_price(self, pair: str, token_in_address: str, token_out_address: str, pair_config: dict) -> float:
        """
        指定されたペアの価格を取得して返すメソッド。
        すべてのDEXアダプターで必ずこの名前・引数で実装する。
        失敗した場合は None を返す。
        """
        pass