from web3 import Web3

class BaseDEX:
    def __init__(self, w3: Web3, logger, config: dict = None):
        self.w3 = w3
        self.logger = logger
        self.config = config or {}
        self.optimal_fees = {} # 高速化用：Feeティア学習キャッシュ

    def get_price(self, pair: str, token_in: str, token_out: str, pair_config: dict) -> float:
        raise NotImplementedError

    def ensure_w3(self):
        """Web3がNoneの場合に再接続を試みるヘルパー"""
        if self.w3 is None:
            # PriceMonitorから渡されたconfigを使って再生成を試みる
            chain = self.config['bot']['chain']
            rpc_url = self.config['rpc'][chain]['url']
            self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 5}))