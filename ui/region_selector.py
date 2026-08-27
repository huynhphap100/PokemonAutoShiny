"""
ui/region_selector.py — Full-screen drag-to-select region overlay.

Shows a semi-transparent black overlay over the entire screen.
User drags to draw a rectangle; the screen coordinates are returned
via callback(x, y, w, h) on release.  ESC or a tiny selection → callback(None).
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional, Tuple

RegionTuple = Tuple[int, int, int, int]  # x, y, w, h (screen-absolute)


class RegionSelector:
    """Fullscreen semi-transparent drag-to-select overlay.

    Parameters
    ----------
    callback:
        Called with (x, y, w, h) on successful selection, or None if cancelled.
    instruction:
        Text shown at the top of the overlay.
    """

    _ALPHA       = 0.45
    _OUTLINE     = "#00D4AA"
    _OUTLINE_W   = 2
    _CORNER_SIZE = 6

    def __init__(
        self,
        parent,
        callback: Callable[[Optional[RegionTuple]], None],
        instruction: str = (
            "Drag to select the Pokémon name bar area   •   ESC to cancel"
        ),
    ) -> None:
        self.callback    = callback
        self._start_x    = 0
        self._start_y    = 0
        self._rect_id    = None
        self._label_ids: list[int] = []

        win = tk.Toplevel(parent)
        self._win = win
        win.attributes("-fullscreen", True)
        win.attributes("-topmost", True)
        win.attributes("-alpha", self._ALPHA)
        win.configure(bg="black")
        win.config(cursor="crosshair")
        win.focus_force()

        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()

        canvas = tk.Canvas(win, bg="black", highlightthickness=0,
                           width=sw, height=sh)
        canvas.pack(fill="both", expand=True)
        self._canvas = canvas

        # Instruction banner
        canvas.create_rectangle(0, 0, sw, 64, fill="#0D1117", outline="")
        canvas.create_text(
            sw // 2, 32,
            text=instruction,
            fill="#00D4AA",
            font=("Segoe UI", 14, "bold"),
            anchor="center",
        )
        canvas.create_text(
            sw // 2, 52,
            text="Release mouse to confirm selection",
            fill="#6E7681",
            font=("Segoe UI", 10),
            anchor="center",
        )

        canvas.bind("<ButtonPress-1>",   self._on_press)
        canvas.bind("<B1-Motion>",       self._on_drag)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        win.bind("<Escape>",             lambda _e: self._cancel())

    # ── Mouse handlers ────────────────────────────────────────────────────────

    def _on_press(self, event: tk.Event) -> None:
        self._start_x = event.x_root
        self._start_y = event.y_root
        self._clear_rect()

    def _on_drag(self, event: tk.Event) -> None:
        self._clear_rect()
        x1, y1 = self._to_canvas(self._start_x, self._start_y)
        x2, y2 = event.x, event.y

        # Dim overlay outside selection
        self._rect_id = self._canvas.create_rectangle(
            x1, y1, x2, y2,
            outline=self._OUTLINE,
            width=self._OUTLINE_W,
            fill="",
        )
        # Size label
        w = abs(event.x_root - self._start_x)
        h = abs(event.y_root - self._start_y)
        mid_x = (x1 + x2) / 2
        mid_y = min(y1, y2) - 14
        lbl = self._canvas.create_text(
            mid_x, mid_y,
            text=f"{w} × {h} px",
            fill=self._OUTLINE,
            font=("Consolas", 11, "bold"),
        )
        self._label_ids = [lbl]

    def _on_release(self, event: tk.Event) -> None:
        x = min(self._start_x, event.x_root)
        y = min(self._start_y, event.y_root)
        w = abs(event.x_root - self._start_x)
        h = abs(event.y_root - self._start_y)
        self._destroy()
        if w > 8 and h > 8:
            self.callback((x, y, w, h))
        else:
            self.callback(None)

    def _cancel(self) -> None:
        self._destroy()
        self.callback(None)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _to_canvas(self, sx: int, sy: int) -> tuple[int, int]:
        """Convert screen-absolute to canvas-relative coordinates."""
        rx = self._win.winfo_rootx()
        ry = self._win.winfo_rooty()
        return sx - rx, sy - ry

    def _clear_rect(self) -> None:
        if self._rect_id is not None:
            self._canvas.delete(self._rect_id)
            self._rect_id = None
        for lid in self._label_ids:
            self._canvas.delete(lid)
        self._label_ids = []

    def _destroy(self) -> None:
        try:
            self._win.destroy()
        except Exception:
            pass
