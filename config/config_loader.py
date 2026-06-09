import yaml
import os
from pathlib import Path

def load_config(config_dir="config"):
    """
    指定されたディレクトリ内の複数のYAMLファイルを読み込み、
    1つの大きな設定辞書に結合して返すローダー
    """
    base_path = Path(config_dir)
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

    if not merged_config:
        raise ValueError("❌ どの設定ファイルも正しく読み込めませんでした。")

    return merged_config

# テスト用
if __name__ == "__main__":
    config = load_config()
    print("✅ マージされた設定ファイル:")
    print(config.keys())