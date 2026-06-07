from web3 import Web3
from ..utils.logger import BotLogger

class RPCManager:
    """
    RPC接続を管理するモジュール
    web3.pyバージョン違いに頑健に対応
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
                self.logger.error(f"RPC URLがconfig.yamlに設定されていません: {self.chain}")
                return False

            self.logger.info(f"RPC接続試行: {self.chain} → {rpc_url}")

            self.w3 = Web3(Web3.HTTPProvider(rpc_url))

            # Arbitrum系POAミドルウェア（安全に処理）
            if 'arbitrum' in self.chain.lower():
                try:
                    from web3.middleware import geth_poa_middleware
                    self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
                except ImportError:
                    self.logger.debug("POAミドルウェアはスキップ（必要ない場合あり）")

            if self.w3.is_connected():
                block = self.w3.eth.block_number
                self.logger.info(f"✅ RPC接続成功: {self.chain} | Latest Block: {block}")
                return True
            else:
                self.logger.error("RPC接続失敗")
                return False

        except Exception as e:
            self.logger.error(f"RPC接続エラー: {e}")
            return False

    def get_web3(self):
        if self.w3 is None or not self.w3.is_connected():
            self.logger.warning("RPC未接続。再接続します")
            self._connect()
        return self.w3