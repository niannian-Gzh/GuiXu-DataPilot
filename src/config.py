from pathlib import Path
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    with open(PROJECT_ROOT / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve(relative_path: str) -> str:
    """把配置里的相对路径，解析成基于项目根的绝对路径字符串。"""
    return str(PROJECT_ROOT / relative_path)