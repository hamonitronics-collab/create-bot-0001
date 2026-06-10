# src/dex/algebra_base.py
from web3 import Web3
from .base_dex import BaseDEX

class BaseAlgebraAdapter(BaseDEX):
    """
    Camelot V3 などの「Algebraエンジン」を採用したDEX用のアダプター。
    """
    def __init__(self, w3: Web3, logger, config: dict, dex_name: str):
        super().__init__(w3, logger, config)
        self.dex_name = dex_name
        self.quoter_address = None
        self.quoter_contract = None

        # 💡 修正：戻り値(outputs)を「amountOut」と「fee」の2つだけに設定！
        self.quoter_abi = [{
            "inputs": [
                {"internalType": "address", "name": "tokenIn", "type": "address"},
                {"internalType": "address", "name": "tokenOut", "type": "address"},
                {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                {"internalType": "uint160", "name": "limitSqrtPrice", "type": "uint160"}
            ],
            "name": "quoteExactInputSingle",
            "outputs": [
                {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
                {"internalType": "uint16", "name": "fee", "type": "uint16"} # 💡 これがさっきの「d (100)」の正体！
            ],
            "stateMutability": "nonpayable",
            "type": "function"
        }]

        quoter_address = config.get('dexes', {}).get(self.dex_name, {}).get('quoter_address')
        if not quoter_address:
            raise ValueError(f"❌ dexes.yaml に {self.dex_name} の quoter_address が設定されていません！")

        self._init_quoter(quoter_address)

    def _init_quoter(self, address: str):
        self.quoter_address = self.w3.to_checksum_address(address)
        self.quoter_contract = self.w3.eth.contract(address=self.quoter_address, abi=self.quoter_abi)

    def get_price(self, pair: str, token_in: str, token_out: str, params: dict) -> float:
        if not self.quoter_contract:
            return 0.0

        amount_in_wei = params.get("amount_in", 100 * 10**6)
        quote_decimals = params.get("quote_decimals", 6)
        base_decimals = params.get("base_decimals", 18)

        try:
            # 引数は4つ（タプルにしない）
            raw_result = self.quoter_contract.functions.quoteExactInputSingle(
                self.w3.to_checksum_address(token_in),
                self.w3.to_checksum_address(token_out),
                int(amount_in_wei),
                0  # limitSqrtPrice
            ).call()

            # 返ってきた2つのデータをしっかり受け取る！
            amount_out = raw_result[0]
            fee = raw_result[1]

        except Exception as e:
            error_msg = str(e)
            if "SPL" in error_msg or "execution reverted" in error_msg:
                self.logger.debug(f"⚠️ [{self.__class__.__name__}][{self.dex_name}] 流動性不足スルー [{pair}]")
            else:
                self.logger.error(f"🔥 [{self.__class__.__name__}][{self.dex_name}] 【要確認】見積もり異常 [{pair}]: {error_msg}")
            return 0.0

        if amount_out == 0:
            return None  # 💡 変更: None を返す

        real_amount_in = amount_in_wei / (10 ** quote_decimals)
        real_amount_out = amount_out / (10 ** base_decimals)
        effective_price = real_amount_in / real_amount_out

        base_sym, quote_sym = pair.split("/")
        base_addr = self.config['tokens'][base_sym]['address'].lower()
        display_sym = base_sym if token_out.lower() == base_addr else quote_sym

        self.logger.info(f"📊 [{self.__class__.__name__}][{self.dex_name}] 最適レート取得 [{pair} - 適用Fee:{fee}]: {effective_price:.6f} (獲得量: {real_amount_out:.4f} {display_sym})")

        # 💡 生データを含めた辞書を返す
        return {
            "price": float(effective_price),
            "amount_out_wei": int(amount_out),  # 次のDEXに渡すための生データ
            "real_amount_out": float(real_amount_out),
            "fee": fee
        }