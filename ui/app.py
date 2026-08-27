"""
ui/app.py — Main application window (tab-based layout).

Layout:
  ┌──────────────────────────────────────────────────────────┐
  │  ✦ PokéShiny Auto Hunter                     [⚙ Settings]│
  ├──────────────────────────────────────────────────────────┤
  │  Target: [PokeMMO ▼]  [🔄]   ● IDLE          (status)  │
  ├──────────────────────────────────────────────────────────┤
  │  [🎬 Movement]   [🎯 Plan]                               │
  ├──────────────────────────────────────────────────────────┤
  │                                                          │
  │  Active tab content                                      │
  │                                                          │
  └──────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

from tkinter import messagebox
from typing import Optional

import customtkinter as ctk

from core import settings as cfg
from core.recorder import MovementRecorder
from core.player import MovementPlayer
from core.detector import ScreenDetector
from core.auto_runner import AutoRunner
from core.settings import key_display, parse_key

from ui.theme import (
    BG, SURFACE, ELEVATED, BORDER,
    TEXT_HI, TEXT_MD, TEXT_LO, TEXT_DIM,
    ACCENT, ACCENT_H, RECORD, RECORD_D,
    PLAY_TXT,
)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ═══════════════════════════════════════════════════════════════════════════════
# Toast overlay
# ═══════════════════════════════════════════════════════════════════════════════

class Toast(ctk.CTkToplevel):
    _W, _H = 320, 64

    def __init__(self, master, text: str, color: str) -> None:
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.0)
        self.configure(fg_color=BORDER)

        sw = self.winfo_screenwidth()
        self.geometry(f"{self._W}x{self._H}+{(sw - self._W) // 2}+28")

        frame = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=14,
                              border_width=1, border_color=BORDER)
        frame.pack(fill="both", expand=True, padx=1, pady=1)
        ctk.CTkLabel(frame, text=text,
                     font=("Segoe UI", 13, "bold"),
                     text_color=color).pack(expand=True)
        self._fade_in(0.0)

    def _fade_in(self, a: float) -> None:
        a = min(a + 0.18, 0.94)
        self._safe_alpha(a)
        if a < 0.94:
            self.after(18, self._fade_in, a)
        else:
            self.after(1_300, self._fade_out, a)

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

    def _safe_alpha(self, v: float) -> None:
        try:
            self.attributes("-alpha", v)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# Settings dialog
# ═══════════════════════════════════════════════════════════════════════════════

class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, master: "App") -> None:
        super().__init__(master)
        self.app = master
        self.title("Settings")
        self.geometry("440x340")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.transient(master)
        self.lift()
        self.focus_force()
        self._pending_toggle   = master.recorder.toggle_key
        self._pending_ocr_chk  = master.recorder.ocr_check_key
        self._capturing_field  = None   # "toggle" | "ocr_check"
        self._build()

    def _build(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(padx=22, pady=(22, 4), fill="x")
        ctk.CTkLabel(hdr, text="Settings",
                     font=("Segoe UI", 17, "bold"), text_color=TEXT_HI).pack(anchor="w")
        ctk.CTkLabel(hdr, text="Customize hotkeys for the recorder",
                     font=("Segoe UI", 11), text_color=TEXT_LO).pack(anchor="w")

        card = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=10)
        card.pack(padx=22, pady=(14, 8), fill="x")
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(card, text="HOTKEYS",
                     font=("Segoe UI", 9, "bold"), text_color=TEXT_LO).grid(
                         row=0, column=0, columnspan=3, padx=16, pady=(14, 6), sticky="w")

        # ── Row 1: Toggle recording ────────────────────────────────────────────
        ctk.CTkLabel(card, text="Toggle Recording",
                     font=("Segoe UI", 12), text_color=TEXT_MD).grid(
                         row=1, column=0, padx=16, pady=(0, 12), sticky="w")
        self.toggle_key_lbl = ctk.CTkLabel(
            card, text=key_display(self._pending_toggle),
            font=("Consolas", 13, "bold"),
            fg_color=BG, text_color=ACCENT, corner_radius=6, width=64, height=30)
        self.toggle_key_lbl.grid(row=1, column=1, padx=8, pady=(0, 12))
        ctk.CTkButton(
            card, text="Change",
            font=("Segoe UI", 11),
            fg_color=ELEVATED, hover_color=BORDER,
            text_color=TEXT_MD, border_color=BORDER, border_width=1,
            height=32, width=90, corner_radius=7,
            command=lambda: self._start_capture("toggle"),
        ).grid(row=1, column=2, padx=16, pady=(0, 12))

        # ── Row 2: OCR Check ───────────────────────────────────────────────────
        ctk.CTkLabel(card, text="OCR Check (mid-record)",
                     font=("Segoe UI", 12), text_color=TEXT_MD).grid(
                         row=2, column=0, padx=16, pady=(0, 14), sticky="w")
        self.ocr_key_lbl = ctk.CTkLabel(
            card, text=key_display(self._pending_ocr_chk),
            font=("Consolas", 13, "bold"),
            fg_color="#0E3535", text_color="#3ECFB2", corner_radius=6, width=64, height=30)
        self.ocr_key_lbl.grid(row=2, column=1, padx=8, pady=(0, 14))
        ctk.CTkButton(
            card, text="Change",
            font=("Segoe UI", 11),
            fg_color=ELEVATED, hover_color=BORDER,
            text_color=TEXT_MD, border_color=BORDER, border_width=1,
            height=32, width=90, corner_radius=7,
            command=lambda: self._start_capture("ocr_check"),
        ).grid(row=2, column=2, padx=16, pady=(0, 14))

        self.hint_lbl = ctk.CTkLabel(card, text="",
                                      font=("Segoe UI", 10, "italic"), text_color=TEXT_DIM)
        self.hint_lbl.grid(row=3, column=0, columnspan=3, padx=16, pady=(0, 10))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(padx=22, pady=(4, 22), fill="x")
        btn_row.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkButton(btn_row, text="Cancel",
                      font=("Segoe UI", 12),
                      fg_color="transparent", hover_color=ELEVATED,
                      text_color=TEXT_LO, border_color=BORDER, border_width=1,
                      height=40, corner_radius=8,
                      command=self.destroy).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkButton(btn_row, text="Save & Close",
                      font=("Segoe UI", 12, "bold"),
                      fg_color=ACCENT, hover_color=ACCENT_H, text_color=BG,
                      height=40, corner_radius=8,
                      command=self._save).grid(row=0, column=1, sticky="ew", padx=(6, 0))

    def _start_capture(self, field: str) -> None:
        self._capturing_field = field
        self.hint_lbl.configure(text="Press any key  (modifiers are ignored)")
        self.app.recorder.capture_next_key(self._on_key_captured)

    def _on_key_captured(self, key) -> None:
        self.after(0, self._update_display, key)

    def _update_display(self, key) -> None:
        if not self.winfo_exists():
            return
        self.hint_lbl.configure(text="")
        if self._capturing_field == "toggle":
            self._pending_toggle = key
            self.toggle_key_lbl.configure(text=key_display(key), text_color=ACCENT)
        elif self._capturing_field == "ocr_check":
            self._pending_ocr_chk = key
            self.ocr_key_lbl.configure(text=key_display(key), text_color="#3ECFB2")
        self._capturing_field = None

    def _save(self) -> None:
        data = cfg.load()
        data["toggle_key"]    = str(self._pending_toggle)
        data["ocr_check_key"] = str(self._pending_ocr_chk)
        cfg.save(data)
        self.app.recorder.set_toggle_key(self._pending_toggle)
        self.app.recorder.set_ocr_check_key(self._pending_ocr_chk)
        self.app.hotkey_lbl.configure(text=f"  {key_display(self._pending_toggle)}  ")
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
# Main App
# ═══════════════════════════════════════════════════════════════════════════════

class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("PokéShiny — Auto Hunter")
        self.geometry("1080x720")
        self.minsize(860, 580)
        self.configure(fg_color=BG)

        # Shared state
        self.target_hwnd: Optional[int] = None
        self._windows: list = []
        self._dot_job: Optional[str] = None

        # Exposed widget refs (set by _build_toolbar)
        self.hotkey_lbl: Optional[ctk.CTkLabel] = None
        self._status_dot: Optional[ctk.CTkLabel] = None
        self._status_txt: Optional[ctk.CTkLabel] = None
        self._stat_steps: Optional[ctk.CTkLabel] = None
        self._stat_time:  Optional[ctk.CTkLabel] = None

        # Core modules
        self.recorder    = MovementRecorder()
        self.player      = MovementPlayer()
        self.detector    = ScreenDetector()
        self.auto_runner = AutoRunner(self.detector)

        # Restore saved OCR region from last session
        _saved = cfg.load()
        _region = _saved.get("ocr_region")
        if isinstance(_region, list) and len(_region) == 4:
            self.detector.set_ocr_region(*_region)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._build_header()
        self._build_toolbar()
        self._build_tab_bar()
        self._build_content()

    def _build_header(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=64)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(1, weight=1)

        # Logo + title
        logo = ctk.CTkFrame(hdr, fg_color="transparent")
        logo.grid(row=0, column=0, padx=20, pady=12, sticky="w")
        ctk.CTkLabel(logo, text="✦", font=("Segoe UI", 22),
                     text_color=ACCENT).pack(side="left", padx=(0, 10))
        title_stack = ctk.CTkFrame(logo, fg_color="transparent")
        title_stack.pack(side="left")
        ctk.CTkLabel(title_stack, text="PokéShiny",
                     font=("Segoe UI", 15, "bold"),
                     text_color=TEXT_HI).pack(anchor="w")
        ctk.CTkLabel(title_stack, text="Auto Hunter",
                     font=("Segoe UI", 10), text_color=TEXT_LO).pack(anchor="w")

        # Right: stats + settings
        right = ctk.CTkFrame(hdr, fg_color="transparent")
        right.grid(row=0, column=2, padx=20, pady=12, sticky="e")

        # Hotkey pill
        pill = ctk.CTkFrame(right, fg_color=ELEVATED, corner_radius=7)
        pill.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(pill, text="Hotkey",
                     font=("Segoe UI", 9), text_color=TEXT_LO).pack(
                         side="left", padx=(10, 4), pady=6)
        self.hotkey_lbl = ctk.CTkLabel(
            pill,
            text=f"  {key_display(self.recorder.toggle_key)}  ",
            font=("Consolas", 11, "bold"),
            text_color=ACCENT, fg_color=BG, corner_radius=4)
        self.hotkey_lbl.pack(side="left", padx=(0, 10), pady=6)

        ctk.CTkButton(
            right, text="⚙  Settings",
            font=("Segoe UI", 10),
            fg_color=ELEVATED, hover_color=BORDER,
            text_color=TEXT_LO, border_color=BORDER, border_width=1,
            height=32, width=100, corner_radius=7,
            command=self._open_settings,
        ).pack(side="left")

    def _build_toolbar(self) -> None:
        tb = ctk.CTkFrame(self, fg_color=BG, corner_radius=0, height=52)
        tb.grid(row=1, column=0, sticky="ew")
        tb.grid_propagate(False)
        tb.grid_columnconfigure(2, weight=1)

        # Window selector
        ctk.CTkLabel(tb, text="Target:",
                     font=("Segoe UI", 10), text_color=TEXT_LO).grid(
                         row=0, column=0, padx=(16, 6), pady=14)

        self.window_var = ctk.StringVar(value="— Not selected —")
        self.window_menu = ctk.CTkOptionMenu(
            tb,
            values=["— Not selected —"],
            variable=self.window_var,
            font=("Segoe UI", 10),
            fg_color=ELEVATED, button_color=BORDER,
            button_hover_color=TEXT_DIM, text_color=TEXT_MD,
            dropdown_fg_color=SURFACE, dropdown_text_color=TEXT_MD,
            dropdown_hover_color=ELEVATED,
            corner_radius=7, dynamic_resizing=False,
            width=240,
            command=self._on_window_selected,
        )
        self.window_menu.grid(row=0, column=1, padx=(0, 4), pady=14)

        ctk.CTkButton(
            tb, text="🔄",
            font=("Segoe UI", 12),
            fg_color=ELEVATED, hover_color=BORDER,
            text_color=TEXT_LO, width=30, height=30, corner_radius=7,
            command=self._refresh_windows,
        ).grid(row=0, column=2, padx=(0, 20), pady=14, sticky="w")

        # Status pill (right)
        status_pill = ctk.CTkFrame(tb, fg_color=ELEVATED, corner_radius=8)
        status_pill.grid(row=0, column=3, padx=16, pady=10, sticky="e")

        self._status_dot = ctk.CTkLabel(
            status_pill, text="●", font=("Segoe UI", 14), text_color=TEXT_DIM)
        self._status_dot.pack(side="left", padx=(10, 4), pady=6)

        self._status_txt = ctk.CTkLabel(
            status_pill, text="IDLE", font=("Segoe UI", 11, "bold"), text_color=TEXT_LO)
        self._status_txt.pack(side="left", padx=(0, 10), pady=6)

    def _build_tab_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=46)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(2, weight=1)  # spacer

        self._tab_btns: dict[str, ctk.CTkButton] = {}

        for col, (name, label) in enumerate([
            ("movement", "🎬   Movement"),
            ("plan",     "🎯   Plan"),
        ]):
            btn = ctk.CTkButton(
                bar, text=label,
                font=("Segoe UI", 12),
                fg_color="transparent",
                hover_color=ELEVATED,
                text_color=TEXT_LO,
                height=36, corner_radius=8,
                command=lambda n=name: self._switch_tab(n),
            )
            btn.grid(row=0, column=col, padx=(12 if col == 0 else 4, 0), pady=5, sticky="w")
            self._tab_btns[name] = btn

        # Separator
        ctk.CTkFrame(bar, fg_color=BORDER, height=1).grid(
            row=1, column=0, columnspan=3, sticky="ew")

    def _build_content(self) -> None:
        from ui.tab_movement import MovementTab
        from ui.tab_plan     import PlanTab

        content = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        content.grid(row=3, column=0, sticky="nsew", padx=10, pady=(8, 10))
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self._tabs: dict[str, ctk.CTkFrame] = {}

        self.movement_tab = MovementTab(content, self)
        self.movement_tab.grid(row=0, column=0, sticky="nsew")
        self._tabs["movement"] = self.movement_tab

        self.plan_tab = PlanTab(content, self)
        self.plan_tab.grid(row=0, column=0, sticky="nsew")
        self._tabs["plan"] = self.plan_tab

        # Start recorder AFTER tabs are set up (they register callbacks)
        self.recorder.start_listener()

        self._switch_tab("movement")

    # ── Tab switching ─────────────────────────────────────────────────────────

    def _switch_tab(self, name: str) -> None:
        for n, frame in self._tabs.items():
            if n == name:
                frame.tkraise()
            # Update button styles
            btn = self._tab_btns[n]
            if n == name:
                btn.configure(
                    fg_color=ACCENT, text_color=BG,
                    hover_color=ACCENT_H, font=("Segoe UI", 12, "bold"))
            else:
                btn.configure(
                    fg_color="transparent", text_color=TEXT_LO,
                    hover_color=ELEVATED, font=("Segoe UI", 12))

    # ── Shared API (called by tabs) ───────────────────────────────────────────

    def set_status(self, text: str, color: str) -> None:
        if self._status_dot:
            self._status_dot.configure(text_color=color)
        if self._status_txt:
            self._status_txt.configure(text=text, text_color=color)

    def set_stats(self, steps: str, duration: str) -> None:
        pass  # Stats now live in each tab's own UI

    def start_blink(self) -> None:
        self._stop_blink_internal()
        self._blink_tick()

    def stop_blink(self) -> None:
        self._stop_blink_internal()
        if self._status_dot:
            self._status_dot.configure(text_color=TEXT_DIM)

    def _blink_tick(self) -> None:
        if not self.recorder.is_recording:
            return
        if self._status_dot:
            c = self._status_dot.cget("text_color")
            self._status_dot.configure(
                text_color=RECORD_D if c == RECORD else RECORD)
        self._dot_job = self.after(560, self._blink_tick)

    def _stop_blink_internal(self) -> None:
        if self._dot_job:
            self.after_cancel(self._dot_job)
            self._dot_job = None

    def show_toast(self, text: str, color: str) -> None:
        Toast(self, text, color)

    def notify_sequences_changed(self) -> None:
        """Called when Movement tab saves or deletes a sequence."""
        if hasattr(self, "plan_tab"):
            self.plan_tab.refresh_sequences()

    # ── Window selector ───────────────────────────────────────────────────────

    def _refresh_windows(self) -> None:
        from core import window_manager as wm_mod
        if not wm_mod.is_available():
            messagebox.showerror(
                "pywin32 Not Found",
                "Install it with:\npip install pywin32",
                parent=self,
            )
            return
        self._windows = wm_mod.list_windows()
        labels = ["— Not selected —"] + [w.label() for w in self._windows]
        self.window_menu.configure(values=labels)

    def _on_window_selected(self, label: str) -> None:
        if label == "— Not selected —":
            self.target_hwnd = None
            self.recorder.set_target_hwnd(None)
            self.detector.set_target_hwnd(None)
            return
        for w in self._windows:
            if w.label() == label:
                self.target_hwnd = w.hwnd
                self.recorder.set_target_hwnd(w.hwnd)
                self.detector.set_target_hwnd(w.hwnd)
                return
        self.target_hwnd = None
        self.recorder.set_target_hwnd(None)
        self.detector.set_target_hwnd(None)

    # ── Settings ──────────────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self)
        dlg.focus_force()

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        # Persist OCR region so it's restored next session
        region = self.detector.get_ocr_region()
        data   = cfg.load()
        data["ocr_region"] = list(region) if region else None
        cfg.save(data)

        self.auto_runner.stop()
        self.player.stop()
        self.recorder.stop_listener()
        self.destroy()
