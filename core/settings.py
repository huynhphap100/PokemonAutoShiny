"""
Settings — load/save user config and pynput key utilities.
"""
from __future__ import annotations

import json
from pathlib import Path

from pynput import keyboard as kb

SETTINGS_FILE = Path(__file__).parent.parent / "data" / "settings.json"

DEFAULTS: dict = {
    "toggle_key":    "Key.f8",
    "ocr_check_key": "Key.f9",   # hotkey to insert OCR checkpoint during recording
    "ocr_region":    None,       # [x, y, w, h] last saved OCR region
}


# ── Persistence ───────────────────────────────────────────────────────────────

def load() -> dict:
    """Return merged settings (saved values over defaults)."""
    if SETTINGS_FILE.exists():
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return {**DEFAULTS, **saved}
        except Exception:
            pass
    return dict(DEFAULTS)


def save(data: dict) -> None:
    """Persist settings to disk."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Key helpers ───────────────────────────────────────────────────────────────

def parse_key(key_str: str):
    """Convert a pynput string (e.g. 'Key.f8' or \"'a'\") back to a key object."""
    if key_str.startswith("Key."):
        attr = key_str[4:]  # "f8"
        try:
            return kb.Key[attr]
        except KeyError:
            pass
    elif key_str.startswith("'") and len(key_str) >= 3:
        char = key_str[1:-1]
        return kb.KeyCode.from_char(char)
    return kb.Key.f8  # fallback


def key_display(key) -> str:
    """Human-readable label for a pynput key (e.g. 'F8', 'A', 'Space')."""
    if isinstance(key, kb.Key):
        name = key.name  # e.g. "f8", "space", "ctrl_l"
        if len(name) <= 4:
            return name.upper()
        return name.replace("_", " ").title()
    if isinstance(key, kb.KeyCode):
        return (key.char or "?").upper()
    return str(key)
