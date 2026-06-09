from web3 import Web3

class BaseDEX:
    def __init__(self, w3: Web3, logger, config: dict = None):
        self.w3 = w3
        self.logger = logger
        self.config = config or {}
        self.optimal_fees = {} # 高速化用：Feeティア学習キャッシュ

    def get_price(self, pair: str, token_in: str, token_out: str, pair_config: dict) -> float:
        raise NotImplementedError