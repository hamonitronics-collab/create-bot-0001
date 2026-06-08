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
    Mainnet本物価格取得版
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
        self.usdc = self.w3.to_checksum_address("0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8")
        self.usdt = self.w3.to_checksum_address("0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9")

        self.logger.info("PriceMonitor initialized (Mainnet本物価格取得)")

    def _connect_rpc(self):
        """Mainnet RPC接続"""
        try:
            #rpc_url = "https://arb1.arbitrum.io/rpc" #testnet
            rpc_url = "https://invictus.ambire.com/arbitrum"  # Mainnet
            self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 10}))
            if self.w3.is_connected():
                self.logger.info(f"✅ PriceMonitor RPC接続成功 (Mainnet) | Chain ID: {self.w3.eth.chain_id}")
            else:
                self.logger.error("PriceMonitor RPC接続失敗")
        except Exception as e:
            self.logger.error(f"PriceMonitor RPC接続エラー: {e}")

    def _get_uniswap_price(self, pair: str) -> float:
        """Uniswap V3から価格取得（複数fee tier対応）"""
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
            return 2500.0

    def _get_sushiswap_price(self, pair: str) -> float:
        """SushiSwapから価格取得（V3 QuoterV2構造体対応）"""
        try:
            # SushiSwap V3 (Arbitrum Mainnet) Quoter
            quoter_address = self.w3.to_checksum_address("0x0524e833ccd057e4d7a296e3aaab9f7675964ce1")

            # Sushi専用の新しいABIを使用
            quoter = self.w3.eth.contract(address=quoter_address, abi=self._get_sushiswap_quoter_abi())
            amount_in = self.w3.to_wei(1, 'ether')
            fees = [500, 3000, 10000] # 0.05%, 0.3%, 1%

            # 使用するUSDCアドレス（引数で動的に渡す場合は適宜変更してください）
            # ここでは新USDCを指定している前提です
            target_usdc = self.w3.to_checksum_address("0xaf88d065e77c8cC2239327C5EDb3A432268e5831")

            for fee in fees:
                try:
                    # 引数を一つのタプル(params)として渡す
                    params = (
                        self.weth,
                        target_usdc,
                        amount_in,
                        fee,
                        0 # sqrtPriceLimitX96
                    )

                    # QuoterV2は複数の値を返すため、[0]でamountOutだけを抽出
                    outputs = quoter.functions.quoteExactInputSingle(params).call()
                    amount_out = outputs[0]

                    price = self.w3.from_wei(amount_out, 'mwei')
                    self.logger.info(f"SushiSwap V3 ({fee/10000}%) 価格取得成功: {price:.4f}")
                    return round(float(price), 4)
                except Exception as inner_e:
                    self.logger.debug(f"SushiSwap V3 fee {fee} 取得失敗詳細: {inner_e}")
                    continue

            raise Exception("全fee tierでリバート、または流動性がありません")
        except Exception as e:
            self.logger.error(f"SushiSwap価格取得エラー: {e}")
            return 2500.0

    def _get_pancakeswap_price(self, pair: str) -> float:
        """PancakeSwap V3から価格取得"""
        try:
            # Arbitrum Mainnet PancakeSwap V3 Router / Quoter
            quoter_address = self.w3.to_checksum_address("0x5e09ACf80C0296740eC5d6F643005a4ef8DaA694")
            quoter = self.w3.eth.contract(address=quoter_address, abi=self._get_quoter_abi())

            amount_in = self.w3.to_wei(1, 'ether')
            fees = [500, 3000, 10000]

            for fee in fees:
                try:
                    amount_out = quoter.functions.quoteExactInputSingle(
                        self.weth, self.usdc, fee, amount_in, 0
                    ).call()
                    price = self.w3.from_wei(amount_out, 'mwei')
                    self.logger.info(f"PancakeSwap V3 ({fee/10000}%) 価格取得成功: {price:.4f}")
                    return round(float(price), 4)
                except:
                    continue
            raise Exception("PancakeSwap全fee tier失敗")
        except Exception as e:
            self.logger.error(f"PancakeSwap価格取得エラー: {e}")
            return 2500.0

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

    def _get_pair_abi(self):
        return [{
            "constant": True,
            "inputs": [],
            "name": "getReserves",
            "outputs": [
                {"name": "_reserve0", "type": "uint112"},
                {"name": "_reserve1", "type": "uint112"},
                {"name": "_blockTimestampLast", "type": "uint32"}
            ],
            "payable": False,
            "stateMutability": "view",
            "type": "function"
        }]

    async def get_prices(self) -> Dict[str, Dict[str, float]]:
        """3DEX (Uniswap V3, SushiSwap, PancakeSwap) の本物価格取得"""
        prices = {}
        for pair in self.pairs:
            try:
                uniswap_price = self._get_uniswap_price(pair)
                sushiswap_price = self._get_sushiswap_price(pair)
                pancakeswap_price = self._get_pancakeswap_price(pair)

                prices[pair] = {
                    "uniswap_v3": uniswap_price,
                    "sushiswap": sushiswap_price,
                    "pancakeswap": pancakeswap_price,
                }
            except Exception as e:
                self.logger.error(f"価格取得エラー {pair}: {e}")
                base_price = 2500.0
                prices[pair] = {
                    "uniswap_v3": base_price,
                    "sushiswap": base_price,
                    "pancakeswap": base_price,
                }

        self.logger.debug(f"3DEX価格取得: {prices}")
        return prices

    # start_monitoring と stop メソッドは変更なし（以前のものを使用）
    async def start_monitoring(self):
        # （省略せず以前の完全版を使用してください）
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

    def _get_sushiswap_quoter_abi(self):
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