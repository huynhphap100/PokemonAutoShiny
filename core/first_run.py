"""
core/first_run.py — First-launch setup wizard.

Shows a splash window while downloading EasyOCR model weights.
Called by main.py before opening the main UI if models are absent.
"""
from __future__ import annotations

import sys
import threading
import tkinter as tk
from pathlib import Path


# ── Model path detection ──────────────────────────────────────────────────────

def _easyocr_model_dir() -> Path:
    """Return the folder where EasyOCR caches model weights."""
    return Path.home() / ".EasyOCR" / "model"


def _models_ready() -> bool:
    """True if at least one EasyOCR English model weight file exists."""
    model_dir = _easyocr_model_dir()
    if not model_dir.exists():
        return False
    # Look for any .pth or .pt file (the CRAFT + recognition models)
    return any(model_dir.glob("*.pth")) or any(model_dir.glob("*.pt"))


# ── Splash window ─────────────────────────────────────────────────────────────

class _Splash(tk.Tk):
    BG      = "#0B1520"
    FG_HI   = "#E4EFF8"
    FG_LO   = "#7B93AF"
    GREEN   = "#22C55E"
    ACCENT  = "#1A6FBF"
    BAR_BG  = "#182433"
    W, H    = 480, 260

    def __init__(self) -> None:
        super().__init__()
        self.overrideredirect(True)           # borderless
        self.attributes("-topmost", True)
        self.configure(bg=self.BG)
        self._center()
        self._build()

    def _center(self) -> None:
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x  = (sw - self.W) // 2
        y  = (sh - self.H) // 2
        self.geometry(f"{self.W}x{self.H}+{x}+{y}")

    def _build(self) -> None:
        tk.Label(self, text="Pokémon Auto Shiny", bg=self.BG,
                 fg=self.ACCENT, font=("Segoe UI", 22, "bold")).pack(pady=(32, 4))
        tk.Label(self, text="First-time setup", bg=self.BG,
                 fg=self.FG_LO, font=("Segoe UI", 11)).pack()

        self._msg = tk.Label(self, text="Preparing…", bg=self.BG,
                             fg=self.FG_HI, font=("Segoe UI", 10))
        self._msg.pack(pady=(24, 6))

        # Progress bar (fake canvas bar)
        bar_frame = tk.Frame(self, bg=self.BG)
        bar_frame.pack(fill="x", padx=48)
        self._bar_bg = tk.Canvas(bar_frame, bg=self.BAR_BG, height=8,
                                 highlightthickness=0)
        self._bar_bg.pack(fill="x")
        self._bar_fill = self._bar_bg.create_rectangle(0, 0, 0, 8,
                                                       fill=self.GREEN, outline="")
        self._bar_bg.bind("<Configure>", self._on_bar_resize)
        self._bar_w = 0
        self._progress = 0.0

        self._sub = tk.Label(self, text="", bg=self.BG,
                             fg=self.FG_LO, font=("Segoe UI", 9))
        self._sub.pack(pady=(8, 0))

        tk.Label(self,
                 text="This only happens once — models are cached for future launches.",
                 bg=self.BG, fg=self.FG_LO, font=("Segoe UI", 8),
                 wraplength=400).pack(pady=(20, 0))

    def _on_bar_resize(self, e) -> None:
        self._bar_w = e.width

    def set_status(self, msg: str, sub: str = "", progress: float = -1) -> None:
        """Thread-safe status update."""
        self.after(0, self._apply_status, msg, sub, progress)

    def _apply_status(self, msg: str, sub: str, progress: float) -> None:
        self._msg.configure(text=msg)
        self._sub.configure(text=sub)
        if progress >= 0:
            self._progress = max(0.0, min(1.0, progress))
            fill_w = int(self._bar_w * self._progress)
            self._bar_bg.coords(self._bar_fill, 0, 0, fill_w, 8)

    def finish(self) -> None:
        self.after(0, self.destroy)


# ── Download worker ───────────────────────────────────────────────────────────

def _download_models(splash: _Splash) -> bool:
    """
    Import easyocr and trigger model download via Reader initialisation.
    Returns True on success.
    """
    try:
        splash.set_status("Importing AI libraries…", "", 0.05)
        import easyocr  # noqa: F401  (heavy import)

        splash.set_status("Downloading OCR model weights…",
                          "CRAFT text detector (~12 MB)", 0.15)

        # Instantiate the Reader — this triggers model download if absent
        # gpu=False keeps it CPU-only (safer for general installs)
        reader = easyocr.Reader(["en"], gpu=False, verbose=False)   # noqa: F841
        splash.set_status("Models ready ✓", "", 1.0)
        return True

    except Exception as exc:
        splash.set_status(f"⚠ Download failed: {exc}",
                          "App will retry when started.", 0.0)
        import time
        time.sleep(3)
        return False


# ── Public API ────────────────────────────────────────────────────────────────

def ensure_models_ready() -> None:
    """
    If EasyOCR models are not present, show a splash window and download them.
    Blocks until download is complete or user closes the splash.
    """
    if _models_ready():
        return   # fast path — already set up

    splash = _Splash()
    splash.set_status("Checking model cache…", "", 0.02)

    result: list[bool] = []

    def _worker():
        ok = _download_models(splash)
        result.append(ok)
        splash.finish()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    splash.mainloop()   # blocks until finish() or close
    t.join(timeout=5)
