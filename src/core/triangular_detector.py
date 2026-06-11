# src/core/triangular_detector.py
import time
import asyncio

# 💡 改善点1: 同時リクエスト数を制限するセマフォ
# 1だと非常に安全（BANされない）ですが、ノードの強さに応じて 2 や 3 に調整しても構いません。
rpc_semaphore = asyncio.Semaphore(4)

class TriangularDetector:
    """
    3つの通貨を順番に両替して利益を狙う「三角アービトラージ」検知器
    """
    def __init__(self, config, logger, profitability_calc):
        self.logger = logger
        self.config = config
        self.profit_calc = profitability_calc

        trading_config = self.config.get('trading', {})
        self.threshold = trading_config.get('min_profit_usd', 0.1)
        self.base_currency = trading_config.get('base_currency', 'USDC')
        self.trade_amount_usd = trading_config.get('trade_amount_usd', 100.0)

        self.logger.info(f"🧠 TriangularDetector initialized (min_profit: ${self.threshold})")

    async def detect_opportunities(self, dex_adapters: dict):
        routes = self.config.get('triangular_routes', [])
        if not routes:
            return []

        tasks = []
        # 各ルート × 各DEX の調査をタスク化
        for route in routes:
            for dex_name, adapter in dex_adapters.items():
                # 💡 ここでは直接 _check_single_route を呼び出します（セマフォは関数側で細かく制御）
                tasks.append(self._check_single_route(route, dex_name, adapter))

        # すべてのタスクを同時に並行実行
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

        # 💡 改善点2: RPC通信（get_price）を行う直前のみセマフォを適用し、STEPごとにわずかなウェイトを入れる
        try:
            # --- STEP 1 ---
            amount_in_wei_1 = int(self.trade_amount_usd * (10 ** dec1))
            params1 = {"amount_in": amount_in_wei_1, "quote_decimals": dec1, "base_decimals": dec2}

            async with rpc_semaphore:
                data1 = await asyncio.to_thread(adapter.get_price, pair1, addr1, addr2, params1)
            if not data1: return None
            amount_out_wei_1 = data1["amount_out_wei"]

            # 💡 わずかなインターバルを入れてRPCの連打を防止 (0.05秒〜0.1秒)
            await asyncio.sleep(0.05)

            # --- STEP 2 ---
            params2 = {"amount_in": amount_out_wei_1, "quote_decimals": dec2, "base_decimals": dec3}

            async with rpc_semaphore:
                data2 = await asyncio.to_thread(adapter.get_price, pair2, addr2, addr3, params2)
            if not data2: return None
            amount_out_wei_2 = data2["amount_out_wei"]

            # 💡 わずかなインターバルを入れてRPCの連打を防止
            await asyncio.sleep(0.05)

            # --- STEP 3 ---
            params3 = {"amount_in": amount_out_wei_2, "quote_decimals": dec3, "base_decimals": dec1}

            async with rpc_semaphore:
                data3 = await asyncio.to_thread(adapter.get_price, pair3, addr3, addr1, params3)
            if not data3: return None
            amount_out_wei_3 = data3["amount_out_wei"]

            # --- 利益計算 ---
            final_usd = amount_out_wei_3 / (10 ** dec1)

            # 💡 単純な引き算をやめ、まずは基本データをまとめる
            raw_opp = {
                "type": "triangular",
                "dex": dex_name,
                "route": route,
                "invested_usd": self.trade_amount_usd,
                "final_usd": final_usd,
                "steps": [
                    {"token_in": addr1, "token_out": addr2, "fee": data1["fee"], "amount_in": amount_in_wei_1},
                    {"token_in": addr2, "token_out": addr3, "fee": data2["fee"], "amount_in": amount_out_wei_1},
                    {"token_in": addr3, "token_out": addr1, "fee": data3["fee"], "amount_in": amount_out_wei_2},
                ],
                "timestamp": time.time()
            }

            # 💡 先ほど作った計算機に判定させる
            calc_result = self.profit_calc.calculate_triangular_profitability(raw_opp)

            if calc_result and calc_result["is_profitable"]:
                self.logger.warning(
                    f"🔺 [三角アビトラ検知!!] {dex_name} | {token1}➔{token2}➔{token3}➔{token1} | "
                    f"純利益: ${calc_result['net_profit_usd']:.2f} (粗利: ${calc_result['gross_profit_usd']:.2f} - ガス代: ${calc_result['estimated_gas_usd']:.2f})"
                )
                return calc_result
            else:
                net_profit = calc_result['net_profit_usd'] if calc_result else (final_usd - self.trade_amount_usd)

                # 💡 修正: Gweiの表示も追加！
                gas_info = f" | ガス代: ${calc_result['estimated_gas_usd']:.4f} (Gas Price: {calc_result.get('gas_price_gwei', 0.0):.2f} Gwei)" if calc_result else ""

                self.logger.info(
                    f"📉 [三角ルート] {dex_name} | {token1}➔{token2}➔{token3}➔{token1} | "
                    f"最終: ${final_usd:.4f} (純利益: ${net_profit:.4f}{gas_info})"
                )
                return None

        except Exception as e:
            self.logger.error(f"❌ [{dex_name}] 三角ルート計算エラー ({route}): {e}")
            await asyncio.sleep(1)  # エラーが続く場合の過負荷防止のため待機
            return None