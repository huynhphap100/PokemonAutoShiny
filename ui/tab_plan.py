"""
ui/tab_plan.py — Hunt Plan Builder tab (Node Graph edition).

Left  : available saved sequences (click to add as a node)
Center: PlanGraphWidget — shader-graph style node canvas
Bottom: loops / jitter / start / stop controls
"""
from __future__ import annotations

import json
import re
import tkinter as tk
from typing import TYPE_CHECKING, Optional

import customtkinter as ctk

from core.plan_runner import PlanRunner
from core.debug_log   import dlog
from ui.condition_editor import ConditionEditorDialog
from ui.plan_graph       import PlanGraphWidget
from core.paths          import MOVES_DIR as DATA_DIR, PLANS_DIR

if TYPE_CHECKING:
    from ui.app import App



# ── Palette ───────────────────────────────────────────────────────────────────
SURFACE  = "#0F1923"
ELEVATED = "#182433"
CARD     = "#162030"
BORDER   = "#1E3050"
TEXT_HI  = "#E2EAF4"
TEXT_LO  = "#7B93AF"
TEXT_DIM = "#4A6076"
ACCENT   = "#1E7FD8"
GREEN    = "#22C55E"
GOLD     = "#FFD700"
RED      = "#EF4444"
ORANGE   = "#F97316"


class PlanTab(ctk.CTkFrame):
    """🎯 Hunt Plan tab — node graph edition."""

    def __init__(self, master, app: "App") -> None:
        super().__init__(master, fg_color="transparent", corner_radius=0)
        self.app = app

        self._available: list[dict] = []   # loaded sequence dicts

        # Plan runner
        self.runner: Optional[PlanRunner] = None

        self._build_ui()
        self._load_sequences()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)
        self.grid_columnconfigure(0, weight=0, minsize=175)
        self.grid_columnconfigure(1, weight=1)

        # ── Left: tabbed sequences + plans ────────────────────────────────────
        left = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10,
                            border_width=1, border_color=BORDER)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=0)
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)

        tabs = ctk.CTkTabview(
            left, fg_color=CARD,
            segmented_button_fg_color=ELEVATED,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color="#1460a8",
            segmented_button_unselected_color=ELEVATED,
            segmented_button_unselected_hover_color=BORDER,
            text_color=TEXT_HI,
        )
        tabs.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        tabs.add("📂 Sequences")
        tabs.add("📋 Plans")

        # ── Tab 1: Sequences ──────────────────────────────────────────────────
        t1 = tabs.tab("📂 Sequences")
        t1.grid_rowconfigure(0, weight=1)
        t1.grid_columnconfigure(0, weight=1)

        self._seq_scroll = ctk.CTkScrollableFrame(
            t1, fg_color="transparent", scrollbar_button_color=BORDER)
        self._seq_scroll.grid(row=0, column=0, sticky="nsew", padx=2, pady=(2, 4))
        self._seq_scroll.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            t1, text="↺  Refresh sequences", height=28,
            fg_color=ELEVATED, hover_color=BORDER,
            text_color=TEXT_LO, font=("Segoe UI", 11),
            command=self._load_sequences,
        ).grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 4))

        # ── Tab 2: Saved Plans ────────────────────────────────────────────────
        t2 = tabs.tab("📋 Plans")
        t2.grid_rowconfigure(0, weight=1)
        t2.grid_columnconfigure(0, weight=1)

        self._plans_scroll = ctk.CTkScrollableFrame(
            t2, fg_color="transparent", scrollbar_button_color=BORDER)
        self._plans_scroll.grid(row=0, column=0, sticky="nsew", padx=2, pady=(2, 4))
        self._plans_scroll.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            t2, text="↺  Refresh", height=28,
            fg_color=ELEVATED, hover_color=BORDER,
            text_color=TEXT_LO, font=("Segoe UI", 11),
            command=self._load_plans_list,
        ).grid(row=1, column=0, sticky="ew", padx=4, pady=(0, 4))

        self._load_plans_list()

        # ── Center: node graph canvas ──────────────────────────────────────────
        self._graph = PlanGraphWidget(
            self,
            on_edit_condition=self._open_condition_editor,
            on_node_dblclick=self._open_node_settings,
            on_changed=self._on_graph_changed,
        )
        self._graph.set_add_seq_callback(self._prompt_add_seq)
        self._graph.grid(row=0, column=1, sticky="nsew")

        # ── Bottom bar ─────────────────────────────────────────────────────────
        bot = ctk.CTkFrame(self, fg_color=CARD, corner_radius=10,
                           border_width=1, border_color=BORDER, height=72)
        bot.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        bot.grid_propagate(False)
        bot.grid_columnconfigure(8, weight=1)

        # Plan name entry (left side of bottom bar)
        ctk.CTkLabel(bot, text="📋 Plan:",
                     font=("Segoe UI", 11), text_color=TEXT_LO,
                     ).grid(row=0, column=0, padx=(12, 4), pady=18)
        self._plan_name_var = tk.StringVar(value="my_plan")
        ctk.CTkEntry(
            bot, textvariable=self._plan_name_var,
            width=120, height=32, justify="left",
            placeholder_text="plan name…",
            font=("Segoe UI", 11), fg_color=ELEVATED, border_color=BORDER,
        ).grid(row=0, column=1, pady=18)

        ctk.CTkLabel(bot, text="🔁  Loops:",
                     font=("Segoe UI", 12), text_color=TEXT_LO,
                     ).grid(row=0, column=2, padx=(14, 4), pady=18)
        self._loops_var   = tk.StringVar(value="1")
        self._loops_entry = ctk.CTkEntry(
            bot, textvariable=self._loops_var,
            width=54, height=32, justify="center",
            font=("Segoe UI", 12), fg_color=ELEVATED, border_color=BORDER,
        )
        self._loops_entry.grid(row=0, column=3, pady=18)

        ctk.CTkButton(bot, text="−", width=28, height=32,
                      fg_color=ELEVATED, hover_color=BORDER,
                      text_color=TEXT_HI, font=("Segoe UI", 14),
                      command=lambda: self._adj_loops(-1),
                      ).grid(row=0, column=4, padx=(2, 0), pady=18)
        ctk.CTkButton(bot, text="+", width=28, height=32,
                      fg_color=ELEVATED, hover_color=BORDER,
                      text_color=TEXT_HI, font=("Segoe UI", 14),
                      command=lambda: self._adj_loops(+1),
                      ).grid(row=0, column=5, padx=(2, 0), pady=18)

        self._inf_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            bot, text="∞ Continuous", variable=self._inf_var,
            font=("Segoe UI", 12), text_color=TEXT_LO,
            fg_color=ACCENT, hover_color=BORDER,
            command=self._on_inf_toggle,
        ).grid(row=0, column=6, padx=(14, 0), pady=18)

        # Jitter
        ctk.CTkFrame(bot, fg_color=BORDER, width=1, height=42
                     ).grid(row=0, column=7, padx=(14, 12), pady=15, sticky="ns")
        ctk.CTkLabel(bot, text="⚡ Jitter:",
                     font=("Segoe UI", 11), text_color=TEXT_LO,
                     ).grid(row=0, column=8, padx=(0, 4), pady=18)

        jf = ctk.CTkFrame(bot, fg_color="transparent")
        jf.grid(row=0, column=9, pady=18, padx=(0, 8))
        ctk.CTkLabel(jf, text="min", font=("Segoe UI", 9),
                     text_color=TEXT_DIM).grid(row=0, column=0, padx=(0, 2))
        self._jitter_min_var = tk.StringVar(value="0")
        ctk.CTkEntry(jf, textvariable=self._jitter_min_var,
                     width=52, height=28, justify="center",
                     font=("Segoe UI", 11), fg_color=ELEVATED,
                     border_color=BORDER).grid(row=0, column=1, padx=(0, 6))
        ctk.CTkLabel(jf, text="max", font=("Segoe UI", 9),
                     text_color=TEXT_DIM).grid(row=0, column=2, padx=(0, 2))
        self._jitter_max_var = tk.StringVar(value="0")
        ctk.CTkEntry(jf, textvariable=self._jitter_max_var,
                     width=52, height=28, justify="center",
                     font=("Segoe UI", 11), fg_color=ELEVATED,
                     border_color=BORDER).grid(row=0, column=3, padx=(0, 4))
        ctk.CTkLabel(jf, text="ms", font=("Segoe UI", 9),
                     text_color=TEXT_DIM).grid(row=0, column=4)

        self._status_lbl = ctk.CTkLabel(
            bot, text="Ready", font=("Segoe UI", 11), text_color=TEXT_DIM)
        self._status_lbl.grid(row=0, column=10, padx=12, pady=18, sticky="w")

        ctk.CTkButton(
            bot, text="💾  Save Plan", height=36, width=110,
            fg_color=ELEVATED, hover_color=BORDER,
            text_color=TEXT_LO, font=("Segoe UI", 12),
            border_color=BORDER, border_width=1,
            command=self._save_plan,
        ).grid(row=0, column=11, padx=(0, 6), pady=18)

        self._start_btn = ctk.CTkButton(
            bot, text="▶  Start Plan", height=36, width=130,
            fg_color=GREEN, hover_color="#16a34a",
            text_color="#FFFFFF", font=("Segoe UI", 13, "bold"),
            command=self._start_plan,
        )
        self._start_btn.grid(row=0, column=12, padx=(0, 6), pady=18)

        self._stop_btn = ctk.CTkButton(
            bot, text="⏹  Stop", height=36, width=90,
            fg_color=ELEVATED, hover_color="#3A1515",
            text_color=TEXT_LO, font=("Segoe UI", 12),
            command=self._stop_plan, state="disabled",
        )
        self._stop_btn.grid(row=0, column=13, padx=(0, 12), pady=18)

    # ── Sequence loading ───────────────────────────────────────────────────────

    def _load_sequences(self) -> None:
        for w in self._seq_scroll.winfo_children():
            w.destroy()
        self._available.clear()
        files = sorted(DATA_DIR.glob("*.json"))
        if not files:
            ctk.CTkLabel(self._seq_scroll, text="No sequences found",
                         font=("Segoe UI", 11), text_color=TEXT_DIM,
                         ).grid(row=0, column=0, pady=20)
            return
        for i, f in enumerate(files):
            try:
                seq = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if "name" not in seq:
                seq["name"] = f.stem
            self._available.append(seq)
            self._build_seq_chip(i, seq)

    def _build_seq_chip(self, row: int, seq: dict) -> None:
        name  = seq.get("name", "?")
        n_act = len(seq.get("actions", []))
        has_ocr = any(a.get("event") == "ocr_check" for a in seq.get("actions", []))

        chip = ctk.CTkFrame(self._seq_scroll, fg_color=ELEVATED,
                            corner_radius=8, cursor="hand2")
        chip.grid(row=row, column=0, sticky="ew", padx=4, pady=3)
        chip.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(chip,
                     text=f"🎬  {name}" + ("  🔍" if has_ocr else ""),
                     font=("Segoe UI", 12, "bold"), text_color=TEXT_HI,
                     anchor="w").grid(row=0, column=0, sticky="w", padx=10, pady=(6, 1))
        ctk.CTkLabel(chip, text=f"{n_act} actions",
                     font=("Segoe UI", 10), text_color=TEXT_DIM,
                     anchor="w").grid(row=1, column=0, sticky="w", padx=10, pady=(0, 5))
        ctk.CTkLabel(chip, text="+", font=("Segoe UI", 16, "bold"),
                     text_color=ACCENT, width=24,
                     ).grid(row=0, column=1, rowspan=2, padx=(0, 10))

        for w in [chip] + list(chip.winfo_children()):
            w.bind("<Button-1>", lambda e, s=seq: self._add_step(s))
            w.bind("<Enter>",    lambda e, c=chip: c.configure(fg_color=BORDER))
            w.bind("<Leave>",    lambda e, c=chip: c.configure(fg_color=ELEVATED))

    # ── Step / node management ─────────────────────────────────────────────────

    def _add_step(self, seq: dict) -> None:
        """Add sequence as a new node in the graph."""
        self._graph.add_node({
            "seq":       seq,
            "name":      seq.get("name", "?"),
            "repeats":   1,
            "delay":     0.5,
            "condition": None,
            "next":      None,
        })

    def _prompt_add_seq(self) -> None:
        """Called by ⊕ button in graph toolbar — focus left panel."""
        self.app.show_toast("👈 Click a sequence in the left panel to add it", ACCENT)

    def _on_graph_changed(self) -> None:
        """Called whenever graph nodes/connections change."""
        pass  # future: auto-save, dirty flag

    # ── Condition editor ───────────────────────────────────────────────────────

    def _open_condition_editor(self, node_idx: int) -> None:
        nodes = self._graph.nodes
        if not 0 <= node_idx < len(nodes):
            return
        node  = nodes[node_idx]
        names = [n.get("name", f"#{i+1}") for i, n in enumerate(nodes)]

        def _on_save(new_cond):
            node["condition"] = new_cond
            self._graph._canvas._redraw()

        ConditionEditorDialog(
            self, step_names=names,
            condition=node.get("condition"),
            on_save=_on_save,
        )

    # ── Node settings popup (double-click) ────────────────────────────────────

    def _open_node_settings(self, node_idx: int) -> None:
        nodes = self._graph.nodes
        if not 0 <= node_idx < len(nodes):
            return
        node = nodes[node_idx]
        self._build_node_settings_popup(node_idx, node)

    def _build_node_settings_popup(self, idx: int, node: dict) -> None:
        popup = ctk.CTkToplevel(self)
        popup.title(f"⚙  Node #{idx+1} — {node.get('name','?')}")
        popup.geometry("360x260")
        popup.resizable(False, False)
        popup.configure(fg_color="#0F1923")
        popup.attributes("-topmost", True)
        popup.grab_set()

        ctk.CTkLabel(popup, text=f"🎬  {node.get('name','?')}",
                     font=("Segoe UI", 13, "bold"), text_color=TEXT_HI,
                     ).pack(pady=(16, 4), padx=20, anchor="w")

        body = ctk.CTkFrame(popup, fg_color="#182433", corner_radius=10)
        body.pack(fill="x", padx=16, pady=8)
        body.grid_columnconfigure(1, weight=1)

        # Repeats
        ctk.CTkLabel(body, text="× Repeats:", font=("Segoe UI", 11),
                     text_color=TEXT_LO).grid(row=0, column=0, sticky="w",
                                               padx=12, pady=(12, 6))
        rep_var = tk.StringVar(value=str(node.get("repeats", 1)))
        rep_f = ctk.CTkFrame(body, fg_color="transparent")
        rep_f.grid(row=0, column=1, sticky="w", padx=8)
        ctk.CTkButton(rep_f, text="−", width=28, height=28,
                      fg_color=CARD, hover_color=BORDER, text_color=TEXT_HI,
                      font=("Segoe UI", 13),
                      command=lambda: rep_var.set(str(max(1, int(rep_var.get())-1))),
                      ).pack(side="left")
        rep_lbl = ctk.CTkLabel(rep_f, textvariable=rep_var, width=40,
                               font=("Segoe UI", 12, "bold"), text_color=TEXT_HI)
        rep_lbl.pack(side="left", padx=4)
        ctk.CTkButton(rep_f, text="+", width=28, height=28,
                      fg_color=CARD, hover_color=BORDER, text_color=TEXT_HI,
                      font=("Segoe UI", 13),
                      command=lambda: rep_var.set(str(int(rep_var.get())+1)),
                      ).pack(side="left")

        # Delay
        ctk.CTkLabel(body, text="⏱ Delay (s):", font=("Segoe UI", 11),
                     text_color=TEXT_LO).grid(row=1, column=0, sticky="w",
                                               padx=12, pady=(0, 12))
        delay_var = tk.StringVar(value=f"{node.get('delay', 0.5):.1f}")
        delay_f = ctk.CTkFrame(body, fg_color="transparent")
        delay_f.grid(row=1, column=1, sticky="w", padx=8)
        ctk.CTkButton(delay_f, text="−", width=28, height=28,
                      fg_color=CARD, hover_color=BORDER, text_color=TEXT_HI,
                      font=("Segoe UI", 13),
                      command=lambda: delay_var.set(
                          f"{max(0.0, round(float(delay_var.get())-0.5, 1)):.1f}"),
                      ).pack(side="left")
        ctk.CTkLabel(delay_f, textvariable=delay_var, width=48,
                     font=("Segoe UI", 12, "bold"), text_color=TEXT_LO,
                     ).pack(side="left", padx=4)
        ctk.CTkButton(delay_f, text="+", width=28, height=28,
                      fg_color=CARD, hover_color=BORDER, text_color=TEXT_HI,
                      font=("Segoe UI", 13),
                      command=lambda: delay_var.set(
                          f"{round(float(delay_var.get())+0.5, 1):.1f}"),
                      ).pack(side="left")

        # Buttons
        btn_row = ctk.CTkFrame(popup, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=8)

        ctk.CTkButton(btn_row, text="⚡  Edit Condition", height=34,
                      fg_color=ORANGE, hover_color="#c2570a",
                      text_color="#FFF", font=("Segoe UI", 11, "bold"),
                      command=lambda: (popup.destroy(),
                                       self._open_condition_editor(idx)),
                      ).pack(side="left", padx=(0, 8))

        def _save():
            node["repeats"] = max(1, int(rep_var.get()))
            node["delay"]   = max(0.0, float(delay_var.get()))
            self._graph._canvas._redraw()
            popup.destroy()

        ctk.CTkButton(btn_row, text="💾  Save", height=34,
                      fg_color=GREEN, hover_color="#16a34a",
                      text_color="#FFF", font=("Segoe UI", 12, "bold"),
                      command=_save,
                      ).pack(side="right")

    # ── Loops controls ─────────────────────────────────────────────────────────

    def _adj_loops(self, delta: int) -> None:
        try:
            v = int(self._loops_var.get())
        except ValueError:
            v = 1
        self._loops_var.set(str(max(1, v + delta)))

    def _on_inf_toggle(self) -> None:
        self._loops_entry.configure(
            state="disabled" if self._inf_var.get() else "normal")

    # ── Runner helpers ─────────────────────────────────────────────────────────

    def _get_jitter(self) -> tuple[int, int]:
        try:
            lo = max(0, int(self._jitter_min_var.get()))
        except ValueError:
            lo = 0
        try:
            hi = max(lo, int(self._jitter_max_var.get()))
        except ValueError:
            hi = lo
        return lo, hi

    # ── Plan start / stop ──────────────────────────────────────────────────────

    def _start_plan(self) -> None:
        steps = self._graph.get_steps()
        if not steps:
            self.app.show_toast("Graph is empty — add sequences first!", RED)
            return
        if self.runner and self.runner.is_running:
            return

        total = 0 if self._inf_var.get() else max(1, int(self._loops_var.get() or 1))
        jitter_min, jitter_max = self._get_jitter()

        self.runner = PlanRunner(self.app.player, self.app.detector)
        self.runner.on_started   = self._cb_started
        self.runner.on_step      = self._cb_step
        self.runner.on_ocr       = self._cb_ocr
        self.runner.on_shiny     = self._cb_shiny
        self.runner.on_stopped   = self._cb_stopped
        self.runner.on_condition = self._cb_condition
        if hasattr(self.runner, "set_jitter"):
            self.runner.set_jitter(jitter_min, jitter_max)

        hwnd = self.app.target_hwnd
        dlog(f"[plan tab] start nodes={len(steps)} loops={total} "
             f"jitter={jitter_min}-{jitter_max}ms")
        self.runner.start(steps, total, hwnd)

    def _stop_plan(self) -> None:
        if self.runner:
            self.runner.stop()

    # ── Save Plan ──────────────────────────────────────────────────────────────

    def _save_plan(self) -> None:
        steps = self._graph.get_steps()
        if not steps:
            self.app.show_toast("Graph is empty — nothing to save!", RED)
            return

        name = self._plan_name_var.get().strip()
        if not name:
            self.app.show_toast("⚠ Enter a plan name first", ORANGE)
            return

        # Sanitise name — keep letters, digits, spaces, hyphens, underscores
        safe = re.sub(r"[^\w\s\-]", "", name).strip().replace(" ", "_") or "my_plan"
        self._plan_name_var.set(safe)

        jitter_min, jitter_max = self._get_jitter()
        try:
            loops = 0 if self._inf_var.get() else max(1, int(self._loops_var.get() or 1))
        except ValueError:
            loops = 1

        payload = {
            "name":          safe,
            "loops":         loops,
            "continuous":    self._inf_var.get(),
            "jitter_min_ms": jitter_min,
            "jitter_max_ms": jitter_max,
            "nodes": [
                {k: v for k, v in s.items()}
                for s in steps
            ],
        }

        PLANS_DIR.mkdir(parents=True, exist_ok=True)
        path = PLANS_DIR / f"{safe}.json"
        try:
            path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8")
            self.app.show_toast(f"💾 Saved → {safe}.json", GREEN)
            self._load_plans_list()
        except Exception as exc:
            self.app.show_toast(f"Save failed: {exc}", RED)

    # ── Saved plans list ───────────────────────────────────────────────────────

    def _load_plans_list(self) -> None:
        """Refresh the Saved Plans panel in the left sidebar."""
        for w in self._plans_scroll.winfo_children():
            w.destroy()

        plans = sorted(PLANS_DIR.glob("*.json")) if PLANS_DIR.exists() else []
        if not plans:
            ctk.CTkLabel(
                self._plans_scroll,
                text="No saved plans yet",
                font=("Segoe UI", 9), text_color=TEXT_DIM,
            ).pack(padx=8, pady=6)
            return

        for p in plans:
            self._build_plan_row(p)

    def _build_plan_row(self, path) -> None:
        row = ctk.CTkFrame(self._plans_scroll, fg_color=ELEVATED,
                           corner_radius=6, border_width=1, border_color=BORDER)
        row.pack(fill="x", padx=4, pady=3)
        row.grid_columnconfigure(0, weight=1)

        name = path.stem
        ctk.CTkButton(
            row, text=f"📋 {name}", anchor="w", height=28,
            fg_color="transparent", hover_color=BORDER,
            text_color=TEXT_HI, font=("Segoe UI", 10),
            command=lambda p=path: self._load_plan(p),
        ).grid(row=0, column=0, sticky="ew", padx=2)

        ctk.CTkButton(
            row, text="🗑", width=26, height=28,
            fg_color="transparent", hover_color="#3A0D0D",
            text_color=TEXT_DIM, font=("Segoe UI", 10),
            command=lambda p=path: self._delete_plan(p),
        ).grid(row=0, column=1, padx=(0, 2))

    def _load_plan(self, path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self.app.show_toast(f"Load failed: {exc}", RED)
            return

        # Restore name + settings
        self._plan_name_var.set(data.get("name", path.stem))
        if not self._inf_var.get():
            self._loops_var.set(str(data.get("loops", 1)))

        # Load nodes into graph (new key "nodes", fallback "steps")
        nodes = data.get("nodes") or data.get("steps") or []
        self._graph.load_steps(nodes)
        self.app.show_toast(f"📂 Loaded: {path.stem}", GREEN)

    def _delete_plan(self, path) -> None:
        try:
            path.unlink()
            self.app.show_toast(f"🗑 Deleted: {path.stem}", ORANGE)
            self._load_plans_list()
        except Exception as exc:
            self.app.show_toast(f"Delete failed: {exc}", RED)

    # ── Runner callbacks (background → main thread) ────────────────────────────

    def _cb_started(self)                                        -> None: self.after(0, self._ui_started)
    def _cb_step(self, i, r, l)                                  -> None: self.after(0, self._ui_step, i, r, l)
    def _cb_ocr(self, l, is_s, t)                                -> None: self.after(0, self._ui_ocr, l, is_s, t)
    def _cb_shiny(self, l, t)                                    -> None: self.after(0, self._ui_shiny, l, t)
    def _cb_stopped(self)                                        -> None: self.after(0, self._ui_stopped)
    def _cb_condition(self, si, m, c, ni)                        -> None: self.after(0, self._ui_condition, si, m, c, ni)

    # ── Main-thread UI updates ─────────────────────────────────────────────────

    def _ui_started(self) -> None:
        self._start_btn.configure(state="disabled", fg_color="#1a5c2e")
        self._stop_btn.configure(state="normal", fg_color=RED,
                                 hover_color="#a11c1c", text_color="#FFF")
        self._status_lbl.configure(text="▶ Running…", text_color=GREEN)

    def _ui_step(self, step_idx: int, repeat_n: int, loop_n: int) -> None:
        nodes = self._graph.nodes
        name  = nodes[step_idx].get("name", "?") if step_idx < len(nodes) else "?"
        reps  = nodes[step_idx].get("repeats", 1) if step_idx < len(nodes) else "?"
        self._status_lbl.configure(
            text=f"Loop {loop_n}  ›  {name} ({repeat_n+1}/{reps})",
            text_color=TEXT_LO)
        self._graph.highlight_node(step_idx)

    def _ui_ocr(self, loop_n: int, is_shiny: bool, text: str) -> None:
        display = (text or "").replace("\n", " ").strip()[:50] or "(no text)"
        color   = GOLD if is_shiny else TEXT_DIM
        self._status_lbl.configure(text=f"OCR: {display}", text_color=color)
        self.app.show_toast(f"📸 OCR: {display}", color)

    def _ui_shiny(self, loop_n: int, text: str) -> None:
        self.app.show_toast("✨ SHINY DETECTED! Plan stopped!", GOLD)
        self._status_lbl.configure(text="✨ SHINY!", text_color=GOLD)
        self._ui_stopped()

    def _ui_stopped(self) -> None:
        self._start_btn.configure(state="normal", fg_color=GREEN,
                                  hover_color="#16a34a", text_color="#FFF")
        self._stop_btn.configure(state="disabled", fg_color=ELEVATED,
                                 text_color=TEXT_LO)
        self._graph.clear_highlights()
        if self.runner and not getattr(self.runner, "_shiny_flag", False):
            self._status_lbl.configure(text="✅ Plan finished", text_color=GREEN)

    def _ui_condition(self, step_idx: int, matched: bool,
                      confidence: float, next_idx: int) -> None:
        colour = "#22C55E" if matched else "#EF4444"
        label  = "✅ MATCH" if matched else "❌ NO MATCH"
        self._status_lbl.configure(
            text=f"Cond: {label}  conf={confidence:.2f}  → #{next_idx+1}",
            text_color=colour)

    # ── Called by app when sequences change ───────────────────────────────────

    def refresh_sequences(self) -> None:
        self._load_sequences()
