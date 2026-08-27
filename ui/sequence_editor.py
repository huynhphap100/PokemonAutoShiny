"""
ui/sequence_editor.py — In-place editor for a saved movement sequence.

Features
--------
* Show all actions as a scrollable list.
* Drag-and-drop rows (≡ handle) to reorder.
* Insert a new action between any two rows via the [+] button.
* Edit individual actions inline:
    - press/release  → capture new key + edit time
    - click          → edit x, y, time
    - ocr_check      → select region + edit time
* Delete any action row.
* Save writes the updated sequence back to disk.
* Cancel discards all changes.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from tkinter import messagebox
from typing import TYPE_CHECKING, Callable, Optional

import customtkinter as ctk
import tkinter as tk

if TYPE_CHECKING:
    pass

from ui.theme import (
    BG, SURFACE, ELEVATED, BORDER,
    TEXT_HI, TEXT_MD, TEXT_LO, TEXT_DIM,
    ACCENT, ACCENT_H,
    PLAY_TXT, PLAY_BG, PLAY_BD,
    RECORD,
)

_OCR_BG  = "#0E3535"
_OCR_BD  = "#1E6060"
_OCR_TXT = "#3ECFB2"
_CLK_BG  = "#0E1F3A"
_CLK_TXT = "#58A6FF"

DATA_DIR = Path(__file__).parent.parent / "data" / "movements"


class SequenceEditorDialog(ctk.CTkToplevel):
    """Modal dialog for editing a single saved sequence."""

    def __init__(
        self,
        master,
        seq: dict,
        app,
        on_save: Optional[Callable] = None,
    ) -> None:
        super().__init__(master)
        self.app      = app
        self._seq     = seq
        self._name    = seq.get("name", "")
        self._actions: list[dict] = copy.deepcopy(seq.get("actions", []))
        self._on_save = on_save

        # Drag state
        self._drag_idx:    Optional[int] = None
        self._drag_ghost:  Optional[ctk.CTkFrame] = None
        self._drag_sep:    Optional[ctk.CTkFrame] = None
        self._drag_target: int = -1

        # Edit-inline state
        self._editing_idx: Optional[int] = None

        # Dialog setup
        self.title(f"Edit Sequence — {self._name}")
        self.geometry("820x600")
        self.minsize(640, 420)
        self.configure(fg_color=BG)
        self.transient(master)
        self.grab_set()
        self.lift()
        self.focus_force()

        self._build()
        self._render_actions()

    # ── UI Build ──────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ── Name bar ──────────────────────────────────────────────────────────
        name_bar = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=52)
        name_bar.grid(row=0, column=0, sticky="ew")
        name_bar.grid_propagate(False)
        name_bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(name_bar, text="Name:", font=("Segoe UI", 11),
                     text_color=TEXT_LO).grid(row=0, column=0, padx=(16, 6), pady=14)
        self.name_entry = ctk.CTkEntry(
            name_bar, font=("Segoe UI", 12), fg_color=ELEVATED,
            border_color=BORDER, text_color=TEXT_HI, height=32)
        self.name_entry.insert(0, self._name)
        self.name_entry.grid(row=0, column=1, padx=(0, 16), pady=10, sticky="ew")

        # ── Column headers ────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color=ELEVATED, corner_radius=0, height=30)
        hdr.grid(row=1, column=0, sticky="ew")
        hdr.grid_propagate(False)
        for col, (txt, w) in enumerate([
            ("", 28), ("#", 36), ("Type", 58), ("Key / Info", 0), ("Time", 80),
            ("", 68), ("", 36),
        ]):
            ctk.CTkLabel(hdr, text=txt, font=("Segoe UI", 9),
                         text_color=TEXT_DIM, width=w or 1).grid(
                             row=0, column=col,
                             padx=(4 if col == 0 else 2, 2), pady=4, sticky="w")
        hdr.grid_columnconfigure(3, weight=1)

        # ── Scrollable action list ─────────────────────────────────────────────
        self.action_frame = ctk.CTkScrollableFrame(
            self, fg_color=BG, corner_radius=0,
            scrollbar_button_color=ELEVATED,
            scrollbar_button_hover_color=BORDER,
        )
        self.action_frame.grid(row=2, column=0, sticky="nsew", padx=0, pady=0)
        self.action_frame.grid_columnconfigure(0, weight=1)

        # ── Footer ────────────────────────────────────────────────────────────
        footer = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=60)
        footer.grid(row=3, column=0, sticky="ew")
        footer.grid_propagate(False)
        footer.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            footer, text="+ Add Action",
            font=("Segoe UI", 11),
            fg_color=ELEVATED, hover_color=BORDER,
            text_color=TEXT_MD, border_color=BORDER, border_width=1,
            height=36, corner_radius=8,
            command=self._add_action,
        ).grid(row=0, column=0, padx=16, pady=12)

        ctk.CTkButton(
            footer, text="Cancel",
            font=("Segoe UI", 12),
            fg_color="transparent", hover_color=ELEVATED,
            text_color=TEXT_LO, border_color=BORDER, border_width=1,
            height=38, width=110, corner_radius=8,
            command=self.destroy,
        ).grid(row=0, column=2, padx=(0, 8), pady=12)

        ctk.CTkButton(
            footer, text="💾  Save",
            font=("Segoe UI", 12, "bold"),
            fg_color=ACCENT, hover_color=ACCENT_H, text_color=BG,
            height=38, width=120, corner_radius=8,
            command=self._save,
        ).grid(row=0, column=3, padx=(0, 16), pady=12)

    # ── Action list rendering ─────────────────────────────────────────────────

    def _render_actions(self) -> None:
        """Clear and rebuild the action list from self._actions."""
        for w in self.action_frame.winfo_children():
            w.destroy()
        self._editing_idx = None

        for i, action in enumerate(self._actions):
            # Insert button (between rows)
            self._insert_btn(i)
            # Action row
            self._action_row(i, action)

        # Final insert button (after last row)
        self._insert_btn(len(self._actions))

        # Empty state
        if not self._actions:
            ctk.CTkLabel(
                self.action_frame,
                text="No actions yet.\nClick '+ Add Action' to start.",
                font=("Segoe UI", 12), text_color=TEXT_DIM, justify="center",
            ).pack(pady=40)

    def _insert_btn(self, pos: int) -> None:
        """Thin clickable separator between rows for inserting."""
        btn = ctk.CTkButton(
            self.action_frame,
            text="+ insert here",
            font=("Segoe UI", 8),
            fg_color="transparent", hover_color=ELEVATED,
            text_color=TEXT_DIM, height=16, corner_radius=4,
            command=lambda p=pos: self._insert_at(p),
        )
        btn.pack(fill="x", padx=8, pady=0)

    def _action_row(self, i: int, action: dict) -> None:
        event = action.get("event", "press")
        bg    = _OCR_BG if event == "ocr_check" else ELEVATED
        bd    = _OCR_BD if event == "ocr_check" else BORDER

        row = ctk.CTkFrame(self.action_frame, fg_color=bg, corner_radius=7,
                           border_width=1, border_color=bd)
        row.pack(fill="x", padx=8, pady=1)
        row.grid_columnconfigure(3, weight=1)

        # ── Drag handle ───────────────────────────────────────────────────────
        handle = ctk.CTkLabel(row, text="≡", font=("Segoe UI", 14),
                              text_color=TEXT_DIM, cursor="fleur", width=28)
        handle.grid(row=0, column=0, padx=(8, 2), pady=8)
        handle.bind("<ButtonPress-1>",   lambda e, idx=i: self._drag_start(e, idx))
        handle.bind("<B1-Motion>",       lambda e, idx=i: self._drag_motion(e, idx))
        handle.bind("<ButtonRelease-1>", lambda e, idx=i: self._drag_end(e, idx))

        # ── Row number ────────────────────────────────────────────────────────
        ctk.CTkLabel(row, text=f"{i+1}", font=("Consolas", 9),
                     text_color=TEXT_DIM, width=26).grid(
                         row=0, column=1, padx=(0, 4))

        # ── Type badge ────────────────────────────────────────────────────────
        badge_txt, badge_fg, badge_bg = self._badge(event)
        ctk.CTkLabel(row, text=badge_txt, font=("Segoe UI", 9, "bold"),
                     text_color=badge_fg, fg_color=badge_bg,
                     corner_radius=4, width=46).grid(row=0, column=2, padx=(0, 6))

        # ── Info ──────────────────────────────────────────────────────────────
        info_txt = self._info_str(action)
        ctk.CTkLabel(row, text=info_txt, font=("Consolas", 11),
                     text_color=_OCR_TXT if event == "ocr_check" else TEXT_MD,
                     anchor="w", justify="left").grid(
                         row=0, column=3, sticky="ew", padx=(0, 8))

        # ── Time ──────────────────────────────────────────────────────────────
        ctk.CTkLabel(row, text=f"@ {action.get('time', 0):.3f}s",
                     font=("Consolas", 9), text_color=TEXT_DIM,
                     width=72, anchor="e").grid(row=0, column=4, padx=(0, 6))

        # ── Edit button ───────────────────────────────────────────────────────
        ctk.CTkButton(
            row, text="✏ Edit",
            font=("Segoe UI", 10),
            fg_color=ELEVATED, hover_color=BORDER,
            text_color=TEXT_LO, border_color=BORDER, border_width=1,
            height=28, width=62, corner_radius=7,
            command=lambda idx=i, r=row: self._open_edit(idx, r),
        ).grid(row=0, column=5, padx=(0, 4))

        # ── Delete button ─────────────────────────────────────────────────────
        ctk.CTkButton(
            row, text="✕",
            font=("Segoe UI", 11),
            fg_color="transparent", hover_color="#3D1010",
            text_color=TEXT_DIM, border_color=BORDER, border_width=1,
            height=28, width=32, corner_radius=7,
            command=lambda idx=i: self._delete_action(idx),
        ).grid(row=0, column=6, padx=(0, 8))

    # ── Badges and text helpers ───────────────────────────────────────────────

    def _badge(self, event: str) -> tuple[str, str, str]:
        if event == "ocr_check":
            return "OCR", _OCR_TXT, _OCR_BG
        if event == "click":
            return "CLK", _CLK_TXT, _CLK_BG
        if event == "press":
            return "▼ KEY", ACCENT, BG
        if event == "release":
            return "▲ KEY", TEXT_DIM, BG
        return event.upper()[:4], TEXT_MD, ELEVATED

    def _info_str(self, action: dict) -> str:
        event = action.get("event", "")
        if event == "ocr_check":
            return "📸  Scan for Shiny here"
        if event == "click":
            return f"🖱  ({action.get('x', 0)}, {action.get('y', 0)})  {action.get('button', 'left')}"
        disp = action.get("display") or action.get("key", "?")
        return f"{disp}   ({event})"

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def _delete_action(self, idx: int) -> None:
        del self._actions[idx]
        self._render_actions()

    def _insert_at(self, pos: int) -> None:
        """Insert a new placeholder action at pos, then open its edit form."""
        new_action = {"key": "?", "event": "press", "time": 0.0, "display": "?"}
        self._actions.insert(pos, new_action)
        self._render_actions()
        # Open the edit form for the newly inserted row
        self.after(50, lambda: self._open_edit_by_idx(pos))

    def _add_action(self) -> None:
        self._insert_at(len(self._actions))

    # ── Inline Edit ───────────────────────────────────────────────────────────

    def _open_edit(self, idx: int, row_widget: ctk.CTkFrame) -> None:
        """Show the inline edit sub-form below the given row."""
        # Close any existing edit form first
        if self._editing_idx is not None and self._editing_idx != idx:
            self._render_actions()
            self.after(10, lambda: self._open_edit_by_idx(idx))
            return
        self._editing_idx = idx
        action = self._actions[idx]
        event  = action.get("event", "press")

        form = ctk.CTkFrame(self.action_frame, fg_color=SURFACE,
                            corner_radius=7, border_width=1, border_color=BORDER)
        form.pack(fill="x", padx=8, pady=(0, 4))
        form.grid_columnconfigure(1, weight=1)

        if event == "ocr_check":
            self._build_ocr_edit(form, idx, action)
        elif event == "click":
            self._build_click_edit(form, idx, action)
        else:
            self._build_key_edit(form, idx, action)

    def _open_edit_by_idx(self, idx: int) -> None:
        """Re-render and open edit form for the given index."""
        self._render_actions()
        # Find the row widget and open edit
        children = [
            w for w in self.action_frame.winfo_children()
            if isinstance(w, ctk.CTkFrame)
        ]
        # children includes both rows and any edit forms
        # After render, rows alternate with insert buttons
        # Each real row: insert_btn, row_frame, insert_btn, row_frame, ...
        row_frames = [
            w for w in self.action_frame.winfo_children()
            if isinstance(w, ctk.CTkFrame)
        ]
        if idx < len(row_frames):
            self._open_edit(idx, row_frames[idx])

    def _time_row(self, parent: ctk.CTkFrame, action: dict, col_offset: int = 0):
        """Add a Time label + entry to parent, return (entry_widget,)."""
        ctk.CTkLabel(parent, text="Time (s):", font=("Segoe UI", 10),
                     text_color=TEXT_LO).grid(
                         row=0, column=col_offset, padx=(12, 4), pady=10, sticky="w")
        t_entry = ctk.CTkEntry(parent, font=("Consolas", 11), width=90,
                               fg_color=ELEVATED, border_color=BORDER,
                               text_color=TEXT_HI)
        t_entry.insert(0, str(action.get("time", 0.0)))
        t_entry.grid(row=0, column=col_offset + 1, padx=(0, 12), pady=10)
        return t_entry

    def _build_key_edit(self, form, idx: int, action: dict) -> None:
        form.grid_columnconfigure(1, weight=1)
        action_copy = dict(action)

        # Key capture
        ctk.CTkLabel(form, text="Key:", font=("Segoe UI", 10),
                     text_color=TEXT_LO).grid(row=0, column=0, padx=(12, 4), pady=10)

        key_lbl = ctk.CTkLabel(
            form,
            text=action_copy.get("display") or action_copy.get("key", "?"),
            font=("Consolas", 13, "bold"),
            text_color=ACCENT, fg_color=BG, corner_radius=5, width=70, height=30)
        key_lbl.grid(row=0, column=1, padx=(0, 8), pady=10)

        def _capture():
            key_lbl.configure(text="…", text_color=TEXT_DIM)
            self.app.recorder.capture_next_key(_on_captured)

        def _on_captured(key):
            from core.settings import key_display
            disp = key_display(key)
            action_copy["key"]     = str(key)
            action_copy["display"] = disp
            self.after(0, lambda: key_lbl.configure(
                text=disp, text_color=ACCENT))

        ctk.CTkButton(
            form, text="Capture Key",
            font=("Segoe UI", 10),
            fg_color=ELEVATED, hover_color=BORDER,
            text_color=TEXT_LO, border_color=BORDER, border_width=1,
            height=30, width=100, corner_radius=7,
            command=_capture,
        ).grid(row=0, column=2, padx=(0, 16), pady=10)

        t_entry = self._time_row(form, action_copy, col_offset=3)

        self._edit_footer(form, idx, action_copy, t_entry, col=5)

    def _build_click_edit(self, form, idx: int, action: dict) -> None:
        action_copy = dict(action)

        for col, (lbl, key, w) in enumerate([
            ("X:", "x", 70), ("Y:", "y", 70),
        ]):
            ctk.CTkLabel(form, text=lbl, font=("Segoe UI", 10),
                         text_color=TEXT_LO).grid(row=0, column=col*2, padx=(12, 4), pady=10)
            e = ctk.CTkEntry(form, font=("Consolas", 11), width=w,
                             fg_color=ELEVATED, border_color=BORDER, text_color=TEXT_HI)
            e.insert(0, str(action_copy.get(key, 0)))
            e.grid(row=0, column=col*2 + 1, padx=(0, 8), pady=10)
            # store reference
            if key == "x":
                x_entry = e
            else:
                y_entry = e

        t_entry = self._time_row(form, action_copy, col_offset=4)

        def _apply():
            try:
                action_copy["x"]    = int(x_entry.get())
                action_copy["y"]    = int(y_entry.get())
                action_copy["time"] = float(t_entry.get())
            except ValueError:
                messagebox.showerror("Invalid value", "X, Y must be integers.", parent=self)
                return
            self._actions[idx] = action_copy
            self._render_actions()

        self._edit_footer(form, idx, action_copy, t_entry, col=6,
                          apply_fn=lambda: _apply())

    def _build_ocr_edit(self, form, idx: int, action: dict) -> None:
        action_copy = dict(action)
        region_lbl  = [None]  # mutable ref

        ctk.CTkLabel(form, text="Region:", font=("Segoe UI", 10),
                     text_color=TEXT_LO).grid(row=0, column=0, padx=(12, 4), pady=10)

        cur_region = self.app.detector.get_ocr_region()
        region_txt = (
            f"({cur_region[0]}, {cur_region[1]})  {cur_region[2]}×{cur_region[3]} px"
            if cur_region else "No region"
        )
        region_lbl[0] = ctk.CTkLabel(
            form, text=region_txt, font=("Consolas", 10),
            text_color=_OCR_TXT, fg_color=_OCR_BG, corner_radius=5,
            width=220)
        region_lbl[0].grid(row=0, column=1, padx=(0, 8), pady=10)

        def _select_region():
            # Release modal grab so RegionSelector can receive mouse events
            try:
                self.grab_release()
            except Exception:
                pass
            self.withdraw()
            self.after(350, _open_sel)

        def _open_sel():
            from ui.region_selector import RegionSelector
            # Use the main app window as master, NOT self (dialog has grab)
            RegionSelector(
                self.app,
                callback=_on_region_selected,
                instruction="Drag to select the Pokémon name bar  •  ESC to cancel",
            )

        def _on_region_selected(region):
            self.deiconify()
            self.lift()
            self.focus_force()
            # Restore modal grab
            try:
                self.grab_set()
            except Exception:
                pass
            if region is None:
                return
            x, y, w, h = region
            self.app.detector.set_ocr_region(x, y, w, h)
            # Also persist to settings
            from core import settings as cfg
            data = cfg.load()
            data["ocr_region"] = [x, y, w, h]
            cfg.save(data)
            region_lbl[0].configure(
                text=f"({x}, {y})  {w}\u00d7{h} px", text_color=_OCR_TXT)

        ctk.CTkButton(
            form, text="Select Region",
            font=("Segoe UI", 10),
            fg_color=_OCR_BG, hover_color="#145252",
            text_color=_OCR_TXT, border_color=_OCR_BD, border_width=1,
            height=30, width=110, corner_radius=7,
            command=_select_region,
        ).grid(row=0, column=2, padx=(0, 16), pady=10)

        t_entry = self._time_row(form, action_copy, col_offset=3)
        self._edit_footer(form, idx, action_copy, t_entry, col=5)

    def _edit_footer(
        self,
        form,
        idx: int,
        action_copy: dict,
        t_entry,
        col: int,
        apply_fn=None,
    ) -> None:
        """Adds Apply/Cancel buttons at the end of an edit form row."""

        def _default_apply():
            try:
                action_copy["time"] = float(t_entry.get())
            except ValueError:
                messagebox.showerror("Invalid time", "Time must be a number.", parent=self)
                return
            self._actions[idx] = action_copy
            self._render_actions()

        ctk.CTkButton(
            form, text="✓ Apply",
            font=("Segoe UI", 10, "bold"),
            fg_color=ACCENT, hover_color=ACCENT_H, text_color=BG,
            height=30, width=76, corner_radius=7,
            command=apply_fn or _default_apply,
        ).grid(row=0, column=col, padx=(0, 4), pady=10)

        ctk.CTkButton(
            form, text="✕",
            font=("Segoe UI", 10),
            fg_color="transparent", hover_color=ELEVATED,
            text_color=TEXT_DIM, border_color=BORDER, border_width=1,
            height=30, width=32, corner_radius=7,
            command=self._render_actions,
        ).grid(row=0, column=col + 1, padx=(0, 12), pady=10)

    # ── Drag-to-reorder ───────────────────────────────────────────────────────

    def _drag_start(self, event: tk.Event, idx: int) -> None:
        self._drag_idx    = idx
        self._drag_target = idx

    def _drag_motion(self, event: tk.Event, idx: int) -> None:
        if self._drag_idx is None:
            return
        # Determine target row from y position relative to scroll canvas
        y_root   = event.y_root
        rows     = self._get_row_widgets()
        target   = len(rows)  # default: drop at end
        for j, rw in enumerate(rows):
            ry = rw.winfo_rooty()
            rh = rw.winfo_height()
            if y_root < ry + rh // 2:
                target = j
                break
        self._drag_target = target
        # Visual: change cursor of all handles
        for j, rw in enumerate(rows):
            color = ACCENT if j == target else TEXT_DIM
            for child in rw.winfo_children():
                if isinstance(child, ctk.CTkLabel) and child.cget("text") == "≡":
                    try:
                        child.configure(text_color=color)
                    except Exception:
                        pass

    def _drag_end(self, event: tk.Event, idx: int) -> None:
        if self._drag_idx is None:
            return
        src = self._drag_idx
        dst = self._drag_target
        self._drag_idx = None

        if src != dst and 0 <= src < len(self._actions):
            item = self._actions.pop(src)
            insert_at = dst if dst <= src else dst - 1
            self._actions.insert(max(0, min(insert_at, len(self._actions))), item)

        self._render_actions()

    def _get_row_widgets(self) -> list:
        """Return only CTkFrame children (action rows, not insert buttons)."""
        return [
            w for w in self.action_frame.winfo_children()
            if isinstance(w, ctk.CTkFrame) and w.cget("height") != 16
        ]

    # ── Save ─────────────────────────────────────────────────────────────────

    def _save(self) -> None:
        new_name = self.name_entry.get().strip()
        if not new_name:
            messagebox.showwarning("Name Required", "Please enter a sequence name.", parent=self)
            return

        presses = [a for a in self._actions
                   if a.get("event") in ("press", "click")]
        step_count = len(presses)
        times      = [a.get("time", 0.0) for a in self._actions]
        total_time = round(max(times), 2) if times else 0.0

        seq_out = {
            "name":       new_name,
            "actions":    self._actions,
            "step_count": step_count,
            "total_time": total_time,
        }

        # Rename: if name changed, delete old file
        old_name = self._seq.get("name", "")
        if old_name and old_name != new_name:
            old_file = DATA_DIR / f"{old_name}.json"
            if old_file.exists():
                old_file.unlink()

        out_path = DATA_DIR / f"{new_name}.json"
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(seq_out, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            messagebox.showerror("Save Error", str(exc), parent=self)
            return

        if self._on_save:
            self._on_save()

        self.destroy()
