"""
ui/ocr_bubble.py — Comic-style speech-bubble overlays at OCR detection positions.

Creates a full-screen transparent canvas window (Windows transparent-color trick)
and draws one bubble per group of nearby detections directly on the game screen.
Uses plain tk.Toplevel (no CTkToplevel delay issues) + Windows -transparentcolor.

Bubble style:
  ┌───────────────────────┐
  │  📸  Nidorino Lv. 24  │
  └───────────────────────┘
  (drawn at the detected text's screen position)
"""
from __future__ import annotations

import tkinter as tk
from typing import Optional
from core.debug_log import dlog

# ── Visual constants ──────────────────────────────────────────────────────────
_CHROMA   = "#000001"     # transparent colour key (Windows only)
_BG       = "#0B1E30"     # bubble fill
_BD       = "#1E9090"     # bubble border (teal)
_TXT      = "#E0F0FF"     # bubble text
_SHINY_BD = "#FFD700"     # shiny border
_FONT     = ("Segoe UI", 10, "bold")
_PAD      = 8             # inner padding px
_RADIUS   = 6             # "corner rounding" via extra rectangles
_SHOW_MS  = 3500          # display duration before fade
_FADE_INT = 30            # fade step interval ms
_FADE_STP = 0.12          # opacity step per interval


class OcrBubbleOverlay:
    """Full-screen transparent window showing speech bubbles at OCR positions."""

    _current: Optional["OcrBubbleOverlay"] = None

    # ── Class API ─────────────────────────────────────────────────────────────

    @classmethod
    def show(
        cls,
        master,
        groups: list,        # [(text, sx, sy, sw, sh), ...]
        is_shiny: bool = False,
    ) -> None:
        """Create (or replace) the bubble overlay.

        Parameters
        ----------
        master : tk widget
            Tkinter parent (typically the App window).
        groups : list of (text, sx, sy, sw, sh)
            Each tuple is a group of nearby OCR detections.
            Coordinates are absolute screen pixels.
        is_shiny : bool
            Whether shiny was detected (changes border colour).
        """
        # Dismiss previous
        if cls._current is not None:
            try:
                cls._current._dismiss()
            except Exception:
                pass
            cls._current = None

        if not groups:
            return

        try:
            cls._current = cls(master, groups, is_shiny)
        except Exception as exc:
            dlog(f"[OcrBubble] show error: {exc}")

    # ── Instance ──────────────────────────────────────────────────────────────

    def __init__(self, master, groups: list, is_shiny: bool) -> None:
        win = tk.Toplevel(master)
        self._win = win

        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()

        win.overrideredirect(True)
        win.geometry(f"{sw}x{sh}+0+0")
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.0)
        try:
            win.attributes("-transparentcolor", _CHROMA)
        except Exception:
            pass
        win.configure(bg=_CHROMA)

        self._canvas = tk.Canvas(
            win, bg=_CHROMA, highlightthickness=0,
            width=sw, height=sh,
        )
        self._canvas.pack(fill="both", expand=True)

        bd_color = _SHINY_BD if is_shiny else _BD
        self._draw_groups(groups, bd_color)

        dlog(f"[OcrBubble] drawing {len(groups)} group(s)")

        # Fade in, then show, then fade out
        self._fade_in(0.0)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw_groups(self, groups: list, bd_color: str) -> None:
        cv = self._canvas
        for (text, sx, sy, sw, sh) in groups:
            self._draw_bubble(cv, text, sx, sy, sw, sh, bd_color)

    def _draw_bubble(
        self, cv: tk.Canvas,
        text: str,
        sx: int, sy: int, sw: int, sh: int,
        bd_color: str,
    ) -> None:
        """Draw a single speech-bubble at the given screen position."""
        # Ensure minimum size
        sw = max(sw, 40)
        sh = max(sh, 16)

        # Outer border rectangle
        x1, y1 = sx - _PAD, sy - _PAD - 2
        x2, y2 = sx + sw + _PAD, sy + sh + _PAD + 2

        # Shadow (slight offset darker rect)
        cv.create_rectangle(x1 + 2, y1 + 2, x2 + 2, y2 + 2,
                            fill="#050F1A", outline="", width=0)
        # Fill
        cv.create_rectangle(x1, y1, x2, y2,
                            fill=_BG, outline=bd_color, width=2)
        # Top accent bar
        cv.create_rectangle(x1 + 2, y1 + 2, x2 - 2, y1 + 5,
                            fill=bd_color, outline="", width=0)

        # Wrap text to fit sw px
        wrapped = _wrap_text(text, max(sw, 80))

        cv.create_text(
            sx, sy + 4,
            text=wrapped,
            anchor="nw",
            fill=_TXT,
            font=_FONT,
            width=max(sw + _PAD, 80),
            justify="left",
        )

    # ── Animation ─────────────────────────────────────────────────────────────

    def _fade_in(self, a: float) -> None:
        a = min(a + _FADE_STP * 2, 0.92)
        self._set_alpha(a)
        if a < 0.92:
            self._win.after(_FADE_INT, self._fade_in, a)
        else:
            self._win.after(_SHOW_MS, self._begin_fade_out)

    def _begin_fade_out(self) -> None:
        self._win.after(0, self._fade_out, 0.92)

    def _fade_out(self, a: float) -> None:
        if not self._exists():
            return
        a = max(a - _FADE_STP, 0.0)
        self._set_alpha(a)
        if a > 0:
            self._win.after(_FADE_INT, self._fade_out, a)
        else:
            self._dismiss()

    def _dismiss(self) -> None:
        try:
            self._win.destroy()
        except Exception:
            pass
        if OcrBubbleOverlay._current is self:
            OcrBubbleOverlay._current = None

    def _set_alpha(self, v: float) -> None:
        try:
            self._win.attributes("-alpha", v)
        except Exception:
            pass

    def _exists(self) -> bool:
        try:
            return bool(self._win.winfo_exists())
        except Exception:
            return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wrap_text(text: str, max_px: int, chars_per_px: float = 0.13) -> str:
    """Rough word-wrap: estimate max chars per line from pixel width."""
    max_chars = max(int(max_px * chars_per_px), 20)
    words = text.split()
    lines, current = [], ""
    for w in words:
        candidate = (current + " " + w).strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    return "\n".join(lines) if lines else text
