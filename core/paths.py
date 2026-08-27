"""
core/paths.py — Centralised path resolver (dev + PyInstaller compatible).

When running as a PyInstaller bundle, sys.frozen = True and
sys.executable points to the .exe.  All user-writable data (movements, logs)
must live next to the .exe, not inside the extracted _MEIPASS temp folder.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _base() -> Path:
    """Root directory for user data.

    Development  : project root  (two levels up from core/)
    PyInstaller  : folder that contains the .exe
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR  = _base()
DATA_DIR  = BASE_DIR / "data"
MOVES_DIR = DATA_DIR / "movements"
COND_DIR  = DATA_DIR / "conditions"   # template images for plan conditions
PLANS_DIR = DATA_DIR / "plans"        # saved hunt plans (.json)
LOG_FILE  = BASE_DIR / "debug.log"
