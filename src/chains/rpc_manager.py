from web3 import Web3
from ..utils.logger import BotLogger

class RPCManager:
    """
    RPC接続管理（デバッグ強化版）
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
        self._connect()

    def _connect(self) -> bool:
        try:
            rpc_config = self.config.get('rpc', {}).get(self.chain, {})
            rpc_url = rpc_config.get('url')

            if not rpc_url:
                self.logger.error(f"RPC URLがconfig.yamlに設定されていません: {self.chain}")
                return self._handle_failure("URL未設定")

            self.logger.info(f"RPC接続試行: {self.chain} → {rpc_url}")
            self.w3 = Web3(Web3.HTTPProvider(rpc_url))

            if self.w3.is_connected():
                self.logger.info(f"✅ RPC接続成功 | Block: {self.w3.eth.block_number}")
                self.consecutive_failures = 0
                return True
            else:
                return self._handle_failure("is_connected()がFalse")

        except Exception as e:
            return self._handle_failure(str(e))

    def _handle_failure(self, error_msg="不明"):
        self.consecutive_failures += 1
        self.logger.error(f"RPC接続失敗 ({self.consecutive_failures}/{self.max_consecutive_failures}): {error_msg}")

        if self.consecutive_failures >= self.max_consecutive_failures:
            self.logger.critical(f"🚨 RPC接続が{self.max_consecutive_failures}回連続失敗しました。Botを停止します。")
            if self.stop_callback:
                self.logger.info("stop_callbackを呼び出します...")
                self.stop_callback("RPC連続接続失敗")
            else:
                self.logger.error("stop_callbackが設定されていません！")

        return False

    def get_web3(self):
        if self.w3 is None or not self.w3.is_connected():
            self.logger.warning("RPC切断検知 → 再接続試行")
            self._connect()
        return self.w3