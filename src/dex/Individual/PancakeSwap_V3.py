# src/dex/Individual/PancakeSwap_V3.py
from ..base_dex import BaseDEX

class PancakeSwapAdapter(BaseDEX):
    """PancakeSwap V3用のアダプター（引数統一・二段構えUSDC対応版）"""

    def get_price(self, pair: str, token_in_address: str, token_out_address: str, pair_config: dict) -> float:
        try:
            # 💡 柔軟性を持たせるため、外から渡された token_out_address と、もう一方のUSDCも候補に入れる
            # （config.yaml や price_monitor で定義されたもうひとつのUSDCのアドレス）
            # ここでは安全のため、渡されたアドレスを最優先し、もう片方もバックアップとして保持します。
            native_usdc = self.w3.to_checksum_address("0xaf88d065e77c8cC2239327C5EDb3A432268e5831")
            legacy_usdc = self.w3.to_checksum_address("0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8")

            # 渡されたものを先頭にし、両方のUSDCを探索できるように配列化
            tokens_out = [token_out_address]
            backup_usdc = legacy_usdc if token_out_address == native_usdc else native_usdc
            tokens_out.append(backup_usdc)

            quoter_address = self.w3.to_checksum_address("0xB048Bbc1E2Dc36a37e96fA3423A7a196fc9444B2")
            quoter = self.w3.eth.contract(address=quoter_address, abi=self._get_v3_quoter_v2_abi())

            # 金額（Decimals）の決定
            if "WBTC" in pair:
                amount_in = int(1 * 10**8) # 1 WBTC (decimals=8)
            else:
                amount_in = self.w3.to_wei(1, 'ether') # 1 WETH (decimals=18)

            fees = [100, 500, 2500, 10000]

            for t_out in tokens_out:
                for fee in fees:
                    try:
                        # 構造体引数の順序を正確にセット
                        params = (
                            token_in_address,
                            t_out,
                            int(amount_in),
                            int(fee),
                            0
                        )

                        outputs = quoter.functions.quoteExactInputSingle(params).call()

                        if isinstance(outputs, (list, tuple)):
                            amount_out = outputs[0]
                        else:
                            amount_out = outputs

                        price = self.w3.from_wei(amount_out, 'mwei')

                        usdc_type = "Native" if t_out == native_usdc else "USDC.e"
                        self.logger.info(f"PancakeSwap V3 ({fee/10000}%) [{pair}] 価格取得成功 ({usdc_type}): {price:.4f}")
                        return round(float(price), 4)

                    except:
                        continue

            raise Exception(f"PancakeSwap全fee tier・全USDC失敗、または流動性がありません")
        except Exception as e:
            self.logger.error(f"PancakeSwap価格取得エラー ({pair}): {e}")
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