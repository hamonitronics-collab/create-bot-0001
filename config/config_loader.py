import yaml
import os
from pathlib import Path
from typing import Dict, Any
import sys

def load_config() -> Dict[str, Any]:
    """
    config.yaml を読み込む
    - プロジェクトルートからの相対パスで探す
    - 環境変数対応
    """
    # プロジェクトルートの絶対パスを取得（実行場所に依存しない）
    project_root = Path(__file__).parent.parent
    config_path = project_root / "config" / "config.yaml"

    if not config_path.exists():
        print(f"❌ エラー: 設定ファイルが見つかりません → {config_path}")
        sys.exit(1)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if config is None:
            raise ValueError("YAMLファイルが空です")

        # 環境変数で上書き（.env対応）
        config = override_with_env(config)

        # 簡単なバリデーション
        validate_config(config)

        print(f"✅ 設定ファイルを読み込みました: {config_path}")
        return config

    except Exception as e:
        print(f"❌ 設定ファイル読み込みエラー: {e}")
        sys.exit(1)


def override_with_env(config: Dict) -> Dict:
    """環境変数で設定を上書き（.env対応）"""
    # 例: TELEGRAM_TOKEN が環境変数にあれば上書き
    if os.getenv("TELEGRAM_TOKEN"):
        if "telegram" not in config:
            config["telegram"] = {}
        config["telegram"]["token"] = os.getenv("TELEGRAM_TOKEN")

    return config


def validate_config(config: Dict):
    """必須項目の簡易チェック"""
    required = ["bot", "trading", "risk_management"]
    for key in required:
        if key not in config:
            raise ValueError(f"必須セクション '{key}' がconfig.yamlにありません")