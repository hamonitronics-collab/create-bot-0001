import yaml
import os
from typing import Dict
from pathlib import Path

def load_config(config_path: str = "config/config.yaml") -> Dict:
    """
    config.yaml を読み込んで辞書形式で返す
    要件定義: すべての設定を一元管理
    """
    try:
        # 絶対パスに変換（実行場所に関係なく読み込めるように）
        base_dir = Path(__file__).parent.parent.parent  # project root
        full_path = base_dir / config_path
        
        if not full_path.exists():
            # 相対パスも試す
            full_path = Path(config_path)
        
        with open(full_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        print(f"✅ Config loaded successfully from: {full_path}")
        return config
        
    except FileNotFoundError:
        print(f"❌ Config file not found: {config_path}")
        # デフォルト設定を返す（フォールバック）
        return get_default_config()
        
    except yaml.YAMLError as e:
        print(f"❌ YAML parsing error: {e}")
        return get_default_config()
        
    except Exception as e:
        print(f"❌ Unexpected error loading config: {e}")
        return get_default_config()


def get_default_config() -> Dict:
    """設定ファイルが見つからない場合のデフォルト設定"""
    return {
        'bot': {
            'chain': 'arbitrum',
            'monitoring_interval': 2.0,
        },
        'trading': {
            'price_difference_threshold': 0.5,
            'min_profit_usd': 5.0,
            'max_slippage': 0.8,
            'max_gas_price_gwei': 30,
        },
        'risk_management': {
            'max_drawdown_percent': 20.0,
            'stop_on_consecutive_failures': 3,
        },
        'pairs': ['WETH/USDC'],
        'dexes': ['uniswap_v3', 'sushiswap'],
        'telegram': {
            'enabled': False,
            'chat_id': '',
            'token': ''
        },
        'logging': {
            'level': 'INFO'
        }
    }


# 直接実行した場合のテスト用
if __name__ == "__main__":
    config = load_config()
    print("Loaded config keys:", list(config.keys()))