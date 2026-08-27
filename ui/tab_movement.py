"""
ui/tab_movement.py — Movement recording & playback tab.
"""
from __future__ import annotations

from pathlib import Path
from tkinter import messagebox
from typing import TYPE_CHECKING

import customtkinter as ctk

from core.recorder import MovementRecorder
from core.settings import key_display

if TYPE_CHECKING:
    from ui.app import App

from core.paths import MOVES_DIR as DATA_DIR

# ── Colours (shared palette) ──────────────────────────────────────────────────
from ui.theme import (
    BG, SURFACE, ELEVATED, BORDER,
    TEXT_HI, TEXT_MD, TEXT_LO, TEXT_DIM,
    ACCENT, ACCENT_H, RECORD, RECORD_D,
    PLAY_BG, PLAY_BD, PLAY_TXT, PLAY_DIM,
)


class MovementTab(ctk.CTkFrame):
    """Two-panel tab: saved sequences (left) | recording log + save bar (right)."""

    def __init__(self, parent, app: "App") -> None:
        super().__init__(parent, fg_color="transparent", corner_radius=0)
        self.app = app

        self._log_row   = 0
        self._dot_job: str | None = None
        self.empty_label: ctk.CTkLabel | None = None

        # Playback bar widgets
        self.pb_frame:    ctk.CTkFrame | None = None
        self.pb_name_lbl: ctk.CTkLabel | None = None
        self.pb_step_lbl: ctk.CTkLabel | None = None
        self.pb_progress: ctk.CTkProgressBar | None = None
        self.pb_loop_var  = ctk.BooleanVar(value=False)

        # Wire callbacks
        app.recorder.on_toggle = self._cb_toggle
        app.recorder.on_action = self._cb_action
        app.player.on_step     = self._cb_play_step
        app.player.on_complete = self._cb_play_complete
        app.player.on_stopped  = self._cb_play_stopped

        self._build()
        self._refresh_saved_list()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=0, minsize=260)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_left()
        self._build_right()

    def _build_left(self) -> None:
        left = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=0)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        # Header
        hdr = ctk.CTkFrame(left, fg_color="transparent")
        hdr.grid(row=0, column=0, padx=14, pady=(16, 8), sticky="ew")
        ctk.CTkLabel(hdr, text="SAVED SEQUENCES",
                     font=("Segoe UI", 9, "bold"),
                     text_color=TEXT_LO).pack(anchor="w")

        # Scrollable list
        self.saved_scroll = ctk.CTkScrollableFrame(
            left, fg_color=BG, corner_radius=8,
            scrollbar_button_color=ELEVATED,
            scrollbar_button_hover_color=BORDER,
        )
        self.saved_scroll.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.saved_scroll.grid_columnconfigure(0, weight=1)

    def _build_right(self) -> None:
        right = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=12)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=0)
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        # Header
        hdr = ctk.CTkFrame(right, fg_color="transparent")
        hdr.grid(row=0, column=0, padx=18, pady=(16, 10), sticky="ew")
        ctk.CTkLabel(hdr, text="Recording Log",
                     font=("Segoe UI", 15, "bold"),
                     text_color=TEXT_HI).pack(anchor="w")
        ctk.CTkLabel(hdr, text="All keys and mouse clicks captured while recording",
                     font=("Segoe UI", 10), text_color=TEXT_LO).pack(anchor="w")

        # Playback bar (hidden)
        self._build_playback_bar(right)

        # Log scrollable
        self.log_scroll = ctk.CTkScrollableFrame(
            right, fg_color=BG, corner_radius=10,
            scrollbar_button_color=ELEVATED,
            scrollbar_button_hover_color=BORDER,
        )
        self.log_scroll.grid(row=1, column=0, padx=16, pady=(0, 8), sticky="nsew")
        self.log_scroll.grid_columnconfigure(0, weight=1)
        self._show_empty_state()

        # Save bar
        self._build_save_bar(right)

    def _build_playback_bar(self, parent: ctk.CTkFrame) -> None:
        self.pb_frame = ctk.CTkFrame(
            parent, fg_color=PLAY_BG, corner_radius=10,
            border_width=1, border_color=PLAY_BD,
        )
        # row=0.5 → use a dedicated row index
        self.pb_frame.grid(row=2, column=0, padx=16, pady=(0, 4), sticky="ew")
        self.pb_frame.grid_columnconfigure(1, weight=1)
        self.pb_frame.grid_remove()

        ctk.CTkLabel(self.pb_frame, text="▶",
                     font=("Segoe UI", 14), text_color=PLAY_TXT).grid(
                         row=0, column=0, padx=(12, 4), pady=(10, 4))

        self.pb_name_lbl = ctk.CTkLabel(
            self.pb_frame, text="", anchor="w",
            font=("Segoe UI", 11, "bold"), text_color=PLAY_TXT)
        self.pb_name_lbl.grid(row=0, column=1, padx=4, pady=(10, 4), sticky="ew")

        self.pb_step_lbl = ctk.CTkLabel(
            self.pb_frame, text="Step 0 / 0",
            font=("Consolas", 10), text_color=PLAY_DIM)
        self.pb_step_lbl.grid(row=0, column=2, padx=8, pady=(10, 4))

        self.pb_loop_sw = ctk.CTkSwitch(
            self.pb_frame, text="Loop",
            font=("Segoe UI", 10), text_color=PLAY_DIM,
            variable=self.pb_loop_var,
            fg_color=BORDER, progress_color=PLAY_TXT,
            command=self._on_loop_toggle,
            width=40, height=20,
        )
        self.pb_loop_sw.grid(row=0, column=3, padx=8, pady=(10, 4))

        ctk.CTkButton(
            self.pb_frame, text="■  Stop",
            font=("Segoe UI", 10, "bold"),
            fg_color="#3D1010", hover_color="#5A1515",
            text_color=RECORD, border_color="#7B1010", border_width=1,
            height=28, width=80, corner_radius=6,
            command=self._stop_playback,
        ).grid(row=0, column=4, padx=(4, 12), pady=(10, 4))

        self.pb_progress = ctk.CTkProgressBar(
            self.pb_frame,
            fg_color=BORDER, progress_color=PLAY_TXT,
            height=5, corner_radius=3,
        )
        self.pb_progress.set(0)
        self.pb_progress.grid(
            row=1, column=0, columnspan=5,
            padx=12, pady=(0, 10), sticky="ew")

    def _build_save_bar(self, parent: ctk.CTkFrame) -> None:
        bar = ctk.CTkFrame(parent, fg_color=BG, corner_radius=10)
        bar.grid(row=3, column=0, padx=16, pady=(0, 16), sticky="ew")
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=10)
        inner.grid_columnconfigure(0, weight=1)

        self.name_entry = ctk.CTkEntry(
            inner,
            placeholder_text="Name this sequence…   e.g.  route_wild",
            font=("Segoe UI", 12),
            fg_color=SURFACE, border_color=BORDER,
            text_color=TEXT_HI, placeholder_text_color=TEXT_DIM,
            height=38, corner_radius=8,
        )
        self.name_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        from core.settings import key_display as _kd
        _ocr_hk = _kd(self.app.recorder.ocr_check_key)
        self._ocr_btn = ctk.CTkButton(
            inner, text=f"\U0001f4f8 OCR [{_ocr_hk}]",
            font=("Segoe UI", 10, "bold"),
            fg_color="#0E3535", hover_color="#145252",
            text_color="#3ECFB2", border_color="#1E6060", border_width=1,
            height=38, width=110, corner_radius=8,
            command=self._insert_ocr_check,
            state="disabled",
        )
        self._ocr_btn.grid(row=0, column=1, padx=(0, 8))

        ctk.CTkButton(
            inner, text="💾  Save",
            font=("Segoe UI", 11, "bold"),
            fg_color=ACCENT, hover_color=ACCENT_H, text_color=BG,
            height=38, width=106, corner_radius=8,
            command=self._save_sequence,
        ).grid(row=0, column=2)

        ctk.CTkButton(
            inner, text="Clear",
            font=("Segoe UI", 11),
            fg_color="transparent", hover_color=ELEVATED,
            text_color=TEXT_LO, border_color=BORDER, border_width=1,
            height=38, width=74, corner_radius=8,
            command=self._clear_log,
        ).grid(row=0, column=3, padx=(6, 0))

    def _insert_ocr_check(self) -> None:
        """Insert an OCR-check checkpoint into the current recording."""
        self.app.recorder.insert_ocr_check()
        self.app.show_toast("📷  OCR Check inserted", "#3ECFB2")

    # ── Recorder callbacks ─────────────────────────────────────────────────────

    def _cb_toggle(self, is_recording: bool) -> None:
        self.after(0, self._on_toggle_ui, is_recording)

    def _cb_action(self, action: dict) -> None:
        self.after(0, self._add_log_entry, action)

    # ── UI updates ────────────────────────────────────────────────────────────

    def _on_toggle_ui(self, is_recording: bool) -> None:
        hk = key_display(self.app.recorder.toggle_key)
        if is_recording:
            self._clear_log()
            self.app.set_status("RECORDING", RECORD)
            self.app.start_blink()
            self.app.show_toast(f"● REC  STARTED  [{hk}]", RECORD)
            if hasattr(self, '_ocr_btn'):
                self._ocr_btn.configure(state="normal")
        else:
            self.app.stop_blink()
            self.app.set_status("IDLE", TEXT_LO)
            actions    = self.app.recorder.actions
            presses    = [a for a in actions if a["event"] in ("press", "click")]
            ocr_checks = [a for a in actions if a["event"] == "ocr_check"]
            step_count = len(presses)
            total_time = f"{actions[-1]['time']:.1f}s" if actions else "0.0s"
            self.app.set_stats(str(step_count), total_time)
            chk_note = f" + {len(ocr_checks)} OCR check(s)" if ocr_checks else ""
            self.app.show_toast(f"■  STOPPED  [{hk}]  —  {step_count} steps{chk_note}", TEXT_MD)
            if step_count > 0 or ocr_checks:
                self._add_complete_banner(step_count, len(ocr_checks))
            if hasattr(self, '_ocr_btn'):
                self._ocr_btn.configure(state="disabled")

    def _add_complete_banner(self, step_count: int, ocr_count: int = 0) -> None:
        row = self._log_row
        self._log_row += 1
        banner = ctk.CTkFrame(
            self.log_scroll, fg_color=PLAY_BG, corner_radius=8,
            border_width=1, border_color=PLAY_BD,
        )
        banner.grid(row=row, column=0, padx=6, pady=(8, 2), sticky="ew")
        banner.grid_columnconfigure(0, weight=1)
        ocr_note = f"  |  {ocr_count} OCR check(s)" if ocr_count else ""
        ctk.CTkLabel(
            banner,
            text=f"\u2713   Recording complete \u2014 {step_count} steps captured{ocr_note}",
            font=("Segoe UI", 11, "bold"), text_color=PLAY_TXT,
        ).grid(row=0, column=0, padx=14, pady=(10, 2), sticky="w")
        ctk.CTkLabel(
            banner,
            text="Enter a name below and press 💾 Save",
            font=("Segoe UI", 9), text_color=PLAY_DIM,
        ).grid(row=1, column=0, padx=14, pady=(0, 10), sticky="w")
        self.log_scroll._parent_canvas.yview_moveto(1.0)

    def _add_log_entry(self, action: dict) -> None:
        event = action["event"]
        if event not in ("press", "click", "ocr_check"):
            return
        if self.empty_label and self.empty_label.winfo_exists():
            self.empty_label.grid_remove()

        row = self._log_row
        self._log_row += 1

        # OCR check: distinct teal card
        if event == "ocr_check":
            entry = ctk.CTkFrame(
                self.log_scroll, fg_color="#0E3535", corner_radius=7,
                border_width=1, border_color="#1E6060",
            )
            entry.grid(row=row, column=0, padx=6, pady=2, sticky="ew")
            entry.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(entry, text="\U0001f4f8", font=("Segoe UI", 14)).grid(
                row=0, column=0, padx=(12, 6), pady=8)
            ctk.CTkLabel(
                entry, text="OCR Check  \u2014  scan for Shiny here",
                font=("Segoe UI", 11, "bold"), text_color="#3ECFB2", anchor="w",
            ).grid(row=0, column=1, sticky="w")
            ctk.CTkLabel(entry, text=f"@ {action['time']:.3f}s",
                         font=("Consolas", 10), text_color="#256050",
                         ).grid(row=0, column=2, padx=(4, 14), pady=8)
            self.log_scroll._parent_canvas.yview_moveto(1.0)
            return

        # Regular key/click action
        entry = ctk.CTkFrame(self.log_scroll, fg_color=ELEVATED, corner_radius=7)
        entry.grid(row=row, column=0, padx=6, pady=2, sticky="ew")
        entry.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(entry, text=f"{row + 1:>3}",
                     font=("Consolas", 10), text_color=TEXT_DIM,
                     width=34).grid(row=0, column=0, padx=(10, 4), pady=8)

        disp = action.get("display", action["key"])
        if event == "click":
            badge_bg, badge_text = "#1A2F4A", "#58A6FF"
        else:
            badge_bg, badge_text = BG, ACCENT

        ctk.CTkLabel(entry, text=disp,
                     font=("Consolas", 12, "bold"),
                     fg_color=badge_bg, text_color=badge_text,
                     corner_radius=5, height=26, padx=6).grid(
                         row=0, column=1, padx=4, pady=8)

        if event == "click":
            coords = f"({action.get('x', 0)}, {action.get('y', 0)})"
            ctk.CTkLabel(entry, text=coords,
                         font=("Consolas", 9), text_color=TEXT_DIM,
                         anchor="w").grid(row=0, column=2, sticky="w", padx=(2, 4))
        else:
            ctk.CTkLabel(entry, text="", fg_color="transparent").grid(
                row=0, column=2, sticky="ew")

        ctk.CTkLabel(entry, text=f"@ {action['time']:.3f}s",
                     font=("Consolas", 10), text_color=TEXT_DIM).grid(
                         row=0, column=3, padx=(4, 14), pady=8)

        self.log_scroll._parent_canvas.yview_moveto(1.0)

    def _show_empty_state(self) -> None:
        self.empty_label = ctk.CTkLabel(
            self.log_scroll,
            text=(
                "No actions recorded yet.\n\n"
                "Press the hotkey while in-game\n"
                "to start capturing your movement."
            ),
            font=("Segoe UI", 12), text_color=TEXT_DIM, justify="center",
        )
        self.empty_label.grid(row=0, column=0, pady=70)

    def _clear_log(self) -> None:
        for w in self.log_scroll.winfo_children():
            w.destroy()
        self._log_row = 0
        self.app.set_stats("0", "0.0s")
        self._show_empty_state()

    def _save_sequence(self) -> None:
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showwarning("Name Required", "Please give this sequence a name.", parent=self)
            return
        if self.app.recorder.is_recording:
            messagebox.showwarning("Still Recording", "Stop recording first.", parent=self)
            return
        if not self.app.recorder.actions:
            messagebox.showwarning("No Data", "There are no recorded actions to save.", parent=self)
            return
        try:
            self.app.recorder.save(name, DATA_DIR)
            self.name_entry.delete(0, "end")
            self._refresh_saved_list()
            self.app.notify_sequences_changed()
        except Exception as exc:
            messagebox.showerror("Save Error", str(exc), parent=self)

    # ── Saved list ────────────────────────────────────────────────────────────

    def _refresh_saved_list(self) -> None:
        for w in self.saved_scroll.winfo_children():
            w.destroy()
        seqs = MovementRecorder.load_all(DATA_DIR)
        if not seqs:
            ctk.CTkLabel(self.saved_scroll,
                         text="No saved sequences",
                         font=("Segoe UI", 10), text_color=TEXT_DIM).pack(pady=14)
            return
        for seq in seqs:
            self._seq_card(seq)

    def _seq_card(self, seq: dict) -> None:
        card = ctk.CTkFrame(self.saved_scroll, fg_color=BG, corner_radius=9)
        card.pack(fill="x", padx=4, pady=3)
        card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(card, text=seq.get("name", "?"),
                     font=("Segoe UI", 11, "bold"),
                     text_color=TEXT_MD, anchor="w").grid(
                         row=0, column=0, padx=11, pady=(9, 1), sticky="w")

        info = f"{seq.get('step_count', 0)} steps \u00b7 {seq.get('total_time', 0.0):.1f}s"
        ctk.CTkLabel(card, text=info,
                     font=("Segoe UI", 9), text_color=TEXT_LO, anchor="w").grid(
                         row=1, column=0, padx=11, pady=(0, 9), sticky="w")

        ctk.CTkButton(
            card, text="\u25b6",
            font=("Segoe UI", 12, "bold"),
            fg_color=PLAY_BG, hover_color="#1B4030",
            text_color=PLAY_TXT, border_color=PLAY_BD, border_width=1,
            width=32, height=32, corner_radius=8,
            command=lambda s=seq: self._start_playback(s),
        ).grid(row=0, column=1, rowspan=2, padx=(4, 4), pady=8)

        ctk.CTkButton(
            card, text="\u270f",
            font=("Segoe UI", 12),
            fg_color=ELEVATED, hover_color=BORDER,
            text_color=TEXT_LO, border_color=BORDER, border_width=1,
            width=28, height=28, corner_radius=7,
            command=lambda s=seq: self._edit_sequence(s),
        ).grid(row=0, column=2, rowspan=2, padx=(0, 4), pady=8)

        ctk.CTkButton(
            card, text="\U0001f5d1",
            font=("Segoe UI", 11),
            fg_color="transparent", hover_color="#3D1010",
            text_color=TEXT_DIM, border_color=BORDER, border_width=1,
            width=28, height=28, corner_radius=7,
            command=lambda n=seq.get("name", ""): self._delete_sequence(n),
        ).grid(row=0, column=3, rowspan=2, padx=(0, 10), pady=8)

    def _edit_sequence(self, seq: dict) -> None:
        from ui.sequence_editor import SequenceEditorDialog
        def _on_save():
            self._refresh_saved_list()
            self.app.notify_sequences_changed()
        SequenceEditorDialog(self.app, seq, self.app, on_save=_on_save)

    def _delete_sequence(self, name: str) -> None:
        if not messagebox.askyesno(
            "Delete Sequence", f"Delete '{name}'?\nThis cannot be undone.", parent=self
        ):
            return
        try:
            MovementRecorder.delete(name, DATA_DIR)
            self._refresh_saved_list()
            self.app.notify_sequences_changed()
        except Exception as exc:
            messagebox.showerror("Delete Error", str(exc), parent=self)

    # ── Playback ──────────────────────────────────────────────────────────────

    def _start_playback(self, seq: dict) -> None:
        if self.app.recorder.is_recording:
            messagebox.showwarning(
                "Recording Active", "Stop recording before playback.", parent=self)
            return
        if self.app.player.is_playing:
            return
        actions = seq.get("actions", [])
        if not actions:
            return
        presses = [a for a in actions if a["event"] in ("press", "click")]
        total   = len(presses)

        # Wire OCR check so overlay + toast appear during playback
        self.app.player.on_ocr_check = self._handle_ocr_during_playback

        self.app.player.play(seq, loop=self.pb_loop_var.get(),
                             target_hwnd=self.app.target_hwnd)
        self.pb_name_lbl.configure(text=seq.get("name", ""))
        self.pb_step_lbl.configure(text=f"Step 0 / {total}")
        self.pb_progress.set(0)
        self.pb_frame.grid()

    def _handle_ocr_during_playback(self) -> bool:
        """Called from player thread when an ocr_check action fires.

        Shows OCR speech bubbles at detected positions. Never stops playback.
        """
        from core.debug_log import dlog

        try:
            is_shiny, text, groups = self.app.detector.check_shiny_ocr_with_boxes()
        except Exception as exc:
            dlog(f"[movement ocr] error: {exc}")
            return False

        dlog(f"[movement ocr] is_shiny={is_shiny} groups={len(groups)}")
        for gi, (gt, *_) in enumerate(groups):
            dlog(f"  group[{gi}]: {repr(gt)}")

        # Schedule on main thread (player runs in background)
        self.after(0, lambda: self._show_ocr_result(text, groups, is_shiny))

        return False  # don't stop playback

    def _show_ocr_result(self, text: str, groups: list, is_shiny: bool) -> None:
        """Main-thread: show Toast + speech bubble overlays."""
        from ui.ocr_bubble import OcrBubbleOverlay
        from ui.theme import PLAY_TXT
        _SHINY_COLOR = "#FFD700"
        color = _SHINY_COLOR if is_shiny else PLAY_TXT
        label = "✨ SHINY!" if is_shiny else "📸 OCR"
        display = (text or "").replace("\n", "  ").strip()[:60] or "(no text)"
        self.app.show_toast(f"{label}: {display}", color)
        OcrBubbleOverlay.show(self.app, groups=groups, is_shiny=is_shiny)

    def _stop_playback(self) -> None:
        self.app.player.stop()

    def _on_loop_toggle(self) -> None:
        if self.app.player.is_playing:
            self.app.player.loop = self.pb_loop_var.get()

    # Playback callbacks (player thread → main thread)
    def _cb_play_step(self, step: int, total: int) -> None:
        self.after(0, self._update_pb_ui, step, total)

    def _cb_play_complete(self) -> None:
        self.after(0, self._hide_pb_bar)

    def _cb_play_stopped(self) -> None:
        self.after(0, self._hide_pb_bar)

    def _update_pb_ui(self, step: int, total: int) -> None:
        loop_tag = "  🔁" if self.app.player.loop else ""
        self.pb_step_lbl.configure(text=f"Step {step} / {total}{loop_tag}")
        self.pb_progress.set(step / total if total else 0)

    def _hide_pb_bar(self) -> None:
        self.pb_progress.set(0)
        self.pb_frame.grid_remove()
