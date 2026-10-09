from pathlib import Path
from typing import Any
import yaml

SCHEME_DIR = Path(__file__).parent

def load_scheme(name: str) -> dict[str, Any]:
    path = SCHEME_DIR / f"{name}.yml"
    if not path.exists():
        raise FileNotFoundError(f"Scheme not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

PAPER_SCHEME = load_scheme("paper_scheme")
REPO_SCHEME = load_scheme("repo_scheme")
COMMON_SCHEME = load_scheme("common")
THREE_LAYER_SCHEME = load_scheme("micro_macro_micro")
