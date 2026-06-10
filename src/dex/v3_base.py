# src/dex/v3_base.py
from web3 import Web3
from .base_dex import BaseDEX

class BaseV3Adapter(BaseDEX):
    """
    Uniswap V3 と同じ構造を持つすべてのDEX（Sushi, Pancake等）で
    使い回せる共通の「V3型アダプター」の親クラス
    """
    def __init__(self, w3: Web3, logger, config: dict):
        # 自動ロードが要求する3つの引数だけで初期化できるようにする
        super().__init__(w3, logger, config)

        # quoter_address は子クラスの init 内で self.quoter_address としてセットされた後に
        # コントラクト化するため、ここでは枠だけ用意するか、初期化を遅延させます。
        self.quoter_address = None
        self.quoter_contract = None

        # 全V3系DEXで共通の QuoterV2 ABI
        self.quoter_abi = [{
            "inputs": [{
                "components": [
                    {"internalType": "address", "name": "tokenIn", "type": "address"},
                    {"internalType": "address", "name": "tokenOut", "type": "address"},
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint24", "name": "fee", "type": "uint24"},
                    {"internalType": "uint160", "name": "sqrtPriceLimitX96", "type": "uint160"}
                ],
                "internalType": "struct IQuoterV2.QuoteExactInputSingleParams",
                "name": "params",
                "type": "tuple"
            }],
            "name": "quoteExactInputSingle",
            "outputs": [
                {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
                {"internalType": "uint160", "name": "sqrtPriceX96After", "type": "uint160"},
                {"internalType": "uint32", "name": "initializedTicksCrossed", "type": "uint32"},
                {"internalType": "uint256", "name": "gasEstimate", "type": "uint256"}
            ],
            "stateMutability": "nonpayable",
            "type": "function"
        }]

    def _init_quoter(self, address: str):
        """子クラスから住所を受け取って Quoter コントラクトを結ぶためのヘルパー"""
        self.quoter_address = self.w3.to_checksum_address(address)
        self.quoter_contract = self.w3.eth.contract(address=self.quoter_address, abi=self.quoter_abi)

    def get_price(self, pair: str, token_in: str, token_out: str, params: dict) -> float:
        # 万が一コントラクトが初期化されていない場合は安全に0を返す
        if not self.quoter_contract:
            return 0.0

        amount_in_wei = params.get("amount_in", 100 * 10**6)
        quote_decimals = params.get("quote_decimals", 6)
        base_decimals = params.get("base_decimals", 18)

        # 4つのFeeプールを総当たりでチェック
        fee_tiers = [100, 500, 3000, 10000]
        best_amount_out = 0
        best_fee = None

        for fee in fee_tiers:
            try:
                quote_params = (
                    self.w3.to_checksum_address(token_in),
                    self.w3.to_checksum_address(token_out),
                    int(amount_in_wei),
                    int(fee),
                    0
                )
                raw_result = self.quoter_contract.functions.quoteExactInputSingle(quote_params).call()
                amount_out = raw_result[0]

                if amount_out > best_amount_out:
                    best_amount_out = amount_out
                    best_fee = fee
            except Exception as e:
                error_msg = str(e)
                if "SPL" in error_msg or "execution reverted" in error_msg:
                    self.logger.debug(f"⚠️ [{self.__class__.__name__}] 流動性不足スルー [{pair} - Fee:{fee}]")
                else:
                    self.logger.error(f"🔥 [{self.__class__.__name__}] 【要確認】見積もり異常 [{pair} - Fee:{fee}]: {error_msg}")
                continue

        if best_amount_out == 0:
            self.logger.debug(f"⚠️ [{self.__class__.__name__}] 有効なプールなし [{pair}]")
            return 0.0

        real_amount_in = amount_in_wei / (10 ** quote_decimals)
        real_amount_out = amount_out_val = real_amount_out = amount_out_val = best_amount_out / (10 ** base_decimals)
        effective_price = real_amount_in / real_amount_out

        base_sym, quote_sym = pair.split("/")
        base_addr = self.config['tokens'][base_sym]['address'].lower()
        display_sym = base_sym if token_out.lower() == base_addr else quote_sym

        self.logger.info(f"📊 [{self.__class__.__name__}] 最適レート取得 [{pair} - Fee:{best_fee}]: {effective_price:.6f} (獲得量: {real_amount_out:.4f} {display_sym})")
        return float(effective_price)