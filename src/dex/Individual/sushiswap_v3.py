from ..base_dex import BaseDEX

class SushiSwapV3Adapter(BaseDEX):
    """SushiSwap V3用のアダプター (構造体引数版・価格インパクト対応)"""

    def get_price(self, pair: str, token_in_address: str, token_out_address: str, pair_config: dict) -> float:
        try:
            quoter_address = self.w3.to_checksum_address("0x0524e833ccd057e4d7a296e3aaab9f7675964ce1")
            quoter = self.w3.eth.contract(address=quoter_address, abi=self._get_v3_quoter_v2_abi())

            # 💡 修正ポイント: 流動性が薄いDEXでの「価格インパクト」による暴落を防ぐため、
            # 1フル単位ではなく少額で見積もりを出し、後から掛け算して1単位の価格に戻す
            if "WBTC" in pair:
                # 0.001 WBTC (約40ドル相当) で問い合わせ
                amount_in = int(0.001 * 10**8)
                multiplier = 1000
            else:
                # 0.01 WETH (約16ドル相当) で問い合わせ
                amount_in = self.w3.to_wei(0.01, 'ether')
                multiplier = 100

            fees = [500, 3000, 10000]

            for fee in fees:
                try:
                    params = (token_in_address, token_out_address, amount_in, fee, 0)
                    outputs = quoter.functions.quoteExactInputSingle(params).call()
                    amount_out = outputs[0]

                    # 少額の取得結果(USDC)を乗数で拡大して、1フル単位の価格にする
                    base_price = float(self.w3.from_wei(amount_out, 'mwei'))
                    price = base_price * multiplier

                    self.logger.info(f"SushiSwap V3 ({fee/10000}%) [{pair}] 価格取得成功: {price:.4f}")
                    return round(price, 4)
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