import yaml
import os
from pathlib import Path

def load_config(strategy_yaml_name: str):
    """
    指定されたディレクトリ内の複数のYAMLファイルを読み込み、
    1つの大きな設定辞書に結合して返すローダー
    """
    base_path = Path("config")
    merged_config = {}

    # 読み込む分割ファイルのリスト
    yaml_files = ["config.yaml", "tokens.yaml", "rpc.yaml", "dexes.yaml"]

    for file_name in yaml_files:
        file_path = base_path / file_name
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as f:
                try:
                    data = yaml.safe_load(f)
                    if data:
                        # 辞書をマージ（上書き・追加）する
                        merged_config.update(data)
                except Exception as e:
                    print(f"❌ 設定ファイル読み込みエラー ({file_name}): {e}")
        else:
            print(f"⚠️ 警告: 設定ファイル {file_name} が見つかりません。スキップします。")

    if not strategy_yaml_name:
        # 3. 指定された戦略固有の設定ファイル(spatialなど)で上書き(オーバーライド)
        strategy_path = base_path / strategy_yaml_name
        if strategy_path.exists():
            with open(strategy_path, "r", encoding="utf-8") as f:
                strategy_data = yaml.safe_load(f)
                if strategy_data:
                    merged_config.update(strategy_data)
                    print(f"✅ 戦略設定 {strategy_yaml_name} を適用しました")
        else:
            raise FileNotFoundError(f"❌ 戦略設定ファイル {strategy_yaml_name} が見つかりません")
    else:
        print("⚠️ 戦略固有の設定ファイルが指定されていません。基本設定のみで起動します。")

    if not merged_config:
        raise ValueError("❌ どの設定ファイルも正しく読み込めませんでした。")

    return merged_config

# テスト用
if __name__ == "__main__":
    config = load_config()
    print("✅ マージされた設定ファイル:")
    print(config.keys())