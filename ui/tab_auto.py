"""
ui/tab_auto.py — Auto Hunt tab  (OCR-based shiny detection).
"""
from __future__ import annotations

from core.debug_log import dlog


from pathlib import Path
from tkinter import messagebox
from typing import TYPE_CHECKING, Optional

import customtkinter as ctk

from core.recorder import MovementRecorder
from ui.ocr_overlay import OcrOverlay

if TYPE_CHECKING:
    from ui.app import App

DATA_DIR = Path(__file__).parent.parent / "data" / "movements"

from ui.theme import (
    BG, SURFACE, ELEVATED, BORDER,
    TEXT_HI, TEXT_MD, TEXT_LO, TEXT_DIM,
    ACCENT, ACCENT_H, RECORD,
    PLAY_BG, PLAY_BD, PLAY_TXT, PLAY_DIM,
)

SHINY_COLOR  = "#FFD700"
SHINY_BG     = "#2A2000"
SHINY_BORDER = "#6B5500"
HUNT_START   = "#0E4D2E"
HUNT_START_H = "#155C38"
HUNT_STOP    = "#4D1010"
HUNT_STOP_H  = "#6B1515"
WARN_COLOR   = "#D4A017"
WARN_BG      = "#1C1A0E"
WARN_BORDER  = "#4A4500"


class AutoTab(ctk.CTkFrame):
    """Two-panel auto-hunt interface: setup (left) | status + log (right)."""

    def __init__(self, parent, app: "App") -> None:
        super().__init__(parent, fg_color="transparent", corner_radius=0)
        self.app = app

        self._log_row     = 0
        self._timer_job:  Optional[str] = None
        self._thumb_img   = None       # PhotoImage reference (prevent GC)
        self._selected_seq: Optional[dict] = None

        # Wire callbacks
        app.auto_runner.on_loop    = self._cb_loop
        app.auto_runner.on_shiny   = self._cb_shiny
        app.auto_runner.on_stopped = self._cb_stopped
        app.auto_runner.on_started = self._cb_started

        self._build()
        self._refresh_seq_list()
        self._update_ocr_status()

        # If a region was restored from settings, update the label & thumbnail
        if app.detector.has_ocr_region():
            region = app.detector.get_ocr_region()
            if region:
                x, y, w, h = region
                self.region_info.configure(
                    text=f"\u25cf Region: ({x}, {y})  {w}\u00d7{h} px  \u2014 restored",
                    text_color=PLAY_TXT,
                )
                self._refresh_region_thumb()

        # Preload EasyOCR model in background so it's ready when user clicks Test
        import threading as _t
        from core.detector import preload_easyocr, _EASYOCR_AVAILABLE
        if _EASYOCR_AVAILABLE:
            _t.Thread(target=self._preload_easyocr_bg, daemon=True).start()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=0, minsize=268)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_left()
        self._build_right()

    # ── LEFT PANEL ────────────────────────────────────────────────────────────

    def _build_left(self) -> None:
        left = ctk.CTkScrollableFrame(
            self, fg_color=SURFACE, corner_radius=12,
            scrollbar_button_color=ELEVATED,
            scrollbar_button_hover_color=BORDER,
        )
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left.grid_columnconfigure(0, weight=1)
        self._left = left

        # ── OCR engine status banner ──────────────────────────────────────────
        self.tess_banner = ctk.CTkFrame(left, fg_color=BG, corner_radius=8)
        self.tess_banner.grid(row=0, column=0, padx=10, pady=(12, 4), sticky="ew")
        self.tess_icon = ctk.CTkLabel(
            self.tess_banner, text="⏳", font=("Segoe UI", 18), text_color=TEXT_DIM)
        self.tess_icon.pack(side="left", padx=(10, 6), pady=8)
        tess_text = ctk.CTkFrame(self.tess_banner, fg_color="transparent")
        tess_text.pack(side="left", fill="x", expand=True, pady=8)
        self.tess_status_lbl = ctk.CTkLabel(
            tess_text, text="Loading OCR engine…",
            font=("Segoe UI", 10, "bold"), text_color=TEXT_LO, anchor="w")
        self.tess_status_lbl.pack(anchor="w")
        self.tess_hint_lbl = ctk.CTkLabel(
            tess_text, text="",
            font=("Segoe UI", 9), text_color=TEXT_DIM, anchor="w")
        self.tess_hint_lbl.pack(anchor="w")

        # ── Section: sequence ─────────────────────────────────────────────────
        _section(left, "MOVEMENT SEQUENCE", row=1)

        seq_card = ctk.CTkFrame(left, fg_color=BG, corner_radius=9)
        seq_card.grid(row=2, column=0, padx=10, pady=(0, 6), sticky="ew")
        seq_card.grid_columnconfigure(0, weight=1)

        self.seq_var = ctk.StringVar(value="— Select —")
        self.seq_menu = ctk.CTkOptionMenu(
            seq_card, values=["— Select —"],
            variable=self.seq_var,
            font=("Segoe UI", 11),
            fg_color=ELEVATED, button_color=BORDER,
            button_hover_color=TEXT_DIM, text_color=TEXT_MD,
            dropdown_fg_color=SURFACE, dropdown_text_color=TEXT_MD,
            dropdown_hover_color=ELEVATED,
            corner_radius=7, dynamic_resizing=False,
            command=self._on_seq_selected,
        )
        self.seq_menu.grid(row=0, column=0, padx=(10, 4), pady=10, sticky="ew")
        ctk.CTkButton(
            seq_card, text="🔄",
            font=("Segoe UI", 12),
            fg_color=ELEVATED, hover_color=BORDER,
            text_color=TEXT_LO, width=30, height=30, corner_radius=7,
            command=self._refresh_seq_list,
        ).grid(row=0, column=1, padx=(0, 10), pady=10)

        # ── Section: OCR region ───────────────────────────────────────────────
        _section(left, "OCR REGION — NAME BARS", row=3)

        ocr_card = ctk.CTkFrame(left, fg_color=BG, corner_radius=9)
        ocr_card.grid(row=4, column=0, padx=10, pady=(0, 6), sticky="ew")
        ocr_card.grid_columnconfigure(0, weight=1)

        # Thumbnail preview of selected region
        self.region_thumb = ctk.CTkLabel(
            ocr_card,
            text="No region selected",
            font=("Segoe UI", 10, "italic"),
            text_color=TEXT_DIM,
            fg_color=ELEVATED, corner_radius=8,
            width=224, height=90,
        )
        self.region_thumb.grid(row=0, column=0, padx=10, pady=(10, 6), sticky="ew")

        # Region info
        self.region_info = ctk.CTkLabel(
            ocr_card, text="● No region selected",
            font=("Segoe UI", 9), text_color=TEXT_DIM)
        self.region_info.grid(row=1, column=0, padx=10, pady=(0, 4))

        # Buttons
        btn_row = ctk.CTkFrame(ocr_card, fg_color="transparent")
        btn_row.grid(row=2, column=0, padx=10, pady=(0, 4), sticky="ew")
        btn_row.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(
            btn_row, text="📍 Select Region",
            font=("Segoe UI", 11),
            fg_color=ELEVATED, hover_color=BORDER,
            text_color=TEXT_MD, border_color=BORDER, border_width=1,
            height=34, corner_radius=8,
            command=self._select_region,
        ).grid(row=0, column=0, padx=(0, 3), sticky="ew")

        ctk.CTkButton(
            btn_row, text="🔬 Test OCR",
            font=("Segoe UI", 11),
            fg_color=ELEVATED, hover_color=BORDER,
            text_color=TEXT_MD, border_color=BORDER, border_width=1,
            height=34, corner_radius=8,
            command=self._test_ocr,
        ).grid(row=0, column=1, padx=(3, 0), sticky="ew")

        ctk.CTkButton(
            ocr_card, text="✕  Clear Region",
            font=("Segoe UI", 9),
            fg_color="transparent", hover_color="#3D1010",
            text_color=TEXT_DIM, border_color=BORDER, border_width=1,
            height=26, corner_radius=6,
            command=self._clear_region,
        ).grid(row=3, column=0, padx=10, pady=(0, 10), sticky="ew")

        # ── Section: check timing ─────────────────────────────────────────────
        _section(left, "CHECK TIMING", row=5)

        timing_card = ctk.CTkFrame(left, fg_color=BG, corner_radius=9)
        timing_card.grid(row=6, column=0, padx=10, pady=(0, 6), sticky="ew")
        timing_card.grid_columnconfigure(0, weight=1)

        trow = ctk.CTkFrame(timing_card, fg_color="transparent")
        trow.grid(row=0, column=0, padx=12, pady=(12, 2), sticky="ew")
        trow.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(trow, text="Scan name bars after:",
                     font=("Segoe UI", 10), text_color=TEXT_LO).grid(
                         row=0, column=0, sticky="w")
        self.delay_val_lbl = ctk.CTkLabel(
            trow, text="3.0s",
            font=("Consolas", 13, "bold"), text_color=ACCENT)
        self.delay_val_lbl.grid(row=0, column=1)

        self.delay_slider = ctk.CTkSlider(
            timing_card, from_=0.5, to=10.0, number_of_steps=95,
            fg_color=BORDER, progress_color=ACCENT,
            button_color=ACCENT, button_hover_color=ACCENT_H,
            command=self._on_delay_change,
        )
        self.delay_slider.set(3.0)
        self.delay_slider.grid(row=1, column=0, padx=12, pady=(2, 4), sticky="ew")

        ctk.CTkLabel(
            timing_card,
            text="Set to when the battle screen is fully loaded.\n"
                 "The sequence continues after the check.",
            font=("Segoe UI", 9), text_color=TEXT_DIM, justify="left",
        ).grid(row=2, column=0, padx=12, pady=(0, 12), sticky="w")

        # ── Start / Stop ──────────────────────────────────────────────────────
        self.start_btn = ctk.CTkButton(
            left, text="▶  Start Auto Hunt",
            font=("Segoe UI", 13, "bold"),
            fg_color=HUNT_START, hover_color=HUNT_START_H,
            text_color=PLAY_TXT, border_color=PLAY_BD, border_width=1,
            height=44, corner_radius=10,
            command=self._toggle_hunt,
        )
        self.start_btn.grid(row=7, column=0, padx=10, pady=(6, 14), sticky="ew")

    # ── RIGHT PANEL ───────────────────────────────────────────────────────────

    def _build_right(self) -> None:
        right = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=12)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)

        # ── Status card ───────────────────────────────────────────────────────
        stat = ctk.CTkFrame(right, fg_color=BG, corner_radius=10)
        stat.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        stat.grid_columnconfigure(1, weight=1)

        self.status_icon = ctk.CTkLabel(
            stat, text="●",
            font=("Segoe UI", 32), text_color=TEXT_DIM)
        self.status_icon.grid(row=0, column=0, rowspan=2, padx=(16, 10), pady=16)

        self.status_lbl = ctk.CTkLabel(
            stat, text="IDLE",
            font=("Segoe UI", 18, "bold"), text_color=TEXT_LO, anchor="w")
        self.status_lbl.grid(row=0, column=1, padx=0, pady=(16, 2), sticky="w")

        self.status_sub = ctk.CTkLabel(
            stat, text="Configure sequence and OCR region to begin",
            font=("Segoe UI", 10), text_color=TEXT_DIM, anchor="w")
        self.status_sub.grid(row=1, column=1, padx=0, pady=(0, 16), sticky="w")

        # KPI row
        kpi = ctk.CTkFrame(stat, fg_color="transparent")
        kpi.grid(row=2, column=0, columnspan=2, padx=14, pady=(0, 14), sticky="ew")
        kpi.grid_columnconfigure((0, 1), weight=1)

        self.var_encounters = ctk.StringVar(value="0")
        self.var_elapsed    = ctk.StringVar(value="00:00:00")
        _mini_kpi(kpi, self.var_encounters, "Encounters", col=0)
        _mini_kpi(kpi, self.var_elapsed,    "Elapsed",    col=1)

        # ── OCR result card ───────────────────────────────────────────────────
        self.ocr_result_card = ctk.CTkFrame(right, fg_color=ELEVATED, corner_radius=9)
        self.ocr_result_card.grid(row=1, column=0, padx=16, pady=(0, 8), sticky="ew")
        self.ocr_result_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self.ocr_result_card, text="Last OCR:",
            font=("Segoe UI", 9, "bold"), text_color=TEXT_DIM,
        ).grid(row=0, column=0, padx=(12, 6), pady=8, sticky="w")

        self.ocr_result_lbl = ctk.CTkLabel(
            self.ocr_result_card,
            text="—",
            font=("Consolas", 10), text_color=TEXT_LO,
            anchor="w", justify="left", wraplength=380,
        )
        self.ocr_result_lbl.grid(row=0, column=1, padx=(0, 12), pady=8, sticky="ew")

        # ── Auto log ──────────────────────────────────────────────────────────
        log_hdr = ctk.CTkFrame(right, fg_color="transparent")
        log_hdr.grid(row=1, column=0, padx=16, pady=(0, 4), sticky="ew")
        log_hdr.grid_columnconfigure(0, weight=1)

        # (log_hdr is overwritten below — reuse row 1 for log header via separate frame)
        log_bar = ctk.CTkFrame(right, fg_color="transparent")
        log_bar.grid(row=1, column=0, padx=16, pady=(54, 4), sticky="ew")
        log_bar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(log_bar, text="AUTO LOG",
                     font=("Segoe UI", 9, "bold"), text_color=TEXT_LO).pack(
                         side="left", anchor="w")
        ctk.CTkButton(
            log_bar, text="Clear",
            font=("Segoe UI", 9),
            fg_color="transparent", hover_color=ELEVATED,
            text_color=TEXT_DIM, border_color=BORDER, border_width=1,
            height=22, width=52, corner_radius=5,
            command=self._clear_log,
        ).pack(side="right")

        self.log_scroll = ctk.CTkScrollableFrame(
            right, fg_color=BG, corner_radius=10,
            scrollbar_button_color=ELEVATED,
            scrollbar_button_hover_color=BORDER,
        )
        self.log_scroll.grid(row=2, column=0, padx=16, pady=(0, 16), sticky="nsew")
        self.log_scroll.grid_columnconfigure(0, weight=1)

        self._log_empty = ctk.CTkLabel(
            self.log_scroll,
            text="No loops run yet.\nStart the hunt to see OCR results here.",
            font=("Segoe UI", 11), text_color=TEXT_DIM, justify="center",
        )
        self._log_empty.grid(row=0, column=0, pady=60)

    # ── OCR engine status ─────────────────────────────────────────────────────

    def _preload_easyocr_bg(self) -> None:
        """Daemon thread: loads EasyOCR model weights, then refreshes status."""
        from core.detector import preload_easyocr
        preload_easyocr()
        self.after(0, self._update_ocr_status)

    def _update_ocr_status(self) -> None:
        from core.detector import _EASYOCR_AVAILABLE, _EASYOCR_READY, _TESS
        if _EASYOCR_AVAILABLE and _EASYOCR_READY:
            self.tess_icon.configure(text="🧠", text_color="#58D6A8")
            self.tess_status_lbl.configure(
                text="EasyOCR ready  (AI neural-network)", text_color="#58D6A8")
            self.tess_hint_lbl.configure(
                text="High accuracy — handles game fonts automatically",
                text_color="#2EA87A")
        elif _EASYOCR_AVAILABLE and not _EASYOCR_READY:
            self.tess_icon.configure(text="⏳", text_color=TEXT_DIM)
            self.tess_status_lbl.configure(
                text="EasyOCR loading model…", text_color=TEXT_DIM)
            self.tess_hint_lbl.configure(
                text="First-time load: ~5 sec  (cached after that)",
                text_color=TEXT_DIM)
        elif _TESS:
            self.tess_icon.configure(text="✓", text_color=PLAY_TXT)
            self.tess_status_lbl.configure(
                text="Tesseract OCR ready  (fallback mode)", text_color=PLAY_TXT)
            self.tess_hint_lbl.configure(
                text="pip install easyocr  for better accuracy",
                text_color=TEXT_DIM)
        else:
            self.tess_icon.configure(text="⚠", text_color=WARN_COLOR)
            self.tess_status_lbl.configure(
                text="No OCR engine found", text_color=WARN_COLOR)
            self.tess_hint_lbl.configure(
                text="pip install easyocr",
                text_color=TEXT_DIM)


    # ── Sequence ──────────────────────────────────────────────────────────────

    def _refresh_seq_list(self) -> None:
        seqs = MovementRecorder.load_all(DATA_DIR)
        names = [s["name"] for s in seqs]
        values = ["— Select —"] + names
        self.seq_menu.configure(values=values)
        if names:
            self.seq_var.set(names[0])
            self._on_seq_selected(names[0])
        else:
            self.seq_var.set("— Select —")
            self._selected_seq = None

    def _on_seq_selected(self, name: str) -> None:
        if name == "— Select —":
            self._selected_seq = None
            return
        for s in MovementRecorder.load_all(DATA_DIR):
            if s["name"] == name:
                self._selected_seq = s
                return
        self._selected_seq = None

    # ── OCR region selection ──────────────────────────────────────────────────

    def _select_region(self) -> None:
        from ui.region_selector import RegionSelector
        # Hide app window briefly so user can see the game
        self.app.iconify()
        self.after(400, self._open_selector)

    def _open_selector(self) -> None:
        from ui.region_selector import RegionSelector
        RegionSelector(
            self.app,
            callback=self._on_region_selected,
            instruction="Drag to select the Pokémon name bar area   •   ESC to cancel",
        )

    def _on_region_selected(self, region) -> None:
        self.app.deiconify()
        if region is None:
            return
        x, y, w, h = region
        self.app.detector.set_ocr_region(x, y, w, h)
        # Persist immediately so it survives restarts
        from core import settings as cfg
        data = cfg.load()
        data["ocr_region"] = [x, y, w, h]
        cfg.save(data)
        self.region_info.configure(
            text=f"● Region: ({x}, {y})  {w}×{h} px",
            text_color=PLAY_TXT,
        )
        self._refresh_region_thumb()

    def _refresh_region_thumb(self) -> None:
        thumb = self.app.detector.get_ocr_preview(size=(222, 88))
        if thumb is None:
            return
        try:
            ctk_img = ctk.CTkImage(light_image=thumb, dark_image=thumb,
                                    size=(min(222, thumb.width), min(88, thumb.height)))
            self._thumb_img = ctk_img
            self.region_thumb.configure(image=ctk_img, text="")
        except Exception:
            self.region_thumb.configure(
                text="Region captured ✓", text_color=PLAY_TXT)

    def _clear_region(self) -> None:
        self.app.detector.clear_ocr_region()
        # Clear from persisted settings too
        from core import settings as cfg
        data = cfg.load()
        data["ocr_region"] = None
        cfg.save(data)
        self.region_thumb.configure(image=None, text="No region selected")
        self._thumb_img = None
        self.region_info.configure(text="● No region selected", text_color=TEXT_DIM)

    def _test_ocr(self) -> None:
        if not self.app.detector.has_ocr_region():
            messagebox.showwarning(
                "No Region", "Select an OCR region first.", parent=self)
            return

        from core.detector import _EASYOCR_AVAILABLE, _EASYOCR_READY, _TESS
        if not _EASYOCR_AVAILABLE and not _TESS:
            messagebox.showerror(
                "No OCR Engine",
                "Install EasyOCR:\n  pip install easyocr\n\n"
                "Or Tesseract from:\n  github.com/UB-Mannheim/tesseract/wiki",
                parent=self,
            )
            return
        if _EASYOCR_AVAILABLE and not _EASYOCR_READY:
            messagebox.showinfo(
                "EasyOCR Loading",
                "AI model is still loading (takes ~5 sec on first run).\n"
                "Please wait a moment then try again.",
                parent=self,
            )
            return

        # Minimize app so the game window is exposed, then capture
        self.app.iconify()
        self.app.after(350, self._do_test_ocr)

    def _do_test_ocr(self) -> None:
        """Run after app is minimized — game screen is now visible."""
        from core.detector import _EASYOCR_AVAILABLE, _EASYOCR_READY, _TESS

        is_shiny, text = self.app.detector.test_ocr()

        # Restore app window
        self.app.deiconify()
        self.app.lift()

        color = SHINY_COLOR if is_shiny else PLAY_TXT
        self.ocr_result_lbl.configure(text=text or "(empty)", text_color=color)

        # Show overlay
        region = self.app.detector.get_ocr_region()
        OcrOverlay.show(self.app, text=text or "(no text)", region=region)

        # When using Tesseract open debug image
        if not (_EASYOCR_AVAILABLE and _EASYOCR_READY):
            proc_img = self.app.detector.get_preprocessed_preview(size=(800, 400))
            if proc_img:
                try:
                    import tempfile, os
                    tmp = tempfile.NamedTemporaryFile(
                        suffix="_ocr_debug.png", delete=False,
                        dir=tempfile.gettempdir(),
                    )
                    proc_img.save(tmp.name)
                    tmp.close()
                    os.startfile(tmp.name)
                except Exception:
                    pass

        engine = "EasyOCR (AI)" if (_EASYOCR_AVAILABLE and _EASYOCR_READY) else "Tesseract"
        status = "\U0001f389 SHINY DETECTED!" if is_shiny else "\u2713 Normal (no Shiny text found)"
        msg = (
            f"{status}\n\n"
            f"Engine: {engine}\n\n"
            f"Detected text:\n{text or '(empty)'}"
        )
        messagebox.showinfo("OCR Test Result", msg, parent=self)


    def _on_delay_change(self, val: float) -> None:
        self.delay_val_lbl.configure(text=f"{val:.1f}s")

    # ── Hunt control ──────────────────────────────────────────────────────────

    def _toggle_hunt(self) -> None:
        if self.app.auto_runner.is_running:
            self.app.auto_runner.stop()
        else:
            self._start_hunt()

    def _start_hunt(self) -> None:
        from core.detector import _EASYOCR_AVAILABLE, _EASYOCR_READY, _TESS
        if not self._selected_seq:
            messagebox.showwarning("No Sequence", "Select a movement sequence first.", parent=self)
            return
        if not self.app.detector.has_ocr_region():
            messagebox.showwarning(
                "No OCR Region",
                "Select the name bar region first.\n\n"
                "1. Open PokeMMO and trigger an encounter so name bars are visible\n"
                "2. Click  \U0001f4cd Select Region  and drag over the name bars\n"
                "3. Start the hunt",
                parent=self,
            )
            return

        # Check OCR engine availability
        has_engine = (_EASYOCR_AVAILABLE and _EASYOCR_READY) or _TESS
        if _EASYOCR_AVAILABLE and not _EASYOCR_READY:
            if not messagebox.askyesno(
                "EasyOCR Still Loading",
                "The AI OCR model is still loading.\n"
                "Shiny detection may not work for the first encounter.\n\n"
                "Start anyway?",
                parent=self,
            ):
                return
        elif not has_engine:
            if not messagebox.askyesno(
                "No OCR Engine",
                "No OCR engine found — shiny detection won't work!\n\n"
                "Run:  pip install easyocr\n\n"
                "Continue anyway (pixel-diff fallback)?",
                parent=self,
            ):
                return

        delay = round(self.delay_slider.get(), 1)
        self.app.auto_runner.start(
            self._selected_seq,
            self.app.target_hwnd,
            ocr_check_delay=delay,
        )

    # ── AutoRunner callbacks ──────────────────────────────────────────────────

    def _cb_started(self) -> None:
        self.after(0, self._on_started_ui)

    def _cb_loop(self, loop_n: int, info: dict) -> None:
        self.after(0, self._on_loop_ui, loop_n, info)

    def _cb_shiny(self, loop_n: int, info: dict) -> None:
        self.after(0, self._on_shiny_ui, loop_n, info)

    def _cb_stopped(self) -> None:
        self.after(0, self._on_stopped_ui)

    # ── Main-thread UI updates ────────────────────────────────────────────────

    def _on_started_ui(self) -> None:
        self.start_btn.configure(
            text="■  Stop Hunt",
            fg_color=HUNT_STOP, hover_color=HUNT_STOP_H,
            text_color=RECORD, border_color="#7B1010",
        )
        self.status_icon.configure(text_color=PLAY_TXT)
        self.status_lbl.configure(text="RUNNING", text_color=PLAY_TXT)
        self.status_sub.configure(text="Looping movement sequence + scanning…")
        self.var_encounters.set("0")
        self.var_elapsed.set("00:00:00")
        self._start_timer()
        self.app.show_toast("▶  Auto Hunt started", PLAY_TXT)

    def _on_loop_ui(self, loop_n: int, info: dict) -> None:
        self.var_encounters.set(str(loop_n))
        text   = info.get("text") or ""
        sim    = info.get("similarity")
        method = info.get("method", "ocr")

        dlog(f"[loop_ui] loop={loop_n} method={method} text={repr(text[:40])}")

        if method in ("ocr", "ocr_inline"):
            display = text.replace("\n", "  ").strip()[:60] or "(no text)"
            self.status_sub.configure(text=f"Loop #{loop_n} \u2014 scanning\u2026")
            self.ocr_result_lbl.configure(text=display, text_color=PLAY_TXT)
            self._add_ocr_log_entry(loop_n, display, is_shiny=False)
            # Toast (guaranteed visible) — shows OCR text at top of screen
            self.app.show_toast(f"\U0001f4f8 OCR #{loop_n}: {display[:50]}", PLAY_TXT)
            # Floating overlay (bottom-right corner)
            region = self.app.detector.get_ocr_region()
            dlog(f"[loop_ui] calling OcrOverlay.show region={region}")
            OcrOverlay.show(self.app, text=text or "(no text)", region=region)
        else:
            self.status_sub.configure(
                text=f"Loop #{loop_n} \u2014 similarity {sim:.1f}%")
            self._add_pixel_log_entry(loop_n, sim or 0.0)

    def _on_shiny_ui(self, loop_n: int, info: dict) -> None:
        self.var_encounters.set(str(loop_n))
        text = info.get("text") or ""
        display = text.replace("\n", "  ").strip()[:80] or "(shiny detected)"

        self.status_icon.configure(text_color=SHINY_COLOR)
        self.status_lbl.configure(text="\U0001f389  SHINY DETECTED!", text_color=SHINY_COLOR)
        self.status_sub.configure(
            text=f"Loop #{loop_n}  \u00b7  {self.app.auto_runner.elapsed_str()}")
        self.ocr_result_lbl.configure(text=display, text_color=SHINY_COLOR)

        if info.get("method") in ("ocr", "ocr_inline"):
            self._add_ocr_log_entry(loop_n, display, is_shiny=True)
        else:
            self._add_pixel_log_entry(loop_n, info.get("similarity") or 0.0, is_shiny=True)

        self._reset_hunt_btn()
        self._stop_timer()
        self.app.show_toast("\U0001f389  SHINY FOUND! Hunt stopped.", SHINY_COLOR)

    def _on_stopped_ui(self) -> None:
        self.status_icon.configure(text_color=TEXT_DIM)
        self.status_lbl.configure(text="STOPPED", text_color=TEXT_LO)
        self.status_sub.configure(
            text=f"Manually stopped after {self.var_encounters.get()} encounters")
        self._reset_hunt_btn()
        self._stop_timer()
        self.app.show_toast("■  Auto Hunt stopped", TEXT_MD)

    def _reset_hunt_btn(self) -> None:
        self.start_btn.configure(
            text="▶  Start Auto Hunt",
            fg_color=HUNT_START, hover_color=HUNT_START_H,
            text_color=PLAY_TXT, border_color=PLAY_BD,
        )

    # ── Timer ─────────────────────────────────────────────────────────────────

    def _start_timer(self) -> None:
        self._stop_timer()
        self._tick_timer()

    def _tick_timer(self) -> None:
        if not self.app.auto_runner.is_running:
            return
        self.var_elapsed.set(self.app.auto_runner.elapsed_str())
        self._timer_job = self.after(1000, self._tick_timer)

    def _stop_timer(self) -> None:
        if self._timer_job:
            self.after_cancel(self._timer_job)
            self._timer_job = None

    # ── Log entries ───────────────────────────────────────────────────────────

    def _add_ocr_log_entry(self, loop_n: int, text: str, is_shiny: bool) -> None:
        if self._log_empty and self._log_empty.winfo_exists():
            self._log_empty.grid_remove()

        row = self._log_row
        self._log_row += 1

        if is_shiny:
            bg, bd, result_txt, result_clr = SHINY_BG, SHINY_BORDER, "🎉 SHINY!", SHINY_COLOR
        else:
            bg, bd, result_txt, result_clr = ELEVATED, BORDER, "✓ normal", PLAY_TXT

        entry = ctk.CTkFrame(self.log_scroll, fg_color=bg, corner_radius=6,
                              border_width=1, border_color=bd)
        entry.grid(row=row, column=0, padx=6, pady=2, sticky="ew")
        entry.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(entry, text=f"#{loop_n}",
                     font=("Consolas", 10), text_color=TEXT_DIM,
                     width=38, anchor="e").grid(row=0, column=0, padx=(10, 6), pady=7)

        ctk.CTkLabel(entry, text=result_txt,
                     font=("Segoe UI", 10, "bold"),
                     text_color=result_clr,
                     width=70).grid(row=0, column=1, padx=(0, 6), pady=7)

        ctk.CTkLabel(entry, text=text,
                     font=("Consolas", 9), text_color=TEXT_DIM,
                     anchor="w", justify="left").grid(
                         row=0, column=2, padx=(0, 10), pady=7, sticky="w")

        self.log_scroll._parent_canvas.yview_moveto(1.0)

    def _add_pixel_log_entry(self, loop_n: int, similarity: float,
                              is_shiny: bool = False) -> None:
        if self._log_empty and self._log_empty.winfo_exists():
            self._log_empty.grid_remove()

        row = self._log_row
        self._log_row += 1

        if is_shiny or similarity < 75:
            bg, bd, sim_clr = SHINY_BG, SHINY_BORDER, SHINY_COLOR
            result_txt, result_clr = "🎉 SHINY!", SHINY_COLOR
        elif similarity < 90:
            bg, bd, sim_clr = WARN_BG, WARN_BORDER, WARN_COLOR
            result_txt, result_clr = "continue", WARN_COLOR
        else:
            bg, bd, sim_clr = ELEVATED, BORDER, PLAY_TXT
            result_txt, result_clr = "✓ normal", PLAY_TXT

        entry = ctk.CTkFrame(self.log_scroll, fg_color=bg, corner_radius=6,
                              border_width=1, border_color=bd)
        entry.grid(row=row, column=0, padx=6, pady=2, sticky="ew")
        entry.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(entry, text=f"#{loop_n}",
                     font=("Consolas", 10), text_color=TEXT_DIM,
                     width=38, anchor="e").grid(row=0, column=0, padx=(10, 6), pady=7)

        ctk.CTkLabel(entry, text=f"{similarity:.1f}%",
                     font=("Consolas", 12, "bold"),
                     text_color=sim_clr).grid(row=0, column=1, padx=(0, 6), pady=7)

        ctk.CTkLabel(entry, text="→",
                     font=("Segoe UI", 10), text_color=TEXT_DIM).grid(
                         row=0, column=2, padx=(0, 6), pady=7, sticky="w")

        ctk.CTkLabel(entry, text=result_txt,
                     font=("Segoe UI", 10, "bold"),
                     text_color=result_clr, anchor="w").grid(
                         row=0, column=3, padx=(0, 12), pady=7)

        self.log_scroll._parent_canvas.yview_moveto(1.0)

    def _clear_log(self) -> None:
        for w in self.log_scroll.winfo_children():
            w.destroy()
        self._log_row = 0
        self._log_empty = ctk.CTkLabel(
            self.log_scroll,
            text="No loops run yet.\nStart the hunt to see OCR results here.",
            font=("Segoe UI", 11), text_color=TEXT_DIM, justify="center",
        )
        self._log_empty.grid(row=0, column=0, pady=60)

    # ── Public ────────────────────────────────────────────────────────────────

    def refresh_sequences(self) -> None:
        self._refresh_seq_list()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _section(parent, title: str, row: int) -> None:
    ctk.CTkLabel(parent, text=title,
                 font=("Segoe UI", 9, "bold"), text_color=TEXT_LO).grid(
                     row=row, column=0, padx=14, pady=(12, 2), sticky="w")


def _mini_kpi(parent, var: ctk.StringVar, label: str, col: int) -> None:
    f = ctk.CTkFrame(parent, fg_color=ELEVATED, corner_radius=8)
    f.grid(row=0, column=col, padx=3, sticky="ew")
    ctk.CTkLabel(f, textvariable=var,
                 font=("Consolas", 18, "bold"), text_color=TEXT_HI).pack(pady=(8, 1))
    ctk.CTkLabel(f, text=label,
                 font=("Segoe UI", 9), text_color=TEXT_LO).pack(pady=(0, 8))
