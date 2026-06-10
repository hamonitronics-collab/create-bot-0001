# src/core/triangular_detector.py

class TriangularDetector:
    def __init__(self, w3, logger, config):
        self.w3 = w3
        self.logger = logger
        self.config = config

        # 設定から最低利益率（しきい値）と基準通貨（USDCなど）を取得
        trading_config = self.config.get('trading', {})
        self.threshold = trading_config.get('min_profit_usd', 0.1)
        self.base_currency = trading_config.get('base_currency', 'USDC')
        self.trade_amount_usd = trading_config.get('trade_amount_usd', 100.0)

        self.logger.info(f"🧠 TriangularDetector initialized (min_profit: ${self.threshold})")

    def detect_opportunities(self, dex_adapters: dict):
        """
        登録されたすべてのDEXに対して、三角アビトラのルートを総当たりで計算する
        """
        routes = self.config.get('triangular_routes', [])
        if not routes:
            self.logger.warning("⚠️ config.yaml に triangular_routes が設定されていません。")
            return []

        opportunities = []

        # 1. 各ルート（例: USDC -> WETH -> ARB -> USDC）をループ
        for route in routes:
            # 今回はルートの最初と最後が USDC（base_currency）であることを前提とします
            token1, token2, token3 = route

            # 各区間のペア名を生成
            pair1 = f"{token1}/{token2}" if token1 != self.base_currency else f"{token2}/{token1}"
            pair2 = f"{token2}/{token3}" # ここは順番通りに作れない場合があるので後で調整が必要になるかも
            pair3 = f"{token3}/{token1}" if token1 != self.base_currency else f"{token3}/{token1}"

            # 2. 登録されている各DEX（Uniswap等）でそのルートを試す
            # （※本当は「DEX A -> DEX B -> DEX C」というDEXを跨ぐ三角も強いですが、
            # まずは「1つのDEX内での三角（例：Uniswap内だけで回す）」から実装します）
            for dex_name, adapter in dex_adapters.items():
                self.logger.debug(f"🔍 [{dex_name}] 三角ルート検索: {token1} ➔ {token2} ➔ {token3} ➔ {token1}")

                try:
                    # --- STEP 1: token1 (USDC) -> token2 (WETH) ---
                    # 100ドルをWETHに替える
                    amount_in_wei_1 = int(self.trade_amount_usd * (10 ** self.config['tokens'][token1]['decimals']))
                    params1 = {
                        "amount_in": amount_in_wei_1,
                        "quote_decimals": self.config['tokens'][token1]['decimals'],
                        "base_decimals": self.config['tokens'][token2]['decimals']
                    }
                    addr1_in = self.config['tokens'][token1]['address']
                    addr1_out = self.config['tokens'][token2]['address']

                    # get_priceは実効価格を返すので、獲得量を計算し直すか、アダプター側でamount_outを返すようにするか...
                    # 現在のアダプターは実効価格（Price）を返す仕様なので、獲得量を算出します
                    price1 = adapter.get_price(pair1, addr1_in, addr1_out, params1)
                    if price1 == 0: continue

                    # (USDC -> WETH の場合、price1は 1600 などの数字。獲得WETH = 投入USDC / price1)
                    # ※ここの計算は通貨ペアの並び（WETH/USDCかUSDC/WETHか）によって割るか掛けるか変わるため、
                    # 一番確実なのは、アダプター側から「実効価格」ではなく「獲得したトークン枚数（Wei）」を
                    # 直接もらうことです。

                except Exception as e:
                    self.logger.error(f"❌ [{dex_name}] 三角ルート計算エラー ({route}): {e}")
                    continue

        return opportunities