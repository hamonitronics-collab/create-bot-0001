# src/dex/sushiswap_v3.py
from ..base_dex import BaseDEX

class SushiSwapV3Adapter(BaseDEX):
    """SushiSwap V3用のアダプター (構造体引数版)"""

    def get_price(self, pair: str, token_in_address: str, token_out_address: str, pair_config: dict) -> float:
        try:
            quoter_address = self.w3.to_checksum_address("0x0524e833ccd057e4d7a296e3aaab9f7675964ce1")
            quoter = self.w3.eth.contract(address=quoter_address, abi=self._get_v3_quoter_v2_abi())

            if "WBTC" in pair:
                amount_in = int(1 * 10**8)
            else:
                amount_in = self.w3.to_wei(1, 'ether')

            fees = [500, 3000, 10000]

            for fee in fees:
                try:
                    # SushiSwap特有の構造体 (amountIn が3番目、fee が4番目)
                    params = (token_in_address, token_out_address, amount_in, fee, 0)
                    outputs = quoter.functions.quoteExactInputSingle(params).call()
                    amount_out = outputs[0]

                    price = self.w3.from_wei(amount_out, 'mwei')
                    self.logger.info(f"SushiSwap V3 ({fee/10000}%) [{pair}] 価格取得成功: {price:.4f}")
                    return round(float(price), 4)
                except:
                    continue

            raise Exception("全fee tierで流動性がありません")
        except Exception as e:
            self.logger.error(f"SushiSwap価格取得エラー ({pair}): {e}")
            return None

    def _get_v3_quoter_v2_abi(self):
        return [{
            "inputs": [{
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "sqrtPriceLimitX96", "type": "uint160"}
                ],
                "name": "params",
                "type": "tuple"
            }],
            "name": "quoteExactInputSingle",
            "outputs": [
                {"name": "amountOut", "type": "uint256"},
                {"name": "sqrtPriceX96After", "type": "uint160"},
                {"name": "initializedTicksCrossed", "type": "uint32"},
                {"name": "gasEstimate", "type": "uint256"}
            ],
            "stateMutability": "view",
            "type": "function"
        }]