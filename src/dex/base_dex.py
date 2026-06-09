from web3 import Web3

class BaseDEX:
    """すべてのDEXアダプターが継承する親クラス"""

    def __init__(self, w3: Web3, logger, config: dict = None):
        self.w3 = w3
        self.logger = logger
        self.config = config or {}

        # 🚀 高速化: 一度成功したFeeティアをペアごとに記憶する学習キャッシュ
        self.optimal_fees = {}

    def get_price(self, pair: str, token_in_address: str, token_out_address: str, pair_config: dict) -> float:
        raise NotImplementedError