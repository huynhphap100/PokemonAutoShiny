"""
ui/ocr_overlay.py — OCR result overlay showing detected text.

Appears at bottom-right corner of screen (always visible, never covered
by the app or game). Uses same CTkToplevel+self.after() pattern as Toast.
"""
from __future__ import annotations

from core.debug_log import dlog

from typing import Optional
import customtkinter as ctk

_BG   = "#0A1E2E"
_BD   = "#1E8080"
_BTXT = "#3ECFB2"
_BBG  = "#0E3535"
_TXT  = "#D8EAF8"

SHOW_MS = 4000
_W, _H  = 360, 140


class OcrOverlay(ctk.CTkToplevel):
    _instance: Optional["OcrOverlay"] = None

    @classmethod
    def show(cls, master, text: str, is_shiny: bool = False,
             region: Optional[tuple] = None) -> None:
        if cls._instance is not None:
            try:
                if cls._instance.winfo_exists():
                    cls._instance.destroy()
            except Exception:
                pass
            cls._instance = None
        dlog(f"[OcrOverlay.show] text={repr(text[:40])}")
        try:
            cls._instance = cls(master, text)
        except Exception as exc:
            dlog(f"[OcrOverlay] error: {exc}")

    def __init__(self, master, text: str) -> None:
        super().__init__(master)

        text  = (text or "").strip()
        self._lines = [l.strip() for l in text.split("\n") if l.strip()] or ["(no text)"]

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x  = sw - _W - 16
        y  = sh - _H - 52

        dlog(f"[OcrOverlay.__init__] pos=({x},{y})")

        # Set geometry & alpha immediately — but do NOT call overrideredirect yet.
        # CTkToplevel runs its own after(200ms) init that would reset it.
        self.geometry(f"{_W}x{_H}+{x}+{y}")
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.0)
        self.title("")

        self._build()

        # Delay borderless + fade until after CTkToplevel's 200ms internal init
        self.after(260, self._start)

    def _start(self) -> None:
        """Called 260ms after creation — after CTkToplevel finishes its init."""
        try:
            self.overrideredirect(True)
            self.lift()
            self.attributes("-topmost", True)
            dlog("[OcrOverlay._start] overrideredirect set, starting fade")
            self._fade_in(0.0)
        except Exception as exc:
            dlog(f"[OcrOverlay._start] error: {exc}")

    def _build(self) -> None:
        inner = ctk.CTkFrame(self, fg_color=_BG, corner_radius=0,
                             border_width=2, border_color=_BD)
        inner.pack(fill="both", expand=True)
        inner.grid_columnconfigure(0, weight=1)

        badge_row = ctk.CTkFrame(inner, fg_color="transparent")
        badge_row.grid(row=0, column=0, sticky="w", padx=8, pady=(6, 0))
        ctk.CTkLabel(badge_row, text="\U0001f4f8 OCR Read",
                     font=("Segoe UI", 9, "bold"),
                     fg_color=_BBG, text_color=_BTXT,
                     corner_radius=3, padx=5, pady=2).pack(side="left")

        ctk.CTkFrame(inner, fg_color=_BD, height=1, corner_radius=0).grid(
            row=1, column=0, sticky="ew", padx=8, pady=(4, 3))

        n     = len(self._lines)
        fsize = max(9, min(13, max(_H - 50, 20) // max(n, 1) - 2))
        for i, line in enumerate(self._lines[:6]):
            ctk.CTkLabel(inner, text=line,
                         font=("Consolas", fsize, "bold"),
                         fg_color="transparent", text_color=_TXT,
                         anchor="w", justify="left",
                         ).grid(row=2 + i, column=0, sticky="ew", padx=10, pady=1)

    def _fade_in(self, a: float) -> None:
        a = min(a + 0.18, 0.92)
        self._safe_alpha(a)
        if a < 0.92:
            self.after(18, self._fade_in, a)
        else:
            self.after(SHOW_MS, self._fade_out, a)

    def _fade_out(self, a: float) -> None:
        if not self.winfo_exists():
            return
        a = max(a - 0.13, 0.0)
        self._safe_alpha(a)
        if a > 0:
            self.after(28, self._fade_out, a)
        else:
            try:
                self.destroy()
            except Exception:
                pass
            if OcrOverlay._instance is self:
                OcrOverlay._instance = None

    def _safe_alpha(self, v: float) -> None:
        try:
            self.attributes("-alpha", v)
        except Exception:
            pass
