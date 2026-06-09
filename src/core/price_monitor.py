import asyncio
from typing import Dict, Callable
from datetime import datetime
from web3 import Web3

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier
from .opportunity_detector import OpportunityDetector
from .profitability import ProfitabilityCalculator
from .executor import Executor

from ..dex.Individual.uniswap_v3 import UniswapV3Adapter
from ..dex.Individual.sushiswap_v3 import SushiSwapV3Adapter

class PriceMonitor:
    """
    DEXから価格情報を監視するモジュール
    【完全自動ルーティング・汎用化対応版】
    """

    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier, stop_callback: Callable = None):
        self.config = config
        self.logger = logger
        self.telegram = telegram
        self.stop_callback = stop_callback
        self.monitoring_interval = config['bot'].get('monitoring_interval', 2.0)
        self.pairs = config.get('pairs', ['WETH/USDC'])
        self.is_running = False

        self.w3 = None
        self._connect_rpc()

        self.detector = OpportunityDetector(config, logger, telegram)
        self.profitability = ProfitabilityCalculator(config, logger, telegram)
        self.executor = Executor(config, logger, telegram)

        # 💡 修正ポイント: 古い `self.tokens` のハードコード辞書を完全に削除しました！
        # 代わりに、config_loader が合体させた tokens.yaml のデータを直接使います。

        self.dex_adapters = {
            "uniswap_v3": UniswapV3Adapter(self.w3, self.logger),
            "sushiswap": SushiSwapV3Adapter(self.w3, self.logger)
        }

        self.logger.info(f"PriceMonitor initialized (監視対象: {self.pairs})")

    def _connect_rpc(self):
        try:
            rpc_url = self.config.get('rpc', {}).get(self.config['bot'].get('chain', 'arbitrum'), {}).get('url', "")
            self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 10}))
            if self.w3.is_connected():
                self.logger.info(f"✅ PriceMonitor RPC接続成功 | Chain ID: {self.w3.eth.chain_id}")
            else:
                self.logger.error("PriceMonitor RPC接続失敗")
        except Exception as e:
            self.logger.error(f"PriceMonitor RPC接続エラー: {e}")

    async def get_prices(self) -> Dict[str, Dict[str, float]]:
        """登録されたすべてのアダプターからループで価格を自動取得"""
        prices = {}

        for pair in self.pairs:
            base_token_sym, quote_token_sym = pair.split("/")

            # 💡 汎用化: configからトークンアドレスを動的取得
            base_token_data = self.config.get('tokens', {}).get(base_token_sym)
            quote_token_data = self.config.get('tokens', {}).get(quote_token_sym)

            if not base_token_data or not quote_token_data:
                self.logger.error(f"⚠️ {pair} のトークン設定が config/tokens.yaml に見つかりません！スキップします。")
                continue

            token_in = self.w3.to_checksum_address(base_token_data['address'])
            token_out = self.w3.to_checksum_address(quote_token_data['address'])

            dex_data = {}
            for dex_name, adapter in self.dex_adapters.items():
                # どんなトークンでも同じように価格を問い合わせる
                price = adapter.get_price(pair, token_in, token_out, {})
                if price is not None:
                    dex_data[dex_name] = price

            if dex_data:
                prices[pair] = dex_data

        return prices

    async def start_monitoring(self):
        self.is_running = True
        self.logger.info("Price monitoring started (完全汎用化基盤稼働中)")
        await self.telegram.send_message("🟢 PriceMonitor started")

        try:
            while self.is_running:
                start_time = datetime.now()

                prices = await self.get_prices()
                opportunities = self.detector.detect_opportunities(prices)

                if opportunities:
                    for opp in opportunities:
                        calculated_result = self.profitability.calculate_profitability(opp)
                        if calculated_result and calculated_result.get("is_profitable"):
                            self.logger.warning(f"✅ 実行可能機会を発見: ${calculated_result['estimated_profit_usd']} | {calculated_result['pair']}")
                            success = self.executor.execute(calculated_result)
                            if success:
                                self.logger.warning(f"🎯 Executorが処理完了: {calculated_result['pair']}")

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