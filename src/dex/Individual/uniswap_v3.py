from ..base_dex import BaseDEX

class UniswapV3Adapter(BaseDEX):
    """Uniswap V3用アダプター (完全汎用化 ＆ Fee学習高速化版)"""

    def get_price(self, pair: str, token_in_address: str, token_out_address: str, pair_config: dict) -> float:
        try:
            self.ensure_w3()

            # 💡 修正ポイント：自分のファイル名（モジュール名）から動的にキーを取得！
            # ファイル名が "uniswap_v3.py" なら、ここが自動で "uniswap_v3" になります。
            dex_key = self.__module__.split('.')[-1]

            # 動的キーを使ってconfigからこのDEXの設定を取得
            dex_config = self.config.get('dexes', {}).get(dex_key, {})
            quoter_address_raw = dex_config.get('quoter_address')
            if not quoter_address_raw:
                return None

            quoter = self.w3.eth.contract(
                address=self.w3.to_checksum_address(quoter_address_raw),
                abi=self._get_quoter_abi()
            )

            # 2. configからトークンの桁数と「見積もり用数量」を動的取得
            base_symbol = pair.split('/')[0]
            token_info = self.config.get('tokens', {}).get(base_symbol, {})
            decimals = token_info.get('decimals', 18)
            quote_amount = token_info.get('quote_amount', 1.0)

            amount_in = int(quote_amount * (10 ** decimals))
            multiplier = 1.0 / quote_amount

            # 3. 🚀 高速化: 前回成功したFeeティアを一番最初に試すように並び替え
            best_fee = self.optimal_fees.get(pair)
            fees_to_try = [best_fee] if best_fee else []
            for f in [500, 3000, 10000]:
                if f not in fees_to_try:
                    fees_to_try.append(f)

            for fee in fees_to_try:
                try:
                    amount_out = quoter.functions.quoteExactInputSingle(
                        token_in_address, token_out_address, fee, amount_in, 0
                    ).call()

                    price = float(self.w3.from_wei(amount_out, 'mwei')) * multiplier

                    # 成功したFeeを記憶 (次回から無駄なエラー通信がゼロになる)
                    if best_fee != fee:
                        self.optimal_fees[pair] = fee

                    # 💡 ログの出力名も動的な dex_key を使って綺麗に整形（例: Uniswap V3）
                    log_name = dex_key.replace('_', ' ').title()
                    self.logger.info(f"{log_name} ({fee/10000}%) [{pair}] 価格取得成功: {price:.4f}")
                    return round(price, 4)
                except:
                    continue

            raise Exception("すべてのfee tierで失敗")
        except Exception as e:
            # 💡 エラーログの名前も動的に追従させます
            log_name = dex_key.replace('_', ' ').title() if 'dex_key' in locals() else "Uniswap V3"
            self.logger.error(f"{log_name}価格取得エラー ({pair}): {e}")
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