# src/core/triangular_detector.py
import time
import asyncio
class TriangularDetector:
    """
    3つの通貨を順番に両替して利益を狙う「三角アービトラージ」検知器
    """
    def __init__(self, config, logger):
        self.logger = logger
        self.config = config

        trading_config = self.config.get('trading', {})
        self.threshold = trading_config.get('min_profit_usd', 0.1) # 例: 0.1ドルの利益でGO
        self.base_currency = trading_config.get('base_currency', 'USDC')
        self.trade_amount_usd = trading_config.get('trade_amount_usd', 100.0)

        self.logger.info(f"🧠 TriangularDetector initialized (min_profit: ${self.threshold})")

    async def detect_opportunities(self, dex_adapters: dict):
        self.logger.info("Price monitoring started")
        routes = self.config.get('triangular_routes', [])
        if not routes:
            return []

        opportunities = []
        for route in routes:
            # ルートの解体（例: USDC -> WETH -> ARB -> USDC）
            token1, token2, token3 = route

            # 各通貨のアドレスと小数点を取得
            t1_info = self.config['tokens'].get(token1)
            t2_info = self.config['tokens'].get(token2)
            t3_info = self.config['tokens'].get(token3)

            if not t1_info or not t2_info or not t3_info:
                continue

            addr1 = t1_info['address']
            addr2 = t2_info['address']
            addr3 = t3_info['address']

            dec1 = t1_info['decimals']
            dec2 = t2_info['decimals']
            dec3 = t3_info['decimals']

            # ペア名の作成（ログ表示用）
            pair1 = f"{token1}/{token2}"
            pair2 = f"{token2}/{token3}"
            pair3 = f"{token3}/{token1}"

            # 今回は「単一のDEX内での三角アビトラ」を探す
            for dex_name, adapter in dex_adapters.items():
                try:
                    # --- STEP 1 ---
                    amount_in_wei_1 = int(self.trade_amount_usd * (10 ** dec1))
                    params1 = {"amount_in": amount_in_wei_1, "quote_decimals": dec1, "base_decimals": dec2}

                    # 💡 修正2: asyncio.to_thread を使って裏側で通信させる！
                    data1 = await asyncio.to_thread(adapter.get_price, pair1, addr1, addr2, params1)
                    if not data1: continue
                    amount_out_wei_1 = data1["amount_out_wei"]

                    # --- STEP 2 ---
                    params2 = {"amount_in": amount_out_wei_1, "quote_decimals": dec2, "base_decimals": dec3}

                    # 💡 同様に修正
                    data2 = await asyncio.to_thread(adapter.get_price, pair2, addr2, addr3, params2)
                    if not data2: continue
                    amount_out_wei_2 = data2["amount_out_wei"]

                    # --- STEP 3 ---
                    params3 = {"amount_in": amount_out_wei_2, "quote_decimals": dec3, "base_decimals": dec1}

                    # 💡 同様に修正
                    data3 = await asyncio.to_thread(adapter.get_price, pair3, addr3, addr1, params3)
                    if not data3: continue
                    amount_out_wei_3 = data3["amount_out_wei"]

                    # --- 利益計算 ---
                    # 最終的なUSDCを人間が読める数字（float）に戻す
                    final_usd = amount_out_wei_3 / (10 ** dec1)
                    profit_usd = final_usd - self.trade_amount_usd
                    self.logger.info(f"profit_usd: {profit_usd}, threshold: {self.threshold}")
                    if profit_usd > self.threshold:
                        self.logger.info(f"profit_usd > self.threshold")
                        opp = {
                            "type": "triangular",
                            "dex": dex_name,
                            "route": route,
                            "profit_usd": profit_usd,
                            "invested_usd": self.trade_amount_usd,
                            "final_usd": final_usd,
                            # 実行時に必要なデータを全て保存
                            "steps": [
                                {"token_in": addr1, "token_out": addr2, "fee": data1["fee"], "amount_in": amount_in_wei_1},
                                {"token_in": addr2, "token_out": addr3, "fee": data2["fee"], "amount_in": amount_out_wei_1},
                                {"token_in": addr3, "token_out": addr1, "fee": data3["fee"], "amount_in": amount_out_wei_2},
                            ],
                            "timestamp": time.time()
                        }
                        self.logger.info(
                            f"🔺 [三角アビトラ検知!!] {dex_name} | {token1}➔{token2}➔{token3}➔{token1} | "
                            f"利益: ${profit_usd:.2f} (投入: ${self.trade_amount_usd:.2f} ➔ 最終: ${final_usd:.2f})"
                        )
                        opportunities.append(opp)
                    else:
                        # 利益が出なかった場合も、裏でこっそり結果を表示（デバッグ用）
                        self.logger.info(
                            f"📉 [三角ルート] {dex_name} | {token1}➔{token2}➔{token3}➔{token1} | "
                            f"最終: ${final_usd:.4f} (利益: ${profit_usd:.4f})"
                        )

                except Exception as e:
                    self.logger.error(f"❌ [{dex_name}] 三角ルート計算エラー ({route}): {e}")
                    continue

        return opportunities