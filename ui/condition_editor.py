"""
ui/condition_editor.py — Redesigned condition editor: clear 3-step flow.

Step 1 → Choose check type  (Image OR OCR)
Step 2 → Configure checks
         Image: add screenshot fragments + confidence threshold
         OCR  : pick region + type the text to find + match mode

Condition data model (saved to step dict)
-----------------------------------------
{
  "type":          "image" | "ocr",
  "images":        ["abs/path.png", ...],
  "img_threshold": 0.85,
  "ocr_checks": [
    {"region": [x,y,w,h] | null, "text": "...", "mode": "contains",
     "_thumb": "abs/preview.png" | null}
  ],
  "timeout":  0,            # 0 = single check, >0 = seconds to keep checking
  "interval": 1.0,          # seconds between checks if timeout > 0
  "logic":    "any" | "all",
  "on_true":  int | null,   # null = next step, -1 = stop
  "on_false": int | null
}
"""
from __future__ import annotations

import io
import tkinter as tk
import tkinter.filedialog as fd
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import customtkinter as ctk
from PIL import Image, ImageGrab, ImageTk

from core.paths import COND_DIR
from ui.region_selector import RegionSelector

# ── Palette ───────────────────────────────────────────────────────────────────
SURFACE   = "#0F1923"
ELEVATED  = "#182433"
CARD      = "#1A2D42"
BORDER    = "#1E3A5A"
BORDER_LO = "#142030"
TEXT_HI   = "#E4EFF8"
TEXT_LO   = "#7A96B0"
TEXT_DIM  = "#3D586A"
ACCENT    = "#1E7FD8"
GREEN     = "#22C55E"
GREEN_DK  = "#166534"
RED       = "#EF4444"
RED_DK    = "#7F1D1D"
GOLD      = "#F59E0B"
PURPLE    = "#A855F7"
PURPLE_DK = "#4A1D96"
ORANGE    = "#F97316"

WIN_W, WIN_H = 640, 600

OCR_MODES = {
    "contains":     "Contains text",
    "not_contains": "Does NOT contain",
    "equals":       "Exact match",
    "regex":        "Regex pattern",
}


def _slug() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]


def _cond_dir() -> Path:
    COND_DIR.mkdir(parents=True, exist_ok=True)
    return COND_DIR


# ─────────────────────────────────────────────────────────────────────────────
# Small reusable widgets
# ─────────────────────────────────────────────────────────────────────────────

class _SectionLabel(ctk.CTkFrame):
    """Horizontal divider with a step number badge and title."""
    def __init__(self, parent, step: str, title: str, color: str = ACCENT):
        super().__init__(parent, fg_color="transparent", height=32)
        self.grid_columnconfigure(1, weight=1)

        badge = ctk.CTkLabel(self, text=f" {step} ",
                             font=("Segoe UI", 10, "bold"),
                             text_color="#FFF", fg_color=color,
                             corner_radius=10, width=28, height=22)
        badge.grid(row=0, column=0, padx=(0, 8))

        ctk.CTkLabel(self, text=title,
                     font=("Segoe UI", 11, "bold"), text_color=color,
                     anchor="w").grid(row=0, column=1, sticky="w")

        line = tk.Frame(self, bg=BORDER_LO, height=1)
        line.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4, 0))


class _ModeCard(ctk.CTkFrame):
    """Selectable mode card with icon + name + description."""
    def __init__(self, parent, icon: str, name: str, desc: str,
                 color: str, var: tk.StringVar, value: str,
                 command: Callable):
        super().__init__(parent, fg_color=CARD, corner_radius=10,
                         border_width=2, border_color=BORDER_LO,
                         cursor="hand2")
        self._var   = var
        self._value = value
        self._color = color
        self._cmd   = command

        ctk.CTkLabel(self, text=icon, font=("Segoe UI", 22),
                     text_color=color).pack(pady=(12, 2))
        ctk.CTkLabel(self, text=name, font=("Segoe UI", 11, "bold"),
                     text_color=TEXT_HI).pack()
        ctk.CTkLabel(self, text=desc, font=("Segoe UI", 9),
                     text_color=TEXT_DIM, wraplength=140,
                     justify="center").pack(padx=8, pady=(2, 12))

        for w in [self] + list(self.winfo_children()):
            w.bind("<Button-1>", self._on_click)

        var.trace_add("write", self._refresh)
        self._refresh()

    def _on_click(self, _=None):
        self._var.set(self._value)
        self._cmd()

    def _refresh(self, *_):
        selected = self._var.get() == self._value
        self.configure(border_color=self._color if selected else BORDER_LO,
                       fg_color=ELEVATED if selected else CARD)


# ─────────────────────────────────────────────────────────────────────────────
# Main dialog
# ─────────────────────────────────────────────────────────────────────────────

class ConditionEditorDialog(ctk.CTkToplevel):
    """Redesigned 3-step condition editor."""

    def __init__(self, parent,
                 step_names: list[str],
                 condition: Optional[dict],
                 on_save: Callable[[Optional[dict]], None]) -> None:
        super().__init__(parent)
        self.title("⚡  Step Condition")
        self.geometry(f"{WIN_W}x{WIN_H}")
        self.resizable(True, True)
        self.configure(fg_color=SURFACE)
        self.attributes("-topmost", True)
        self.grab_set()
        self.minsize(600, 560)

        self._step_names = step_names
        self._on_save    = on_save

        # ── State ──────────────────────────────────────────────────────────────
        self._mode_var          = tk.StringVar(value="image")
        self._logic_var         = tk.StringVar(value="any")
        self._images: list[str] = []
        self._img_thresh_var    = tk.DoubleVar(value=0.85)
        self._ocr_checks: list[dict] = []
        self._on_true_var       = tk.StringVar(value=self._idx_to_label(None))
        self._on_false_var      = tk.StringVar(value=self._idx_to_label(None))
        self._timeout_var       = tk.StringVar(value="0")
        self._interval_var      = tk.StringVar(value="1.0")

        if condition:
            ctype = condition.get("type", "image")
            if ctype in ("image_match", "image_list", "mixed"):
                ctype = "image"
            self._mode_var.set(ctype if ctype in ("image", "ocr") else "image")
            self._images = list(condition.get("images") or [])
            self._img_thresh_var.set(float(condition.get("img_threshold",
                                           condition.get("threshold", 0.85))))
            self._ocr_checks = [dict(c) for c in (condition.get("ocr_checks") or [])]
            self._logic_var.set(condition.get("logic", "any"))
            self._on_true_var.set(self._idx_to_label(condition.get("on_true")))
            self._on_false_var.set(self._idx_to_label(condition.get("on_false")))
            self._timeout_var.set(str(condition.get("timeout", 0)))
            self._interval_var.set(str(condition.get("interval", 1.0)))

        self._build()
        self.bind("<Control-v>", self._img_paste)
        self.bind("<Control-V>", self._img_paste)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _idx_to_label(self, idx) -> str:
        if idx is None:   return "▶  Continue to next step"
        if idx == -1:     return "⏹  Stop plan"
        if 0 <= idx < len(self._step_names):
            return f"→  #{idx+1}  {self._step_names[idx]}"
        return "▶  Continue to next step"

    def _label_to_idx(self, label: str) -> Optional[int]:
        if "Continue" in label: return None
        if "Stop"     in label: return -1
        try:
            token = label.split("#")[1].split()[0]
            n = int(token) - 1
            if 0 <= n < len(self._step_names): return n
        except Exception: pass
        return None

    def _all_labels(self) -> list[str]:
        out = ["▶  Continue to next step", "⏹  Stop plan"]
        for i, name in enumerate(self._step_names):
            out.append(f"→  #{i+1}  {name}")
        return out

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_columnconfigure(0, weight=1)

        # ── Scrollable body ────────────────────────────────────────────────────
        body = ctk.CTkScrollableFrame(self, fg_color=SURFACE,
                                      scrollbar_button_color=BORDER)
        body.grid(row=0, column=0, sticky="nsew", padx=18, pady=(16, 8))
        body.grid_columnconfigure(0, weight=1)
        self._body = body

        r = 0  # row counter

        # ══ STEP 1 — Choose type ══════════════════════════════════════════════
        _SectionLabel(body, "1", "What should be checked?",
                      ACCENT).grid(row=r, column=0, sticky="ew", pady=(0, 10))
        r += 1

        cards_frame = ctk.CTkFrame(body, fg_color="transparent")
        cards_frame.grid(row=r, column=0, sticky="ew", pady=(0, 16))
        cards_frame.grid_columnconfigure((0, 1), weight=1)
        r += 1

        _ModeCard(cards_frame, "🖼", "Image check",
                  "Find a screenshot fragment\nin the game window",
                  ACCENT, self._mode_var, "image",
                  self._on_mode_change).grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        _ModeCard(cards_frame, "🔤", "OCR text check",
                  "Scan for text on screen\nand match a keyword",
                  PURPLE, self._mode_var, "ocr",
                  self._on_mode_change).grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        # ══ STEP 2a — Image section ═══════════════════════════════════════════
        self._img_sec_lbl = _SectionLabel(body, "2", "Add reference images", ACCENT)
        self._img_sec_lbl.grid(row=r, column=0, sticky="ew", pady=(0, 8))
        r += 1

        self._img_help = ctk.CTkLabel(
            body,
            text="📌  Take a small screenshot of a recognisable game state "
                 "(battle screen, dialog, menu).\n"
                 "The runner searches the FULL game window for that fragment.",
            font=("Segoe UI", 9), text_color=TEXT_DIM, justify="left", anchor="w",
        )
        self._img_help.grid(row=r, column=0, sticky="w", pady=(0, 8))
        r += 1

        # Add-frame toolbar
        self._img_toolbar = ctk.CTkFrame(body, fg_color="transparent")
        self._img_toolbar.grid(row=r, column=0, sticky="ew", pady=(0, 8))
        r += 1

        ctk.CTkButton(self._img_toolbar, text="📸  Capture region",
                      height=36, fg_color=ACCENT, hover_color="#1460a8",
                      text_color="#FFF", font=("Segoe UI", 11, "bold"),
                      command=self._img_capture,
                      ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(self._img_toolbar, text="📋  Paste  Ctrl+V",
                      height=36, fg_color=ELEVATED, hover_color=BORDER,
                      text_color=TEXT_LO, border_color=BORDER, border_width=1,
                      font=("Segoe UI", 11), command=self._img_paste,
                      ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(self._img_toolbar, text="📁  Browse file",
                      height=36, fg_color=ELEVATED, hover_color=BORDER,
                      text_color=TEXT_DIM, border_color=BORDER_LO, border_width=1,
                      font=("Segoe UI", 11), command=self._img_browse,
                      ).pack(side="left")

        # Thumbnail strip container
        self._img_strip_wrap = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10,
                                            border_width=1, border_color=BORDER_LO)
        self._img_strip_wrap.grid(row=r, column=0, sticky="ew", pady=(0, 8))
        self._img_strip_wrap.grid_columnconfigure(0, weight=1)
        r += 1

        self._img_strip = ctk.CTkScrollableFrame(
            self._img_strip_wrap, fg_color="transparent",
            height=130, orientation="horizontal",
            scrollbar_button_color=BORDER,
        )
        self._img_strip.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self._refresh_img_strip()

        # Threshold row
        self._thresh_row = ctk.CTkFrame(body, fg_color="transparent")
        self._thresh_row.grid(row=r, column=0, sticky="ew", pady=(0, 16))
        self._thresh_row.grid_columnconfigure(1, weight=1)
        r += 1

        ctk.CTkLabel(self._thresh_row, text="🎯  Confidence:",
                     font=("Segoe UI", 10), text_color=TEXT_LO,
                     ).grid(row=0, column=0, padx=(0, 10))
        ctk.CTkSlider(
            self._thresh_row, from_=0.50, to=0.99, number_of_steps=49,
            variable=self._img_thresh_var,
            fg_color=CARD, progress_color=ACCENT,
            button_color=ACCENT, button_hover_color="#1460a8",
            command=self._on_thresh_change,
        ).grid(row=0, column=1, sticky="ew")
        self._thresh_val_lbl = ctk.CTkLabel(
            self._thresh_row,
            text=f"{self._img_thresh_var.get():.2f}",
            font=("Segoe UI", 11, "bold"), text_color=GOLD, width=40,
        )
        self._thresh_val_lbl.grid(row=0, column=2, padx=(10, 0))
        ctk.CTkLabel(self._thresh_row,
                     text="← loose        strict →",
                     font=("Segoe UI", 8), text_color=TEXT_DIM,
                     ).grid(row=1, column=1)

        # ══ STEP 2b — OCR section ═════════════════════════════════════════════
        self._ocr_sec_lbl = _SectionLabel(body, "2", "Add text checks (OCR)", PURPLE)
        self._ocr_sec_lbl.grid(row=r, column=0, sticky="ew", pady=(0, 8))
        r += 1

        self._ocr_help = ctk.CTkLabel(
            body,
            text="📌  Pick a region where text appears, then type the word/phrase to look for.\n"
                 "Leave region as  🖥 Full screen  to scan the entire game window.",
            font=("Segoe UI", 9), text_color=TEXT_DIM, justify="left", anchor="w",
        )
        self._ocr_help.grid(row=r, column=0, sticky="w", pady=(0, 8))
        r += 1

        self._ocr_toolbar = ctk.CTkFrame(body, fg_color="transparent")
        self._ocr_toolbar.grid(row=r, column=0, sticky="ew", pady=(0, 8))
        r += 1

        ctk.CTkButton(self._ocr_toolbar, text="🖥  Full-screen OCR",
                      height=36, fg_color=PURPLE, hover_color="#7e22ce",
                      text_color="#FFF", font=("Segoe UI", 11, "bold"),
                      command=self._ocr_add_full,
                      ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(self._ocr_toolbar, text="📸  Select region",
                      height=36, fg_color=ELEVATED, hover_color=BORDER,
                      text_color=TEXT_LO, border_color=BORDER, border_width=1,
                      font=("Segoe UI", 11), command=self._ocr_add_region,
                      ).pack(side="left")

        self._ocr_list_frame = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10,
                                            border_width=1, border_color=BORDER_LO)
        self._ocr_list_frame.grid(row=r, column=0, sticky="ew", pady=(0, 8))
        self._ocr_list_frame.grid_columnconfigure(0, weight=1)
        r += 1
        self._refresh_ocr_list()

        # ══ STEP 3 — Polling / Timeout ════════════════════════════════════════
        _SectionLabel(body, "3", "Polling & Timeout (Optional)",
                      GOLD).grid(row=r, column=0, sticky="ew", pady=(0, 10))
        r += 1

        poll_frame = ctk.CTkFrame(body, fg_color="transparent")
        poll_frame.grid(row=r, column=0, sticky="ew", pady=(0, 16))
        r += 1

        ctk.CTkLabel(poll_frame, text="⏳  Timeout (sec):",
                     font=("Segoe UI", 10), text_color=TEXT_LO,
                     ).pack(side="left", padx=(0, 10))
        ctk.CTkEntry(poll_frame, textvariable=self._timeout_var, width=60,
                     font=("Segoe UI", 11), fg_color=CARD, border_color=BORDER,
                     ).pack(side="left")
        ctk.CTkLabel(poll_frame, text="0 = check once",
                     font=("Segoe UI", 8), text_color=TEXT_DIM,
                     ).pack(side="left", padx=(8, 20))

        ctk.CTkLabel(poll_frame, text="⏱  Interval (sec):",
                     font=("Segoe UI", 10), text_color=TEXT_LO,
                     ).pack(side="left", padx=(0, 10))
        ctk.CTkEntry(poll_frame, textvariable=self._interval_var, width=60,
                     font=("Segoe UI", 11), fg_color=CARD, border_color=BORDER,
                     ).pack(side="left")

        # ══ STEP 4 — Branch targets ═══════════════════════════════════════════
        _SectionLabel(body, "4", "What happens next?",
                      GREEN).grid(row=r, column=0, sticky="ew", pady=(0, 12))
        r += 1

        branch_frame = ctk.CTkFrame(body, fg_color=CARD, corner_radius=10,
                                    border_width=1, border_color=BORDER_LO)
        branch_frame.grid(row=r, column=0, sticky="ew", pady=(0, 16))
        branch_frame.grid_columnconfigure(1, weight=1)
        r += 1

        # PASS row
        pass_lbl = ctk.CTkFrame(branch_frame, fg_color="#0D2A1A",
                                corner_radius=6, width=160, height=44)
        pass_lbl.grid(row=0, column=0, padx=(12, 10), pady=(12, 6), sticky="ew")
        pass_lbl.grid_propagate(False)
        pass_lbl.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(pass_lbl, text="🟢  Check PASSES",
                     font=("Segoe UI", 10, "bold"), text_color=GREEN,
                     ).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkOptionMenu(
            branch_frame, values=self._all_labels(),
            variable=self._on_true_var,
            font=("Segoe UI", 11), height=44, fg_color=ELEVATED,
            button_color=BORDER, button_hover_color=CARD,
            text_color=TEXT_HI, dropdown_fg_color=ELEVATED,
            dropdown_text_color=TEXT_HI, dropdown_hover_color=BORDER,
        ).grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=(12, 6))

        # FAIL row
        fail_lbl = ctk.CTkFrame(branch_frame, fg_color="#2A0D0D",
                                corner_radius=6, width=160, height=44)
        fail_lbl.grid(row=1, column=0, padx=(12, 10), pady=(6, 12), sticky="ew")
        fail_lbl.grid_propagate(False)
        ctk.CTkLabel(fail_lbl, text="🔴  Check FAILS",
                     font=("Segoe UI", 10, "bold"), text_color=RED,
                     ).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkOptionMenu(
            branch_frame, values=self._all_labels(),
            variable=self._on_false_var,
            font=("Segoe UI", 11), height=44, fg_color=ELEVATED,
            button_color=BORDER, button_hover_color=CARD,
            text_color=TEXT_HI, dropdown_fg_color=ELEVATED,
            dropdown_text_color=TEXT_HI, dropdown_hover_color=BORDER,
        ).grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=(6, 12))

        # ── Bottom bar ─────────────────────────────────────────────────────────
        bot = ctk.CTkFrame(self, fg_color=ELEVATED,
                           border_width=1, border_color=BORDER_LO, height=64)
        bot.grid(row=1, column=0, sticky="ew")
        bot.grid_propagate(False)
        bot.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(bot, text="✕  Remove condition", height=38, width=170,
                      fg_color="#1A0D0D", hover_color="#3A0D0D",
                      text_color=RED, border_color="#3A1515", border_width=1,
                      font=("Segoe UI", 11), command=self._save_none,
                      ).grid(row=0, column=1, padx=(0, 10), pady=13)
        ctk.CTkButton(bot, text="💾  Save", height=38, width=130,
                      fg_color=GREEN, hover_color=GREEN_DK,
                      text_color="#FFF", font=("Segoe UI", 12, "bold"),
                      command=self._save,
                      ).grid(row=0, column=2, padx=(0, 16), pady=13)

        # Initial visibility
        self._on_mode_change()

    # ── Mode change ───────────────────────────────────────────────────────────

    def _on_mode_change(self) -> None:
        mode    = self._mode_var.get()
        img_on  = mode == "image"
        ocr_on  = mode == "ocr"

        img_widgets = [self._img_sec_lbl, self._img_help, self._img_toolbar,
                       self._img_strip_wrap, self._thresh_row]
        ocr_widgets = [self._ocr_sec_lbl, self._ocr_help, self._ocr_toolbar,
                       self._ocr_list_frame]

        for w in img_widgets:
            if img_on: w.grid()
            else:      w.grid_remove()
        for w in ocr_widgets:
            if ocr_on: w.grid()
            else:      w.grid_remove()

    # ── Image: capture / paste / browse ──────────────────────────────────────

    def _img_capture(self) -> None:
        self.withdraw()
        self.after(150, self._img_open_selector)

    def _img_open_selector(self) -> None:
        def _done(region):
            self.deiconify(); self.attributes("-topmost", True); self.grab_set()
            if region is None: return
            try:
                x, y, w, h = region
                img  = ImageGrab.grab(bbox=(x, y, x+w, y+h))
                path = _cond_dir() / f"img_{_slug()}.png"
                img.save(str(path))
                self._images.append(str(path))
                self._refresh_img_strip()
            except Exception as e:
                self._toast(f"Capture failed: {e}")
        RegionSelector(self, callback=_done,
                       instruction="Drag to select game fragment   •   ESC to cancel")

    def _img_paste(self, _=None) -> None:
        img = self._clipboard_image()
        if img is None:
            self._toast("📋  No image in clipboard — copy a screenshot first")
            return
        try:
            path = _cond_dir() / f"img_{_slug()}.png"
            img.save(str(path))
            self._images.append(str(path))
            self._refresh_img_strip()
            self._toast("✅  Frame added from clipboard")
        except Exception as e:
            self._toast(f"Paste failed: {e}")

    def _img_browse(self) -> None:
        paths = fd.askopenfilenames(
            title="Select image file(s)",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp"), ("All", "*.*")],
            initialdir=str(COND_DIR) if COND_DIR.exists() else ".",
        )
        for p in paths:
            if p and p not in self._images: self._images.append(p)
        self._refresh_img_strip()

    def _refresh_img_strip(self) -> None:
        for w in self._img_strip.winfo_children(): w.destroy()

        if not self._images:
            ctk.CTkLabel(self._img_strip,
                         text="No frames yet",
                         font=("Segoe UI", 10), text_color=TEXT_DIM,
                         ).pack(padx=20, pady=30)
            return

        for i, path in enumerate(self._images):
            self._build_thumb(i, path)

    def _build_thumb(self, idx: int, path: str) -> None:
        card = ctk.CTkFrame(self._img_strip, fg_color=ELEVATED,
                            corner_radius=8, border_width=1, border_color=BORDER_LO)
        card.pack(side="left", padx=5, pady=5)

        W, H = 100, 68
        try:
            img = Image.open(path)
            ow, oh = img.size
            img.thumbnail((W, H), Image.LANCZOS)
            bg = Image.new("RGB", (W, H), "#0B1520")
            bg.paste(img, ((W - img.width)//2, (H - img.height)//2))
            photo = ImageTk.PhotoImage(bg)
            lbl = tk.Label(card, image=photo, bg=ELEVATED)
            lbl.image = photo
            lbl.pack(padx=4, pady=(6, 2))
            size_txt = f"{ow}×{oh}"
        except Exception:
            ctk.CTkLabel(card, text="⚠", font=("Segoe UI", 20),
                         text_color=RED, width=W).pack(padx=4, pady=4)
            size_txt = "?"

        name = Path(path).name
        ctk.CTkLabel(card, text=(name[:13]+"…") if len(name) > 14 else name,
                     font=("Segoe UI", 8), text_color=TEXT_DIM).pack()
        ctk.CTkLabel(card, text=size_txt,
                     font=("Segoe UI", 7), text_color=TEXT_DIM).pack(pady=(0, 2))

        # Prominent delete button
        ctk.CTkButton(
            card, text="🗑  Remove", width=88, height=24,
            fg_color="#3A0D0D", hover_color="#5A1010",
            text_color="#FF6B6B", font=("Segoe UI", 9, "bold"),
            corner_radius=4,
            command=lambda i=idx: self._img_remove(i),
        ).pack(pady=(0, 6))

    def _img_remove(self, idx: int) -> None:
        if 0 <= idx < len(self._images): self._images.pop(idx)
        self._refresh_img_strip()

    def _on_thresh_change(self, val) -> None:
        self._thresh_val_lbl.configure(text=f"{float(val):.2f}")

    # ── OCR checks ────────────────────────────────────────────────────────────

    def _ocr_add_full(self) -> None:
        self._ocr_checks.append({"region": None, "text": "",
                                  "mode": "contains", "_thumb": None})
        self._refresh_ocr_list()

    def _ocr_add_region(self) -> None:
        self.withdraw()
        self.after(150, self._ocr_open_selector)

    def _ocr_open_selector(self) -> None:
        def _done(region):
            self.deiconify(); self.attributes("-topmost", True); self.grab_set()
            if region is None: return
            thumb = None
            try:
                x, y, w, h = region
                img = ImageGrab.grab(bbox=(x, y, x+w, y+h))
                p   = _cond_dir() / f"ocr_prev_{_slug()}.png"
                img.save(str(p)); thumb = str(p)
            except Exception: pass
            self._ocr_checks.append({"region": list(region), "text": "",
                                      "mode": "contains", "_thumb": thumb})
            self._refresh_ocr_list()
        RegionSelector(self, callback=_done,
                       instruction="Drag the text region to read   •   ESC to cancel")

    def _refresh_ocr_list(self) -> None:
        for w in self._ocr_list_frame.winfo_children(): w.destroy()
        if not self._ocr_checks:
            ctk.CTkLabel(self._ocr_list_frame,
                         text="No text checks yet — use the buttons above to add one",
                         font=("Segoe UI", 10), text_color=TEXT_DIM,
                         ).pack(padx=16, pady=14)
            return
        self._ocr_list_frame.grid_columnconfigure(0, weight=1)
        for i, chk in enumerate(self._ocr_checks):
            self._build_ocr_row(i, chk)

    def _build_ocr_row(self, idx: int, chk: dict) -> None:
        row = ctk.CTkFrame(self._ocr_list_frame, fg_color=ELEVATED,
                           corner_radius=8, border_width=1, border_color=BORDER_LO)
        row.grid(row=idx, column=0, sticky="ew", padx=8, pady=5)
        row.grid_columnconfigure(2, weight=1)

        # Region badge
        region = chk.get("region")
        thumb  = chk.get("_thumb")
        PW, PH = 80, 50

        if thumb and Path(thumb).exists():
            try:
                img = Image.open(thumb)
                img.thumbnail((PW, PH), Image.LANCZOS)
                bg = Image.new("RGB", (PW, PH), "#0B1520")
                bg.paste(img, ((PW-img.width)//2, (PH-img.height)//2))
                photo = ImageTk.PhotoImage(bg)
                lbl = tk.Label(row, image=photo, bg=ELEVATED,
                               relief="flat", bd=0)
                lbl.image = photo
                lbl.grid(row=0, column=0, rowspan=2, padx=(10, 8), pady=8)
            except Exception:
                self._ocr_badge(row, region)
        elif region is None:
            badge = ctk.CTkFrame(row, fg_color=PURPLE_DK, corner_radius=6,
                                 width=PW, height=PH)
            badge.grid(row=0, column=0, rowspan=2, padx=(10, 8), pady=8)
            badge.grid_propagate(False)
            ctk.CTkLabel(badge, text="🖥\nFull\nscreen",
                         font=("Segoe UI", 8, "bold"), text_color=PURPLE,
                         ).place(relx=0.5, rely=0.5, anchor="center")
        else:
            self._ocr_badge(row, region)

        # Index
        ctk.CTkLabel(row, text=f"#{idx+1}",
                     font=("Segoe UI", 9), text_color=TEXT_DIM, width=22,
                     ).grid(row=0, column=1, sticky="n", padx=(0, 6), pady=(10, 0))

        # Text entry
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.grid(row=0, column=2, rowspan=2, sticky="nsew", pady=8, padx=(0, 6))
        inner.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(inner, text="Text to find in game:",
                     font=("Segoe UI", 9), text_color=TEXT_DIM, anchor="w",
                     ).grid(row=0, column=0, sticky="w")

        txt_var = tk.StringVar(value=chk.get("text", ""))
        txt_var.trace_add("write",
                          lambda *_, i=idx, v=txt_var: self._ocr_set_text(i, v.get()))
        ctk.CTkEntry(inner, textvariable=txt_var,
                     placeholder_text='e.g.  "Shiny"  or  "Battle"',
                     height=32, font=("Segoe UI", 11),
                     fg_color=CARD, border_color=BORDER,
                     ).grid(row=1, column=0, sticky="ew")

        # Mode selector
        modes = list(OCR_MODES.values())
        cur_mode_lbl = OCR_MODES.get(chk.get("mode", "contains"), modes[0])
        mode_var = tk.StringVar(value=cur_mode_lbl)
        mode_var.trace_add("write",
                           lambda *_, i=idx, v=mode_var: self._ocr_set_mode(i, v.get()))
        ctk.CTkOptionMenu(
            inner, values=modes, variable=mode_var,
            height=28, font=("Segoe UI", 9),
            fg_color=CARD, button_color=BORDER, button_hover_color=ELEVATED,
            text_color=TEXT_LO, dropdown_fg_color=ELEVATED,
            dropdown_text_color=TEXT_LO, dropdown_hover_color=BORDER,
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))

        # Remove
        ctk.CTkButton(row, text="✕", width=28, height=28,
                      fg_color="transparent", hover_color="#3A0D0D",
                      text_color=TEXT_DIM, font=("Segoe UI", 12),
                      command=lambda i=idx: self._ocr_remove(i),
                      ).grid(row=0, column=3, rowspan=2, padx=(0, 8))

    def _ocr_badge(self, parent, region) -> None:
        PW, PH = 80, 50
        badge = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=6,
                             width=PW, height=PH)
        badge.grid(row=0, column=0, rowspan=2, padx=(10, 8), pady=8)
        badge.grid_propagate(False)
        if region:
            x, y, w, h = region
            text = f"📐\n{w}×{h}\n@{x},{y}"
        else:
            text = "🖥 Full"
        ctk.CTkLabel(badge, text=text, font=("Segoe UI", 8),
                     text_color=TEXT_LO).place(relx=0.5, rely=0.5, anchor="center")

    def _ocr_set_text(self, idx: int, val: str) -> None:
        if 0 <= idx < len(self._ocr_checks):
            self._ocr_checks[idx]["text"] = val

    def _ocr_set_mode(self, idx: int, label: str) -> None:
        if 0 <= idx < len(self._ocr_checks):
            for k, v in OCR_MODES.items():
                if v == label:
                    self._ocr_checks[idx]["mode"] = k; break

    def _ocr_remove(self, idx: int) -> None:
        if 0 <= idx < len(self._ocr_checks): self._ocr_checks.pop(idx)
        self._refresh_ocr_list()

    # ── Clipboard ──────────────────────────────────────────────────────────────

    @staticmethod
    def _clipboard_image() -> Optional[Image.Image]:
        try:
            import win32clipboard, win32con
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
                    data = win32clipboard.GetClipboardData(win32con.CF_DIB)
                    hdr  = (b"BM" + (len(data)+14).to_bytes(4,"little")
                            + b"\x00\x00\x00\x00" + (54).to_bytes(4,"little"))
                    return Image.open(io.BytesIO(hdr + data)).convert("RGB")
            finally:
                win32clipboard.CloseClipboard()
        except Exception: pass
        try:
            img = ImageGrab.grabclipboard()
            if isinstance(img, Image.Image): return img.convert("RGB")
        except Exception: pass
        return None

    # ── Toast ──────────────────────────────────────────────────────────────────

    def _toast(self, msg: str) -> None:
        try:
            if not hasattr(self, "_toast_lbl"):
                self._toast_lbl = ctk.CTkLabel(
                    self._body, text="", font=("Segoe UI", 10), text_color=GOLD)
                self._toast_lbl.grid(row=99, column=0, pady=6)
            self._toast_lbl.configure(text=msg)
            self.after(3500, lambda: self._toast_lbl.configure(text="")
                       if hasattr(self, "_toast_lbl") else None)
        except Exception: pass

    # ── Save ───────────────────────────────────────────────────────────────────

    def _save_none(self) -> None:
        self._on_save(None); self.destroy()

    def _save(self) -> None:
        mode = self._mode_var.get()   # "image" | "ocr"

        if mode == "image":
            images     = self._images
            ocr_checks = []
            if not images:
                self._toast("⚠ Add at least one reference image first")
                return
        else:  # ocr
            images     = []
            ocr_checks = [
                {k: v for k, v in c.items() if not k.startswith("_")}
                for c in self._ocr_checks
                if c.get("text", "").strip()
            ]
            if not ocr_checks:
                self._toast("⚠ Add at least one OCR check with a text pattern")
                return

        try:
            timeout_val = float(self._timeout_var.get() or 0)
        except ValueError:
            timeout_val = 0
            
        try:
            interval_val = float(self._interval_var.get() or 1.0)
        except ValueError:
            interval_val = 1.0

        self._on_save({
            "type":          mode,
            "images":        images,
            "img_threshold": round(float(self._img_thresh_var.get()), 2),
            "ocr_checks":    ocr_checks,
            "timeout":       timeout_val,
            "interval":      interval_val,
            "logic":         "any",
            "on_true":       self._label_to_idx(self._on_true_var.get()),
            "on_false":      self._label_to_idx(self._on_false_var.get()),
        })
        self.destroy()
