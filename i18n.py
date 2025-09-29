import json
from pathlib import Path

_LANG = {}

def loadLang(path: str) -> None:
    global _LANG
    _LANG = json.loads(Path(path).read_text(encoding="utf-8"))

def pickLang(userLangCode: str | None) -> str:
    base = (userLangCode or "en").split("-")[0].lower()
    return base if base in _LANG else "en"

def tr(lang: str, key: str, **kwargs) -> str:
    msg = _LANG.get(lang, {}).get(key) or _LANG.get("en", {}).get(key) or key
    return msg.format(**kwargs)
