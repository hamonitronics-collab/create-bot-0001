# src/dex/Individual/uniswap_v3.py
from web3 import Web3
from ..v3_base import BaseV3Adapter

class UniswapV3Adapter(BaseV3Adapter):
    """Uniswap V3用のアダプター (BaseV3Adapterを継承)"""
    def __init__(self, w3: Web3, logger, config: dict):
        # 1. まず自動ロード規格の3引数で親クラスを初期化
        super().__init__(w3, logger, config)

        # 2. dexes.yaml から動的にアドレスを取得
        quoter_address = config.get('dexes', {}).get('uniswap_v3', {}).get('quoter_address')
        if not quoter_address:
            raise ValueError("❌ dexes.yaml に uniswap_v3 の quoter_address が設定されていません！")

        # 3. 親クラスの初期化関数にアドレスを流し込む
        self._init_quoter(quoter_address)