import asyncio
import random
from typing import Dict, Callable
from datetime import datetime
from web3 import Web3

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier
from .opportunity_detector import OpportunityDetector
from .profitability import ProfitabilityCalculator
from .executor import Executor


class PriceMonitor:
    """
    DEXから価格情報を監視するモジュール
    Mainnet本物価格取得版（PancakeSwapエラー修正対応）
    """

    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier, stop_callback: Callable = None):
        self.config = config
        self.logger = logger
        self.telegram = telegram
        self.stop_callback = stop_callback
        self.monitoring_interval = config['bot'].get('monitoring_interval', 2.0)
        self.pairs = config.get('pairs', ['WETH/USDC'])
        self.is_running = False

        # RPC接続（Mainnet）
        self.w3 = None
        self._connect_rpc()

        # 各モジュール初期化
        self.detector = OpportunityDetector(config, logger, telegram)
        self.profitability = ProfitabilityCalculator(config, logger, telegram)
        self.executor = Executor(config, logger, telegram)

        # トークンアドレス（Mainnet）
        self.weth = self.w3.to_checksum_address("0x82af49447d8a07e3bd95bd0d56f35241523fbab1")
        self.wbtc = self.w3.to_checksum_address("0x2f2a2543B76A4166549F7aaB2e75Bef0aefc5B0f") # 👈 これを追加
        self.usdc = self.w3.to_checksum_address("0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8")

        # Pancake/Sushi用の新USDC (Native USDC)
        self.native_usdc = self.w3.to_checksum_address("0xaf88d065e77c8cC2239327C5EDb3A432268e5831")

        self.logger.info("PriceMonitor initialized (Mainnet本物価格取得・Pancake対応版)")

    def _connect_rpc(self):
        """Mainnet RPC接続"""
        try:
            rpc_url = "https://invictus.ambire.com/arbitrum"  # Mainnet
            self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 10}))
            if self.w3.is_connected():
                self.logger.info(f"✅ PriceMonitor RPC接続成功 (Mainnet) | Chain ID: {self.w3.eth.chain_id}")
            else:
                self.logger.error("PriceMonitor RPC接続失敗")
        except Exception as e:
            self.logger.error(f"PriceMonitor RPC接続エラー: {e}")

    def _get_uniswap_price(self, pair: str) -> float:
        """Uniswap V3から価格取得（失敗時はNoneを返す安全弁付き）"""
        try:
            fees = [500, 3000, 10000]  # 0.05%, 0.3%, 1%
            for fee in fees:
                try:
                    quoter_address = self.w3.to_checksum_address("0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6")
                    quoter = self.w3.eth.contract(address=quoter_address, abi=self._get_quoter_abi())

                    amount_in = self.w3.to_wei(1, 'ether')
                    amount_out = quoter.functions.quoteExactInputSingle(
                        self.weth, self.usdc, fee, amount_in, 0
                    ).call()

                    price = self.w3.from_wei(amount_out, 'mwei')
                    self.logger.info(f"Uniswap V3 ({fee/10000}%) 価格取得成功: {price:.4f}")
                    return round(float(price), 4)
                except:
                    continue
            raise Exception("すべてのfee tierで失敗")
        except Exception as e:
            self.logger.error(f"Uniswap V3価格取得エラー: {e}")
            return None # ⚠️ 安全弁：失敗時は固定値ではなくNoneを返す

    def _get_sushiswap_price(self, pair: str) -> float:
        """SushiSwapから価格取得（失敗時はNoneを返す）"""
        try:
            quoter_address = self.w3.to_checksum_address("0x0524e833ccd057e4d7a296e3aaab9f7675964ce1")
            quoter = self.w3.eth.contract(address=quoter_address, abi=self._get_v3_quoter_v2_abi())
            amount_in = self.w3.to_wei(1, 'ether')
            fees = [500, 3000, 10000]

            for fee in fees:
                try:
                    params = (self.weth, self.native_usdc, amount_in, fee, 0)
                    outputs = quoter.functions.quoteExactInputSingle(params).call()
                    amount_out = outputs[0]

                    price = self.w3.from_wei(amount_out, 'mwei')
                    self.logger.info(f"SushiSwap V3 ({fee/10000}%) 価格取得成功: {price:.4f}")
                    return round(float(price), 4)
                except Exception as inner_e:
                    continue

            raise Exception("全fee tierでリバート、または流動性がありません")
        except Exception as e:
            self.logger.error(f"SushiSwap価格取得エラー: {e}")
            return None # ⚠️ 安全弁

    def _get_pancakeswap_price(self, pair: str) -> float:
        """PancakeSwap V3から価格取得（引数順序正常化・USDC二段構え版）"""
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

    async def get_prices(self) -> Dict[str, Dict[str, float]]:
        """3DEXの価格取得"""
        prices = {}
        for pair in self.pairs:
            uniswap_price = self._get_uniswap_price(pair)
            sushiswap_price = self._get_sushiswap_price(pair)
            pancakeswap_price = self._get_pancakeswap_price(pair)

            # Noneを弾くフィルター用の辞書を構築
            dex_data = {}
            if uniswap_price is not None: dex_data["uniswap_v3"] = uniswap_price
            if sushiswap_price is not None: dex_data["sushiswap"] = sushiswap_price
            if pancakeswap_price is not None: dex_data["pancakeswap"] = pancakeswap_price

            prices[pair] = dex_data

        self.logger.debug(f"3DEX価格取得結果: {prices}")
        return prices

    async def start_monitoring(self):
        self.is_running = True
        self.logger.info("Price monitoring started (Mainnet 本物価格取得)")
        await self.telegram.send_message("🟢 PriceMonitor started (Mainnet)")

        try:
            while self.is_running:
                start_time = datetime.now()

                prices = await self.get_prices()
                opportunities = self.detector.detect_opportunities(prices)

                if opportunities:
                    for opp in opportunities:
                        result = self.profitability.calculate_profitability(opp)
                        if result and result.get("is_profitable"):
                            self.logger.warning(f"✅ 実行可能機会: ${result['estimated_profit_usd']} | {result['pair']}")
                            success = self.executor.execute(result)
                            if success:
                                self.logger.warning(f"🎯 Executorが処理完了: {result['pair']}")

                self.logger.info(f"[{start_time.strftime('%H:%M:%S')}] {len(self.pairs)}ペアを監視完了")
                await asyncio.sleep(self.monitoring_interval)

        except asyncio.CancelledError:
            self.logger.info("Price monitoring stopped gracefully")
            if self.stop_callback:
                self.stop_callback()
        except Exception as e:
            self.logger.error(f"Monitoring error: {e}")
        finally:
            self.is_running = False

    def stop(self):
        self.is_running = False
        self.logger.info("PriceMonitor stopped")
        if self.stop_callback:
            self.stop_callback()

    def _get_quoter_abi(self):
        """Uniswap V3 等の旧Quoter(フラット引数用) ABI"""
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

    def _get_v3_quoter_v2_abi(self):
        """SushiSwap / PancakeSwap V3 等のQuoterV2(構造体引数用) ABI"""
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

