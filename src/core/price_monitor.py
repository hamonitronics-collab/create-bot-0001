import asyncio
from typing import Dict, Callable
from datetime import datetime
from web3 import Web3
import importlib

# 必要なクラスをインポート
from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier
from .opportunity_detector import OpportunityDetector
from .profitability import ProfitabilityCalculator
from .executor import Executor

class PriceMonitor:
    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier, stop_callback: Callable = None):
        self.config = config
        self.logger = logger
        self.telegram = telegram
        self.stop_callback = stop_callback
        self.monitoring_interval = config['bot'].get('monitoring_interval', 2.0)
        self.pairs = config.get('pairs', [])
        self.is_running = False
        self.w3 = None

        self.detector = OpportunityDetector(config, logger, telegram)
        self.profitability = ProfitabilityCalculator(config, logger, telegram)
        self.executor = Executor(config, logger, telegram)

        self.dex_adapters = {}

    def _init_adapters(self):
        """
        💡 【究極のFactoryパターン：YAML完全駆動モード】
        dexes.yaml の設定(module, class_name)を読み取り、
        if文やフォルダ検索なしでDEXアダプターを全自動生成する。
        """
        import importlib

        self.dex_adapters = {}
        dex_configs = self.config.get('dexes', {})

        # YAMLに書かれているDEX設定をループ処理
        for dex_name, dex_info in dex_configs.items():
            module_name = dex_info.get("module")
            class_name = dex_info.get("class_name")

            # YAMLにモジュールやクラス名の指定がない場合はスキップ
            if not module_name or not class_name:
                self.logger.warning(f"⚠️ {dex_name} は config に module と class_name がないためスキップします。")
                continue

            try:
                # 💡 ハック1: src/dex/ 配下の指定されたモジュール(v3_baseなど)を動的にインポート
                full_module_path = f"src.dex.{module_name}"
                module = importlib.import_module(full_module_path)

                # 💡 ハック2: そのモジュールの中から、指定されたクラス(BaseV3Adapterなど)を抽出
                adapter_class = getattr(module, class_name)

                # 💡 ハック3: クラスを初期化！※ここで dex_name (uniswap_v3など) も第4引数として渡します！
                self.dex_adapters[dex_name] = adapter_class(self.w3, self.logger, self.config, dex_name)

                self.logger.info(f"🚀 [YAML自動生成] {dex_name} を {class_name} ({module_name}.py) として起動しました！")

            except Exception as e:
                self.logger.error(f"❌ {dex_name} の動的ロード中にエラーが発生しました: {e}")

    async def _connect_rpc(self):
        """非同期でRPCに接続し、成功したらアダプターを初期化する"""
        try:
            chain = self.config['bot']['chain']
            rpc_url = self.config['rpc'][chain]['url']

            def connect():
                w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={'timeout': 5}))
                # 💡 修正1: chain_id の取得もフリーズの原因になるため、ここで裏処理として取得してしまう
                if w3.is_connected():
                    return w3, w3.eth.chain_id
                return None, None

            self.w3, chain_id = await asyncio.to_thread(connect)

            if self.w3:
                self.logger.info(f"✅ RPC接続成功 | Chain ID: {chain_id}")
                self._init_adapters()
            else:
                self.logger.error("❌ RPC接続失敗")
        except Exception as e:
            self.logger.error(f"RPC接続エラー: {e}")

    async def get_prices(self) -> Dict[str, Dict[str, float]]:
        if not self.w3 or not (await asyncio.to_thread(self.w3.is_connected)):
            await self._connect_rpc()
            if not self.w3: return {}

        prices = {}
        for pair in self.pairs:
            base_sym, quote_sym = pair.split("/")
            base_data = self.config.get('tokens', {}).get(base_sym)
            quote_data = self.config.get('tokens', {}).get(quote_sym)

            if not base_data or not quote_data: continue

            token_base = self.w3.to_checksum_address(base_data['address'])
            token_quote = self.w3.to_checksum_address(quote_data['address'])

            trade_amount_usd = self.config.get('trading', {}).get('trade_amount_usd', 100.0)
            quote_decimals = quote_data.get('decimals', 6)
            base_decimals = base_data.get('decimals', 18)
            amount_in_wei = int(trade_amount_usd * (10 ** quote_decimals))

            dex_data_buy = {}
            dex_data_sell = {}
            dex_names = list(self.dex_adapters.keys())

            # 💡【ステップ1】まずは全DEXで「往路（買う）」の見積もりを一斉取得
            tasks_buy = []
            for dex_name, adapter in self.dex_adapters.items():
                params_buy = {"amount_in": amount_in_wei, "quote_decimals": quote_decimals, "base_decimals": base_decimals}
                tasks_buy.append(asyncio.to_thread(adapter.get_price, pair, token_quote, token_base, params_buy))

            results_buy = await asyncio.gather(*tasks_buy, return_exceptions=True)

# 往路で手に入る「最大枚数(Wei)」を計算（一番条件が良いDEXで買った場合の枚数）
            max_base_amount_wei = 0
            for i, res in enumerate(results_buy):
                # 💡 修正1: 0以上の数字ではなく「Noneではない（辞書が返ってきた）」で判定
                if not isinstance(res, Exception) and res is not None:
                    dex_data_buy[dex_names[i]] = res  # 辞書データをそのまま保存

                    # 💡 修正2: 割り算による逆算を廃止！アダプターがくれた「本物のWei」を直接使う！
                    base_amount_wei = res["amount_out_wei"]
                    if base_amount_wei > max_base_amount_wei:
                        max_base_amount_wei = base_amount_wei

            # 💡【ステップ2】往路で手に入れた「正確なトークン枚数」を使って、全DEXで「復路（売る）」の見積もりを取得！
            if max_base_amount_wei > 0:
                tasks_sell = []
                for dex_name, adapter in self.dex_adapters.items():
                    # 復路なので decimals を逆にする
                    params_sell = {"amount_in": max_base_amount_wei, "quote_decimals": base_decimals, "base_decimals": quote_decimals}
                    tasks_sell.append(asyncio.to_thread(adapter.get_price, pair, token_base, token_quote, params_sell))

                results_sell = await asyncio.gather(*tasks_sell, return_exceptions=True)

                for i, res in enumerate(results_sell):
                    # 💡 修正3: ここも None 判定に変更して辞書をそのまま保存
                    if not isinstance(res, Exception) and res is not None:
                        dex_data_sell[dex_names[i]] = res

            if dex_data_buy and dex_data_sell:
                 prices[pair] = {"buy": dex_data_buy, "sell": dex_data_sell}

        return prices

    async def start_monitoring(self):
        self.is_running = True
        self.logger.info("Price monitoring started")
        #await self.telegram.send_message("🟢 PriceMonitor started")

        while self.is_running:
            prices = await self.get_prices()
            if prices:
                opportunities = self.detector.detect_opportunities(prices)
                if opportunities:
                    self.logger.warning(f"検知された機会: {len(opportunities)}件")

                    for opp in opportunities:
                        # 💡 修正：非同期関数の中で安全に「辞書データ」から各要素を掘り出して処理する
                        async def process_opportunity_async(opportunity_data):
                            try:
                                # 1. 収益性の計算
                                calc = self.profitability.calculate_profitability(opportunity_data)

                                # 2. 利益が出るなら実行エンジンを叩く
                                if calc and calc.get("is_profitable"):
                                    # 🚀 ここでExecutorの非同期処理を完璧に呼び出します！
                                    await self.executor.execute(calc)
                            except Exception as e:
                                self.logger.error(f"❌ 機会処理中にエラーが発生: {e}")

                        # メインループを邪魔させずにタスクを即時射出
                        asyncio.create_task(process_opportunity_async(opp))

            await asyncio.sleep(self.monitoring_interval)