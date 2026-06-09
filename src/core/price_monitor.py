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
        💡 【完全汎用化：プラグイン自動検出モード】
        src/dex/Individual フォルダ内のファイルを全自動スキャンし、
        定義されているDEXアダプタークラスを自動で発掘・ロードする。
        """
        import os
        from inspect import isclass

        # アダプターが格納されているディレクトリのパス
        adapter_dir = os.path.join("src", "dex", "Individual")
        if not os.path.exists(adapter_dir):
            self.logger.error(f"❌ アダプターディレクトリが見つかりません: {adapter_dir}")
            return

        # フォルダ内のファイルをループ処理
        for file_name in os.listdir(adapter_dir):
            # .py で終わり、__init__.py 以外のファイルを対象にする
            if file_name.endswith(".py") and file_name != "__init__.py":
                module_name = file_name[:-3]  # 拡張子の ".py" を取り除く (例: "sushiswap_v3")
                full_module_path = f"src.dex.Individual.{module_name}"

                try:
                    # ファイルを動的にインポート（ロード）
                    module = importlib.import_module(full_module_path)

                    # ロードしたファイルの中身（属性）をすべて検査
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)

                        # それが「クラス」であり、名前が「Adapter」で終わるものを自動発見
                        if isclass(attr) and attr_name.endswith("Adapter") and attr_name != "BaseDEX":

                            # 💡 yamlの設定（キー名）とファイル名が一致している場合のみ有効化
                            # 例: module_nameが "sushiswap_v3" で、yamlにも "sushiswap_v3" があれば合致
                            if module_name in self.config.get('dexes', {}):
                                self.dex_adapters[module_name] = attr(self.w3, self.logger, self.config)
                                self.logger.info(f"🚀 [ファイル自動検出] {file_name} から {attr_name} をハックしてロードしました！")

                except Exception as e:
                    self.logger.error(f"❌ ファイル {file_name} の自動ロード中にエラー: {e}")

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
        # 接続がなければ再接続を試みる
        if not self.w3 or not (await asyncio.to_thread(self.w3.is_connected)):
            await self._connect_rpc()
            if not self.w3: return {}

        prices = {}
        for pair in self.pairs:
            base_sym, quote_sym = pair.split("/")
            base_data = self.config.get('tokens', {}).get(base_sym)
            quote_data = self.config.get('tokens', {}).get(quote_sym)

            if not base_data or not quote_data: continue

            # 💡 変更点1：見積もりは「USDC(Quote)を支払って、ARB(Base)を買う」方向でシミュレート
            token_in = self.w3.to_checksum_address(quote_data['address'])
            token_out = self.w3.to_checksum_address(base_data['address'])

            # 💡 変更点2：configから「$100」を取得し、桁数情報と一緒に専用パラメータ(params)を作る
            trade_amount_usd = self.config.get('trading', {}).get('trade_amount_usd', 100.0)
            quote_decimals = quote_data.get('decimals', 6)   # USDCは6桁
            base_decimals = base_data.get('decimals', 18)    # ARBなどは18桁

            amount_in_wei = int(trade_amount_usd * (10 ** quote_decimals))

            params = {
                "amount_in": amount_in_wei,
                "quote_decimals": quote_decimals,
                "base_decimals": base_decimals
            }

            dex_data = {}
            tasks = []
            dex_names = []

            for dex_name, adapter in self.dex_adapters.items():
                def fetch_price(ad=adapter, current_params=params):
                    # 💡 変更点3：空っぽだった {} の代わりに、金額と桁数を入れた current_params を渡す！
                    return ad.get_price(pair, token_in, token_out, current_params)

                tasks.append(asyncio.to_thread(fetch_price))
                dex_names.append(dex_name)

            # すべてのDEXの返事を一斉に待つ（並列処理）
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(results):
                if not isinstance(result, Exception) and result is not None and result > 0:
                    dex_data[dex_names[i]] = result

            if dex_data: prices[pair] = dex_data

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