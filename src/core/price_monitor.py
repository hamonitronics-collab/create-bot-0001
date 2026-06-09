# src/core/price_monitor.py
import asyncio
from typing import Dict, Callable
from datetime import datetime
from web3 import Web3

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier
from .opportunity_detector import OpportunityDetector
from .profitability import ProfitabilityCalculator
from .executor import Executor

# 🔴 追加: 作成したDEXアダプターをインポート
from ..dex.Individual.uniswap_v3 import UniswapV3Adapter
from ..dex.Individual.sushiswap_v3 import SushiSwapV3Adapter

class PriceMonitor:
    """
    DEXから価格情報を監視するモジュール
    【DEXアダプターパターン実装版】
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

        # 各コアモジュールの初期化
        self.detector = OpportunityDetector(config, logger, telegram)
        self.profitability = ProfitabilityCalculator(config, logger, telegram)
        self.executor = Executor(config, logger, telegram)

        # トークンアドレスの一括定義（Mainnet想定）
        self.tokens = {
            "WETH": self.w3.to_checksum_address("0x82af49447d8a07e3bd95bd0d56f35241523fbab1"),
            "WBTC": self.w3.to_checksum_address("0x2f2a2543B76A4166549F7aaB2e75Bef0aefc5B0f"),
            "USDC": self.w3.to_checksum_address("0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8"),       # 旧USDC.e (Uniswap用)
            "NATIVE_USDC": self.w3.to_checksum_address("0xaf88d065e77c8cC2239327C5EDb3A432268e5831") # 新Native USDC (Sushi用)
        }

        # 🔴【最重要】使用するDEXアダプターを登録する
        # 将来新しいDEXを追加するときは、ここに1行アダプタークラスを増やすだけで一括変更・反映されます！
        self.dex_adapters = {
            "uniswap_v3": UniswapV3Adapter(self.w3, self.logger),
            "sushiswap": SushiSwapV3Adapter(self.w3, self.logger)
            #"pancakeswap_v3": PancakeSwapV3Adapter(self.w3, self.logger)
        }

        self.logger.info(f"PriceMonitor initialized (DEXアダプターパターン適用版: {list(self.dex_adapters.keys())})")

    def _connect_rpc(self):
        """Mainnet RPC接続"""
        try:
            rpc_url = self.config.get('rpc', {}).get(self.config['bot'].get('chain', 'arbitrum'), {}).get('url', "https://invictus.ambire.com/arbitrum")
            self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 10}))
            if self.w3.is_connected():
                self.logger.info(f"✅ PriceMonitor RPC接続成功 (Mainnet) | Chain ID: {self.w3.eth.chain_id}")
            else:
                self.logger.error("PriceMonitor RPC接続失敗")
        except Exception as e:
            self.logger.error(f"PriceMonitor RPC接続エラー: {e}")

    async def get_prices(self) -> Dict[str, Dict[str, float]]:
        """登録されたすべてのアダプターからループで価格を自動取得"""
        prices = {}

        for pair in self.pairs:
            # ペア文字列（"WETH/USDC"など）から入出力トークンを判定
            base_token, quote_token = pair.split("/")
            token_in = self.tokens.get(base_token)

            # DEXの「方言」によるUSDCの使い分けをマッピング（基盤が整うまでの一時的な措置）
            dex_data = {}

            for dex_name, adapter in self.dex_adapters.items():
                # Uniswapなら旧USDC、SushiSwapなら新Native USDCを選択
                token_out = self.tokens["NATIVE_USDC"] if dex_name == "sushiswap" else self.tokens["USDC"]

                if not token_in or not token_out:
                    continue

                # どんなDEXでも、共通のルール「get_price」を呼ぶだけ！
                price = adapter.get_price(pair, token_in, token_out, {})

                # 🛡️ 安全弁：None（失敗）でなければ監視対象データに加える
                if price is not None:
                    dex_data[dex_name] = price

            prices[pair] = dex_data

        self.logger.debug(f"アダプター経由の価格取得結果: {prices}")
        return prices

    async def start_monitoring(self):
        self.is_running = True
        self.logger.info("Price monitoring started (DEXアダプター基盤稼働中)")
        await self.telegram.send_message("🟢 PriceMonitor started (Adapter Mode)")

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