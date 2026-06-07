from web3 import Web3
from ..utils.logger import BotLogger

class RPCManager:
    """
    RPC接続を管理するモジュール
    URL変更時に確実に再接続するよう強化
    """

    def __init__(self, config: dict, logger: BotLogger, stop_callback=None):
        self.config = config
        self.logger = logger
        self.stop_callback = stop_callback
        self.w3 = None
        self.chain = config['bot'].get('chain', 'arbitrum-sepolia')

        rpc_settings = config.get('rpc_settings', {})
        self.max_consecutive_failures = rpc_settings.get('max_consecutive_failures', 5)

        self.consecutive_failures = 0
        self._connect(force=True)  # 強制接続

    def _connect(self, force: bool = False) -> bool:
        """RPCに接続"""
        try:
            rpc_config = self.config.get('rpc', {}).get(self.chain, {})
            rpc_url = rpc_config.get('url')

            if not rpc_url:
                self.logger.error(f"RPC URLがconfig.yamlに設定されていません: {self.chain}")
                return False

            self.logger.info(f"RPC接続試行: {self.chain} → {rpc_url}")

            # 新しいWeb3インスタンスを常に作成（キャッシュ対策）
            self.w3 = Web3(Web3.HTTPProvider(rpc_url))

            if 'arbitrum' in self.chain.lower():
                try:
                    from web3.middleware import geth_poa_middleware
                    self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
                except ImportError:
                    pass

            if self.w3.is_connected():
                block = self.w3.eth.block_number
                self.logger.info(f"✅ RPC接続成功: {self.chain} | Block: {block}")
                self.consecutive_failures = 0
                return True
            else:
                return self._handle_failure()

        except Exception as e:
            return self._handle_failure(e)

    def _handle_failure(self, error=None):
        # （前回と同じ内容）
        self.consecutive_failures += 1
        error_msg = str(error) if error else "接続失敗"
        self.logger.error(f"RPC接続失敗 ({self.consecutive_failures}/{self.max_consecutive_failures}): {error_msg}")

        if self.consecutive_failures >= self.max_consecutive_failures:
            self.logger.critical(f"🚨 RPC接続が{self.max_consecutive_failures}回連続失敗しました。Botを停止します。")
            if self.stop_callback:
                self.stop_callback("RPC連続接続失敗")

        return False

    def get_web3(self):
        if self.w3 is None or not self.w3.is_connected():
            self.logger.warning("RPC接続が切断されています。再接続を試みます...")
            self._connect()
        return self.w3