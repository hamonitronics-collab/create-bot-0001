# src/core/executor.py
import json
import os
import time
import asyncio
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
                raise FileNotFoundError("ArbitrageExecutor.json が見つかりません。")

            with open(json_path, "r") as f:
                contract_json = json.load(f)
                abi = contract_json["abi"]

            self.contract = self.w3.eth.contract(address=self.contract_address, abi=abi)
            self.logger.info(f"💾 自作スマートコントラクトのABIロードに成功しました！ Address: {self.contract_address}")
        except Exception as e:
            self.logger.error(f"❌ コントラクトABIの読み込みに失敗: {e}")

    async def execute(self, opportunity_calc: dict):
        """
        監視エンジンから検知された機会を受け取り、オンチェーンで実行する
        """
        if not self.contract:
            self.logger.error("❌ コントラクトが初期化されていないため、実行をスキップします。")
            return False

        # =========================================================
        # 🚀 【完全版】 三角アービトラージ（Triangular）の実行ルート
        # =========================================================
        if opportunity_calc.get("type") == "triangular":
            try:
                dex = opportunity_calc.get("dex")
                route = opportunity_calc.get("route")
                net_profit = opportunity_calc.get("net_profit_usd")
                steps = opportunity_calc.get("steps", [])
                final_usd = opportunity_calc.get("final_usd", 0.0)

                self.logger.warning(
                    f"🔥 [Executor発動!!] 三角アビトラ実行プロセスを開始します...\n"
                    f"  DEX: {dex} | ルート: {' ➔ '.join(route)}\n"
                    f"  見込み純利益: ${net_profit:.2f}\n"
                    f"  STEP1: {steps[0]['amount_in']} wei 投入 ➔ STEP3獲得期待量: ${final_usd:.4f}"
                )

                # パラメータの準備
                tokens_config = self.config.get('tokens', {})
                dex_config = self.config.get('dexes', {})

                tokens_addresses = [
                    self.w3.to_checksum_address(tokens_config[route[0]]['address']),
                    self.w3.to_checksum_address(tokens_config[route[1]]['address']),
                    self.w3.to_checksum_address(tokens_config[route[2]]['address'])
                ]

                # stepからfeeを抽出（取得できなければデフォルト値を使用）
                fees = [
                    int(steps[0].get('fee', 500)),
                    int(steps[1].get('fee', 3000)),
                    int(steps[2].get('fee', 3000))
                ]

                dex_router = self.w3.to_checksum_address(dex_config[dex]['router_address'])
                amount_in = int(steps[0]['amount_in'])
                min_profit_wei = 0 # 🛡️ 利益防壁はスマコンが持っているので、Python側は0で送信

                # DryRunチェック
                if self.dry_run:
                    self.logger.info("🚨 [DryRunモード] オンチェーントランザクションの構築シミュレーション成功。実弾は消費されていません。")
                    return True

                if not self.private_key:
                    self.logger.error("❌ 秘密鍵が未設定です。")
                    return False

                # 💡 実弾トランザクション送信
                loop = asyncio.get_event_loop()
                nonce = self.w3.eth.get_transaction_count(self.account_address)
                gas_price = self.w3.eth.gas_price

                tx_build = self.contract.functions.executeTriangularArbitrage(
                    tokens_addresses,
                    fees,
                    dex_router,
                    amount_in,
                    min_profit_wei
                ).build_transaction({
                    'chainId': self.w3.eth.chain_id,
                    'gas': 800000, # 三角はガスを食うため多めに確保
                    'gasPrice': gas_price,
                    'nonce': nonce,
                })

                signed_tx = self.w3.eth.account.sign_transaction(tx_build, private_key=self.private_key)
                self.logger.warning("🚀 トランザクションをメインネットへパブリッシュ中...")

                tx_hash = await loop.run_in_executor(None, lambda: self.w3.eth.send_raw_transaction(signed_tx.rawTransaction))
                self.logger.info(f"⏳ オンチェーン承認待ち... TxHash: {tx_hash.hex()}")

                tx_receipt = await loop.run_in_executor(None, lambda: self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30))

                if tx_receipt['status'] == 1:
                    self.logger.warning(f"🏆 🏆 🏆 【三角アビトラ大勝利】 取引が正常にブロックへ書き込まれました！ Tx: {tx_hash.hex()}")
                #    # スマホ通知
                #    await self.telegram.send_message(
                #        f"🏆 **【三角アビトラ成功】** 🏆\n"
                #        f"DEX: `{dex}`\n"
                #        f"Route: `{' ➔ '.join(route)}`\n"
                #        f"見込み利益: `${net_profit:.2f}`\n"
                #        f"TxHash: `{tx_hash.hex()}`"
                #    )
                else:
                    self.logger.error(f"❌ トランザクションがオンチェーン実行中にRevert（赤字回避防壁が作動）しました。")

                return True
            except Exception as e:
                self.logger.error(f"❌ 三角アビトラ実行中にエラー: {e}")
                return False
        # =========================================================

        # =========================================================
        # 🚀 【修正版】 空間アービトラージ（Spatial）の実行ルート
        # =========================================================
        opp = opportunity_calc.get("opportunity", opportunity_calc)
        pair = opp.get("pair", "")

        if not pair or "/" not in pair:
            return False

        base_sym, quote_sym = pair.split("/")
        tokens_config = self.config.get('tokens', {})

        token_in_address = self.w3.to_checksum_address(tokens_config[quote_sym]['address'])
        token_out_address = self.w3.to_checksum_address(tokens_config[base_sym]['address'])

        decimals = tokens_config[quote_sym].get('decimals', 6)
        trade_amount_dollars = self.config['trading'].get('trade_amount_usd', 100.0)
        amount_in = int(trade_amount_dollars * (10 ** decimals))

        dex_config = self.config.get('dexes', {})
        buy_dex = opp.get("buy_dex")
        sell_dex = opp.get("sell_dex")

        buy_router = self.w3.to_checksum_address(dex_config[buy_dex]['router_address'])
        sell_router = self.w3.to_checksum_address(dex_config[sell_dex]['router_address'])

        fee_buy = opp.get("buy_fee", 500)
        fee_sell = opp.get("sell_fee", 500)
        min_profit = int(0.1 * (10 ** decimals))

        self.logger.warning(f"🔥 【アビトラ戦闘シグナル】 {pair} で空間価格乖離を捕捉！")

        if self.dry_run:
            self.logger.info("🚨 [DryRunモード] オンチェーン注文の送信シミュレーション成功。")
            return True

        try:
            loop = asyncio.get_event_loop()
            nonce = self.w3.eth.get_transaction_count(self.account_address)
            gas_price = self.w3.eth.gas_price

            # 💡 【修正】新型スマコンの関数名「executeSpatialArbitrage」に変更
            tx_build = self.contract.functions.executeSpatialArbitrage(
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

            tx_hash = await loop.run_in_executor(None, lambda: self.w3.eth.send_raw_transaction(signed_tx.rawTransaction))
            self.logger.info(f"⏳ オンチェーン承認待ち... TxHash: {tx_hash.hex()}")

            tx_receipt = await loop.run_in_executor(None, lambda: self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=30))

            if tx_receipt['status'] == 1:
                self.logger.warning(f"🏆 【空間アビトラ大勝利】 取引完了！ Tx: {tx_hash.hex()}")
                await self.telegram.send_message(f"🏆 【空間アビトラ成功】\nペア: {pair}\nTxHash: `{tx_hash.hex()}`")
            else:
                self.logger.error(f"❌ オンチェーン実行中にRevert（赤字回避）しました。")

        except Exception as e:
            self.logger.error(f"❌ 空間アビトラ送信エラー: {e}")