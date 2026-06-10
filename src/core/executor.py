# src/core/executor.py
import json
import os
import time
import asyncio  # 💡 追記：フリーズ防止用の非同期ライブラリ
from dotenv import load_dotenv
from typing import Dict, Optional
from web3 import Web3

from ..utils.logger import BotLogger
from ..utils.telegram import TelegramNotifier

class Executor:
    """
    アービトラージ機会を実行するモジュール
    自作スマートコントラクト（ArbitrageExecutor.sol）と通信し、オンチェーンで一撃スワップを完結させます。
    """
    def __init__(self, config: dict, logger: BotLogger, telegram: TelegramNotifier, mode: str = "spatial"):
        self.config = config
        self.logger = logger
        self.telegram = telegram
        self.mode = mode

        # GitHubリポジトリの設定構造を維持
        self.chain = config['bot']['chain']
        self.rpc_url = config['rpc'][self.chain]['url']
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))

        # 安全第一: DryRunフラグ
        self.dry_run = config['bot'].get('dry_run', True)

        # アカウント情報と秘密鍵のロード

        load_dotenv()
        self.account_address = self.w3.to_checksum_address(os.getenv(f'account_{mode.lower()}'))
        self.private_key = os.getenv(f'BOT_PRIVATE_KEY_{mode.lower()}')


        # コントラクト設定の動的ロード
        self.contract_address = config.get('contract', {}).get('address')
        self.contract = None

        if self.contract_address:
            self.contract_address = self.w3.to_checksum_address(self.contract_address)
            self._load_contract()
        else:
            self.logger.warning("⚠️ config.yaml に 'contract.address' が指定されていません。")

    def _load_contract(self):
        """Foundryのビルド成果物(JSON)からABIを自動ロードする"""
        try:
            possible_paths = [
                os.path.join("src", "contracts", "out", "ArbitrageExecutor.sol", "ArbitrageExecutor.json"),
                os.path.join("contracts", "out", "ArbitrageExecutor.sol", "ArbitrageExecutor.json")
            ]

            json_path = None
            for path in possible_paths:
                if os.path.exists(path):
                    json_path = path
                    break

            if not json_path:
                raise FileNotFoundError("ArbitrageExecutor.json が見つかりません。forge build が成功しているか確認してください。")

            with open(json_path, "r") as f:
                contract_json = json.load(f)
                abi = contract_json["abi"]

            self.contract = self.w3.eth.contract(address=self.contract_address, abi=abi)
            self.logger.info(f"💾 自作スマートコントラクトのABIロードに成功しました！ Address: {self.contract_address}")
        except Exception as e:
            self.logger.error(f"❌ コントラクトABIの読み込みに失敗: {e}")

    # 💡 修正点：関数に「async」を付与して非同期対応にする
    async def execute(self, opportunity_calc: dict):
        """
        監視エンジンから検知された機会を受け取り、
        自作スマートコントラクトの executeArbitrage 関数をオンチェーンで実行する
        """
        if not self.contract:
            self.logger.error("❌ コントラクトが初期化されていないため、実行をスキップします。")
            return

        # 💡 修正：送られてきた辞書データをそのまま opp として扱う！（保険の get も追加）
        opp = opportunity_calc.get("opportunity", opportunity_calc)
        pair = opp.get("pair", "")

        # 💡 安全対策：もし pair が空だったり "/" が無い変なデータならここで弾く
        if not pair or "/" not in pair:
            self.logger.error(f"❌ ペア情報が正しく取得できませんでした。実行をスキップします: {opp}")
            return

        # トークン情報の抽出
        base_sym, quote_sym = pair.split("/")
        tokens_config = self.config.get('tokens', {})

        # --- (これ以降の config 読み込みやトランザクション処理はそのまま変更なし！) ---
        if quote_sym not in tokens_config or base_sym not in tokens_config:
            self.logger.error(f"❌ トークン設定が config に不足しています: {pair}")
            return

        token_in_address = self.w3.to_checksum_address(tokens_config[quote_sym]['address'])
        token_out_address = self.w3.to_checksum_address(tokens_config[base_sym]['address'])

        # 💡 修正点：YAMLの記述に合わせて「trading.trade_amount_usd」から動的に金額を取得するよう修正！
        decimals = tokens_config[quote_sym].get('decimals', 6)
        trade_amount_dollars = self.config['trading'].get('trade_amount_usd', 100.0)
        amount_in = int(trade_amount_dollars * (10 ** decimals))

        # DEXルーターのアドレスをconfigから動的取得
        dex_config = self.config.get('dexes', {})
        buy_dex = opp.get("buy_dex")
        sell_dex = opp.get("sell_dex")

        if buy_dex not in dex_config or sell_dex not in dex_config:
            self.logger.error(f"❌ DEX設定が config に不足しています: {buy_dex} / {sell_dex}")
            return

        buy_router = self.w3.to_checksum_address(dex_config[buy_dex]['router_address'])
        sell_router = self.w3.to_checksum_address(dex_config[sell_dex]['router_address'])

        fee_buy = opp.get("buy_fee", 500)
        fee_sell = opp.get("sell_fee", 500)

        min_profit = int(0.1 * (10 ** decimals))

        self.logger.warning(f"🔥 【アビトラ戦闘シグナル】 {pair} で価格乖離を捕捉！")
        self.logger.warning(f"   ➔ {buy_dex} で購入 ➔ {sell_dex} で売却。投入金額: ${trade_amount_dollars}")

        # DryRun（テストモード）ならここで安全に離脱
        if self.dry_run:
            self.logger.info("🚨 [DryRunモード有効] オンチェーン注文の送信シミュレーション成功。実弾は消費されていません。")
            return

        if not self.private_key:
            self.logger.error("❌ 秘密鍵が設定されていないため、トランザクションに署名できません。")
            return

        try:
            # 💡 修正点：通信ブロックを防ぐため、イベントループを取得して非同期スレッドに逃がす
            loop = asyncio.get_event_loop()

            nonce = self.w3.eth.get_transaction_count(self.account_address)
            gas_price = self.w3.eth.gas_price

            tx_build = self.contract.functions.executeArbitrage(
                token_in_address, token_out_address, amount_in,
                buy_router, fee_buy, sell_router, fee_sell, min_profit
            ).build_transaction({
                'chainId': self.w3.eth.chain_id,
                'gas': 350000,
                'gasPrice': gas_price,
                'nonce': nonce,
            })

            signed_tx = self.w3.eth.account.sign_transaction(tx_build, private_key=self.private_key)

            self.logger.warning("🚀 トランザクションをメインネットへパブリッシュ中...")

            # 💡 修正点：send と wait_for_receipt を非同期実行に変え、メインループを絶対に止めないようにする！
            tx_hash = await loop.run_in_executor(None, lambda: self.w3.eth.send_raw_transaction(signed_tx.rawTransaction))
            self.logger.info(f"⏳ オンチェーン承認待ち... TxHash: {tx_hash.hex()}")

            tx_receipt = await loop.run_in_executor(None, lambda: self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30))

            if tx_receipt['status'] == 1:
                self.logger.warning(f"🏆 🏆 🏆 【アビトラ大勝利】 取引が正常にブロックへ書き込まれました！ Tx: {tx_hash.hex()}")
                self.telegram.send_message(f"🏆 【アビトラ成功通知】\nペア: {pair}\n投入原資: ${trade_amount_dollars}\nTxHash: {tx_hash.hex()}")
            else:
                self.logger.error(f"❌ トランザクションがオンチェーン実行中にRevert（強制終了）しました。")

        except Exception as e:
            self.logger.error(f"❌ オンチェーン注文の送信中に深刻なエラーが発生しました: {e}")