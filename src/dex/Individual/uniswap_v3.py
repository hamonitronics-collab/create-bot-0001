# src/dex/uniswap_v3.py
from ..base_dex import BaseDEX

class UniswapV3Adapter(BaseDEX):
    """Uniswap V3用のアダプター"""

    def get_price(self, pair: str, token_in_address: str, token_out_address: str, pair_config: dict) -> float:
        try:
            # 必須アドレスの取得（Uniswapは共通の旧USDC等を使用する想定）
            quoter_address = self.w3.to_checksum_address("0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6")
            quoter = self.w3.eth.contract(address=quoter_address, abi=self._get_quoter_abi())

            # トークンDecimalsの決定
            if "WBTC" in pair:
                amount_in = int(1 * 10**8)  # 1 WBTC
            else:
                amount_in = self.w3.to_wei(1, 'ether')  # 1 WETH

            fees = [500, 3000, 10000]
            for fee in fees:
                try:
                    amount_out = quoter.functions.quoteExactInputSingle(
                        token_in_address, token_out_address, fee, amount_in, 0
                    ).call()

                    price = self.w3.from_wei(amount_out, 'mwei')
                    self.logger.info(f"Uniswap V3 ({fee/10000}%) [{pair}] 価格取得成功: {price:.4f}")
                    return round(float(price), 4)
                except:
                    continue
            raise Exception("すべてのfee tierで失敗")
        except Exception as e:
            self.logger.error(f"Uniswap V3価格取得エラー ({pair}): {e}")
            return None

    def _get_quoter_abi(self):
        return [{
            "inputs": [
                {"name": "tokenIn", "type": "address"},
                {"name": "tokenOut", "type": "address"},
                {"name": "fee", "type": "uint24"},
                {"name": "amountIn", "type": "uint256"},
                {"name": "sqrtPriceLimitX96", "type": "uint160"}
            ],
            "name": "quoteExactInputSingle",
            "outputs": [{"name": "amountOut", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function"
        }]