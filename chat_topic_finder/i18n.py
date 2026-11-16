"""Load UI translations from editable JSON locale files."""
from __future__ import annotations
import json
from pathlib import Path

LOCALE_DIR = Path(__file__).with_name("locales")

def load_locale(language: str = "en") -> dict:
    code = "he" if str(language).lower().startswith("he") else "en"
    path = LOCALE_DIR / f"{code}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
