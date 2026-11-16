#!/usr/bin/env python3
"""Assemble browser/src into a self-contained Tampermonkey userscript."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
PROJECT = ROOT.parent
LOCALE = PROJECT / "chat_topic_finder" / "locales" / "he.json"
TEMPLATE = SRC / "main.template.js"
OUT = ROOT / "dist" / "ai-chat-backup.user.js"

text = TEMPLATE.read_text(encoding="utf-8")
locale = json.loads(LOCALE.read_text(encoding="utf-8"))
replacements = {
    "/*__ADAPTER_CLAUDE__*/": (SRC / "adapters" / "claude.js").read_text(encoding="utf-8").rstrip(),
    "/*__ADAPTER_CHATGPT__*/": (SRC / "adapters" / "chatgpt.js").read_text(encoding="utf-8").rstrip(),
    "/*__ADAPTER_GEMINI__*/": (SRC / "adapters" / "gemini.js").read_text(encoding="utf-8").rstrip(),
    "/*__HE_TRANSLATIONS__*/": json.dumps(locale.get("userscript", {}), ensure_ascii=False, separators=(",", ":")),
}
for marker, value in replacements.items():
    if text.count(marker) != 1:
        raise SystemExit(f"Expected exactly one {marker!r} marker; found {text.count(marker)}")
    text = text.replace(marker, value, 1)
if "/*__" in text:
    raise SystemExit("Unresolved build placeholder remains in output")
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(text, encoding="utf-8")
print(f"Built {OUT} ({len(text):,} characters)")
