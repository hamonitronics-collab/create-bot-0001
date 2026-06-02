# DEX間アービトラージBot

仮想通貨DEX間（主に空間）アービトラージを行うPythonボットです。
要件定義書 v0.3 に準拠して開発しています。

## 特徴
- 設定ファイル(`config.yaml`)でほぼすべてのパラメータを調整可能
- 価格監視 → 機会検知 → 収益性計算 → 実行 の完全モジュール化
- Logger + Telegram通知対応
- モック実装中心（安全に学習・テスト可能）
- 将来的に複数チェーン・本物RPC対応しやすい設計

## プロジェクト構成

dex-arbitrage-bot/                  # プロジェクトルート
├── main.py                         # エントリーポイント（メイン実行ファイル）
├── config/
│   ├── config.yaml                 # 全設定ファイル（監視間隔・閾値・ドローダウンなど）
│   └── config_loader.py            # 設定読み込みモジュール
├── src/
│   ├── core/                       # コアロジック
│   │   ├── price_monitor.py        # 価格監視
│   │   ├── opportunity_detector.py # 機会検知
│   │   ├── profitability.py        # 収益性計算
│   │   └── executor.py             # 実行エンジン
│   ├── utils/                      # ユーティリティ
│   │   ├── logger.py               # ログ管理
│   │   └── telegram.py             # Telegram通知
│   ├── chains/                     # 将来の複数チェーン対応用（空）
│   ├── dex/                        # DEX抽象化用（空）
│   └── contracts/                  # コントラクト用（空）
├── tests/                          # テストコード（未作成）
├── logs/                           # ログ出力先（実行時に自動作成）
├── requirements.txt                # 必要ライブラリ一覧
├── README.md                       # プロジェクト説明
├── .env.example                    # 環境変数テンプレート
└── .gitignore


## セットアップ手順

1. リポジトリをクローンまたはZIP展開
2. 依存ライブラリインストール
   ```bash
   pip install -r requirements.txt

設定ファイル編集Bashcp config/config.yaml.example config/config.yaml   # 必要に応じて
Telegram通知設定（.envまたはconfig.yaml）

実行方法
Bashpython main.py
Ctrl + C で安全停止
注意事項（低リスク運用）

最初は必ずテストネットで検証してください
本番運用前に十分なバックテストと小額テストを実施
ガス代・スリッページで赤字になる可能性が高いことを理解
Private Keyは絶対にハードコードしない

今後の拡張予定

本物RPC接続（Alchemyなど）
Flash Loan対応
複数チェーン対応
バックテスト機能


作成者: ニトロニクス参謀 × Grok
開発方式: ウォーターフォールモデル