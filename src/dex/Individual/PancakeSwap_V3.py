# src/dex/sushiswap_v3.py
from ..base_dex import BaseDEX

class PancakeSwapV3Adapter(BaseDEX):
    """PancakeSwap V3用のアダプター (構造体引数版)"""

    def get_price(self, pair: str, token_in_address: str, token_out_address: str, pair_config: dict) -> float:
        try:
            token_in = self.weth
            # ⚠️ 対策1: ArbitrumのPancakeSwapは旧USDC(USDC.e)に流動性がある場合が多いため、配列にして両方試す
            tokens_out = [self.native_usdc, self.usdc]

            if "WBTC" in pair:
                if hasattr(self, 'wbtc'):
                    token_in = self.wbtc
                else:
                    token_in = self.w3.to_checksum_address("0x2f2a2543B76A4166549F7aaB2e75Bef0aefc5B0f")

            quoter_address = self.w3.to_checksum_address("0xB048Bbc1E2Dc36a37e96fA3423A7a196fc9444B2")
            # ⚠️ 対策2: 正規の構造体ABI（SushiSwapと同じ、amountInが先のもの）に戻す
            quoter = self.w3.eth.contract(address=quoter_address, abi=self._get_v3_quoter_v2_abi())

            if "WBTC" in pair:
                amount_in = int(1 * 10**8)
            else:
                amount_in = self.w3.to_wei(1, 'ether')

            fees = [100, 500, 2500, 10000]

            # 新USDC → 旧USDC.e の順番で流動性プールを探索する
            for token_out in tokens_out:
                for fee in fees:
                    try:
                        # ⚠️ 対策3: 正常な順序 (amountIn が3番目、fee が4番目) に修正
                        params = (
                            token_in,
                            token_out,
                            int(amount_in),   # 3番目: amountIn
                            int(fee),         # 4番目: fee
                            0                 # 5番目: sqrtPriceLimitX96
                        )

                        outputs = quoter.functions.quoteExactInputSingle(params).call()

                        if isinstance(outputs, (list, tuple)):
                            amount_out = outputs[0]
                        else:
                            amount_out = outputs

                        price_raw = self.w3.from_wei(amount_out, 'mwei')
                        price = float(price_raw)

                        # どちらのUSDCで取得できたかログに出力する
                        usdc_type = "Native" if token_out == self.native_usdc else "USDC.e"
                        self.logger.info(f"PancakeSwap V3 ({fee/10000}%) [{pair}] 価格取得成功 ({usdc_type}): {price:.4f}")
                        return round(price, 4)

                    except Exception as inner_e:
                        continue

            raise Exception(f"PancakeSwap全fee tier・全USDC失敗、または流動性がありません ({pair})")
        except Exception as e:
            self.logger.error(f"PancakeSwap価格取得エラー: {e}")
            return None