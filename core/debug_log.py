"""
core/debug_log.py — Centralized debug logger.

Writes to d:/Workbase/Plugins/Gum/PokemonAutoShiny/debug.log
Thread-safe (Python logging module handles locking internally).

Usage anywhere:
    from core.debug_log import dlog
    dlog("something happened")
"""
from __future__ import annotations

import logging
import sys
from core.paths import LOG_FILE as _LOG_FILE

# ── set up the logger ─────────────────────────────────────────────────────────
_logger = logging.getLogger("poke_shiny")
_logger.setLevel(logging.DEBUG)

if not _logger.handlers:
    # File handler — always write to debug.log (overwrite on each app start)
    _fh = logging.FileHandler(str(_LOG_FILE), mode="a", encoding="utf-8")
    _fh.setLevel(logging.DEBUG)
    _fmt = logging.Formatter(
        "[%(asctime)s.%(msecs)03d] [%(threadName)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    _fh.setFormatter(_fmt)
    _logger.addHandler(_fh)

    # Console handler too
    _ch = logging.StreamHandler(sys.stdout)
    _ch.setLevel(logging.DEBUG)
    _ch.setFormatter(_fmt)
    _logger.addHandler(_ch)


def dlog(msg: str) -> None:
    """Write a debug line. Never raises."""
    try:
        _logger.debug(msg)
    except Exception:
        pass


def clear_log() -> None:
    """Truncate the log file (call once at app startup)."""
    try:
        _LOG_FILE.write_text("", encoding="utf-8")
        dlog("=== debug.log started ===")
    except Exception:
        pass
