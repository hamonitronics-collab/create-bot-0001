# src/dex/Individual/uniswap_v3.py
import json
from web3 import Web3
from ..base_dex import BaseDEX

class UniswapV3Adapter(BaseDEX):
    def __init__(self, w3: Web3, logger, config: dict):
        super().__init__(w3, logger, config)
        # 💡 ここを本物の Uniswap V3 QuoterV2 (Arbitrum) のアドレスに修正！
        self.quoter_address = self.w3.to_checksum_address("0x61fFE014bA17989E743c5F6cB21bF9697530B21e")

        self.quoter_abi = [
            {
                "inputs": [
                    {
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
                    }
                ],
                "name": "quoteExactInputSingle",
                "outputs": [
                    {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
                    {"internalType": "uint160", "name": "sqrtPriceX96After", "type": "uint160"},
                    {"internalType": "uint32", "name": "initializedTicksCrossed", "type": "uint32"},
                    {"internalType": "uint256", "name": "gasEstimate", "type": "uint256"}
                ],
                "stateMutability": "nonpayable",
                "type": "function"
            }
        ]
        self.quoter_contract = self.w3.eth.contract(address=self.quoter_address, abi=self.quoter_abi)

    def get_price(self, pair: str, token_in: str, token_out: str, params: dict) -> float:
        try:
            amount_in_wei = params.get("amount_in", 100 * 10**6)
            fee = params.get("fee", 500) # Uniswapは0.05%
            quote_decimals = params.get("quote_decimals", 6)
            base_decimals = params.get("base_decimals", 18)

            quote_params = (
                self.w3.to_checksum_address(token_in),
                self.w3.to_checksum_address(token_out),
                int(amount_in_wei),
                int(fee),
                0  # sqrtPriceLimitX96
            )

            raw_result = self.quoter_contract.functions.quoteExactInputSingle(quote_params).call()
            amount_out = raw_result[0]

            if amount_out == 0: return 0.0

            real_amount_in = amount_in_wei / (10 ** quote_decimals)
            real_amount_out = amount_out / (10 ** base_decimals)
            effective_price = real_amount_in / real_amount_out

            base_sym, quote_sym = pair.split("/")
            base_addr = self.config['tokens'][base_sym]['address'].lower()
            display_sym = base_sym if token_out.lower() == base_addr else quote_sym

            self.logger.info(f"📊 [{self.__class__.__name__}] 実効価格取得 [{pair} - Fee:{fee}]: {effective_price:.6f} (獲得量: {real_amount_out:.4f} {display_sym})")
            return float(effective_price)
        except Exception as e:
            error_msg = str(e)
            # DEX起因の正常なエラー（流動性なし・プール未作成）かどうかを判定
            if "SPL" in error_msg or "execution reverted" in error_msg:
                # 正常な動作なので debug で静かに隠す（画面には出さない）
                self.logger.debug(f"⚠️ [{self.__class__.__name__}] プールなし/流動性不足 [{pair} - Fee:{fee}]")
                return 0.0
            else:
                # 🔥 俺起因の可能性大！（アドレス間違い、RPCエラーなど）なので赤色で警告！
                self.logger.error(f"🔥 [{self.__class__.__name__}] 【要確認】異常な見積もり失敗 [{pair} - Fee:{fee}]: {error_msg}")
                return 0.0