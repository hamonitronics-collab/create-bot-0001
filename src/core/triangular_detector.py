# src/core/triangular_detector.py
import time
import asyncio

semaphore = asyncio.Semaphore(1)
class TriangularDetector:
    """
    3つの通貨を順番に両替して利益を狙う「三角アービトラージ」検知器
    """
    def __init__(self, config, logger):
        self.logger = logger
        self.config = config

        trading_config = self.config.get('trading', {})
        self.threshold = trading_config.get('min_profit_usd', 0.1)
        self.base_currency = trading_config.get('base_currency', 'USDC')
        self.trade_amount_usd = trading_config.get('trade_amount_usd', 100.0)

        self.logger.info(f"🧠 TriangularDetector initialized (min_profit: ${self.threshold})")

    async def detect_opportunities(self, dex_adapters: dict):
        async def _checked_check(route, dex_name, adapter):
            async with semaphore:
                return await self._check_single_route(route, dex_name, adapter)

        routes = self.config.get('triangular_routes', [])
        if not routes:
            return []

        tasks = []
        # 💡 修正1: 各ルート × 各DEX の調査を「タスク化」してリストにまとめる
        for route in routes:
            for dex_name, adapter in dex_adapters.items():
                tasks.append(_checked_check(route, dex_name, adapter))

        # 💡 修正2: 用意したすべてのタスクを「同時に（一斉に）」走らせる！
        # これにより20秒かかっていた処理が、一番遅いDEXの応答時間(数秒)だけで終わります
        results = await asyncio.gather(*tasks, return_exceptions=True)

        opportunities = []
        for res in results:
            if isinstance(res, Exception):
                self.logger.error(f"❌ ルート並行処理エラー: {res}")
            elif res is not None:  # 機会（辞書）が見つかって返ってきた場合
                opportunities.append(res)

        return opportunities

    async def _check_single_route(self, route, dex_name, adapter):
        """1つのルート・1つのDEXに対する三角アビトラ計算（並行処理用）"""
        token1, token2, token3 = route

        t1_info = self.config['tokens'].get(token1)
        t2_info = self.config['tokens'].get(token2)
        t3_info = self.config['tokens'].get(token3)

        if not t1_info or not t2_info or not t3_info:
            return None

        addr1, dec1 = t1_info['address'], t1_info['decimals']
        addr2, dec2 = t2_info['address'], t2_info['decimals']
        addr3, dec3 = t3_info['address'], t3_info['decimals']

        pair1 = f"{token1}/{token2}"
        pair2 = f"{token2}/{token3}"
        pair3 = f"{token3}/{token1}"

        try:
            # --- STEP 1 ---
            amount_in_wei_1 = int(self.trade_amount_usd * (10 ** dec1))
            params1 = {"amount_in": amount_in_wei_1, "quote_decimals": dec1, "base_decimals": dec2}

            data1 = await asyncio.to_thread(adapter.get_price, pair1, addr1, addr2, params1)
            if not data1: return None
            amount_out_wei_1 = data1["amount_out_wei"]

            # --- STEP 2 ---
            params2 = {"amount_in": amount_out_wei_1, "quote_decimals": dec2, "base_decimals": dec3}

            data2 = await asyncio.to_thread(adapter.get_price, pair2, addr2, addr3, params2)
            if not data2: return None
            amount_out_wei_2 = data2["amount_out_wei"]

            # --- STEP 3 ---
            params3 = {"amount_in": amount_out_wei_2, "quote_decimals": dec3, "base_decimals": dec1}

            data3 = await asyncio.to_thread(adapter.get_price, pair3, addr3, addr1, params3)
            if not data3: return None
            amount_out_wei_3 = data3["amount_out_wei"]

            # --- 利益計算 ---
            final_usd = amount_out_wei_3 / (10 ** dec1)
            profit_usd = final_usd - self.trade_amount_usd

            if profit_usd > self.threshold:
                opp = {
                    "type": "triangular",
                    "dex": dex_name,
                    "route": route,
                    "profit_usd": profit_usd,
                    "invested_usd": self.trade_amount_usd,
                    "final_usd": final_usd,
                    "steps": [
                        {"token_in": addr1, "token_out": addr2, "fee": data1["fee"], "amount_in": amount_in_wei_1},
                        {"token_in": addr2, "token_out": addr3, "fee": data2["fee"], "amount_in": amount_out_wei_1},
                        {"token_in": addr3, "token_out": addr1, "fee": data3["fee"], "amount_in": amount_out_wei_2},
                    ],
                    "timestamp": time.time()
                }
                self.logger.warning(
                    f"🔺 [三角アビトラ検知!!] {dex_name} | {token1}➔{token2}➔{token3}➔{token1} | "
                    f"利益: ${profit_usd:.2f} (投入: ${self.trade_amount_usd:.2f} ➔ 最終: ${final_usd:.2f})"
                )
                return opp
            else:
                self.logger.info(
                    f"📉 [三角ルート] {dex_name} | {token1}➔{token2}➔{token3}➔{token1} | "
                    f"最終: ${final_usd:.4f} (利益: ${profit_usd:.4f})"
                )
                return None

        except Exception as e:
            self.logger.error(f"❌ [{dex_name}] 三角ルート計算エラー ({route}): {e}")
            await asyncio.sleep(1)  # エラーが続く場合の過負荷防止のため少し待機
            return None