from web3 import Web3
from web3.middleware import geth_poa_middleware
from ..utils.logger import BotLogger

class RPCManager:
    """
    RPC接続を管理するモジュール
    将来的に複数チェーン・複数プロバイダー対応
    """

    def __init__(self, config: dict, logger: BotLogger):
        self.config = config
        self.logger = logger
        self.w3 = None
        self.chain = config['bot'].get('chain', 'arbitrum-sepolia')
        self._connect()

    def _connect(self):
        """RPCに接続"""
        try:
            rpc_config = self.config.get('rpc', {}).get(self.chain, {})
            rpc_url = rpc_config.get('url')

            if not rpc_url:
                self.logger.error(f"RPC URLが設定されていません: {self.chain}")
                return False

            self.w3 = Web3(Web3.HTTPProvider(rpc_url))

            # Arbitrum系はPOAミドルウェアが必要
            if 'arbitrum' in self.chain:
                self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)

            if self.w3.is_connected():
                self.logger.info(f"✅ RPC接続成功: {self.chain} | Latest Block: {self.w3.eth.block_number}")
                return True
            else:
                self.logger.error("RPC接続失敗")
                return False

        except Exception as e:
            self.logger.error(f"RPC接続エラー: {e}")
            return False

    def get_web3(self):
        return self.w3