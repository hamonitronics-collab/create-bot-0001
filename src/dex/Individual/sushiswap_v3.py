from ..base_dex import BaseDEX

class SushiswapV3Adapter(BaseDEX):
    """SushiSwap V3用アダプター (完全汎用化 ＆ Fee学習高速化版)"""

    def get_price(self, pair: str, token_in_address: str, token_out_address: str, pair_config: dict) -> float:
        try:
            self.ensure_w3()
            # 1. configからQuoterアドレスを動的取得
            dex_config = self.config.get('dexes', {}).get('sushiswap', {})
            quoter_address_raw = dex_config.get('quoter_address')
            if not quoter_address_raw:
                return None

            quoter = self.w3.eth.contract(
                address=self.w3.to_checksum_address(quoter_address_raw),
                abi=self._get_v3_quoter_v2_abi()
            )

            # 2. configからトークンの桁数と「見積もり用数量」を動的取得
            base_symbol = pair.split('/')[0]
            token_info = self.config.get('tokens', {}).get(base_symbol, {})
            decimals = token_info.get('decimals', 18)
            quote_amount = token_info.get('quote_amount', 1.0)

            amount_in = int(quote_amount * (10 ** decimals))
            multiplier = 1.0 / quote_amount

            # 3. 🚀 高速化: 前回成功したFeeティアを一番最初に試す
            best_fee = self.optimal_fees.get(pair)
            fees_to_try = [best_fee] if best_fee else []
            for f in [500, 3000, 10000]:
                if f not in fees_to_try:
                    fees_to_try.append(f)

            for fee in fees_to_try:
                try:
                    # SushiSwap特有の引数順序
                    params = (token_in_address, token_out_address, amount_in, fee, 0)
                    outputs = quoter.functions.quoteExactInputSingle(params).call()
                    amount_out = outputs[0]

                    price = float(self.w3.from_wei(amount_out, 'mwei')) * multiplier

                    if best_fee != fee:
                        self.optimal_fees[pair] = fee

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