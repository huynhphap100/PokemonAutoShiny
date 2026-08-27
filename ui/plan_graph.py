"""
ui/plan_graph.py — Node-graph canvas for the Hunt Plan.

Two node types
--------------
SEQ node        : plays a movement sequence
                  ports: ● in (left)  ●→ out (right-centre)

CONDITION node  : evaluates image/OCR check — NO sequence playing
                  ports: ● in (left)  ●✓ true (right-top)
                                      ●✗ false (right-bottom)
                  Created by: right-click canvas → "Add Condition"

Interactions
------------
  Left click + drag on node body       → move node
  Left click + drag from OUTPUT port   → draw bezier wire
  Release on INPUT port                → create connection
  Right-click wire                     → remove connection
  Right-click on canvas bg             → create condition node menu
  Right-click on node                  → edit / delete menu
  Double-click node                    → open settings
  Middle-drag / Space+drag             → pan
  Ctrl+Scroll                          → zoom
"""
from __future__ import annotations

import math
import tkinter as tk
from typing import Callable, Optional

import customtkinter as ctk

# ── Constants ─────────────────────────────────────────────────────────────────
NODE_W   = 200
SEQ_H    = 100
COND_H   = 90
START_H  = 58       # start node (no body, header only)
HDR_H    = 28
PORT_R   = 8
GRID     = 40
MIN_ZOOM = 0.35
MAX_ZOOM = 2.2

# ── Palette ───────────────────────────────────────────────────────────────────
BG           = "#0B1520"
GRID_C       = "#111E2C"
SEQ_BG       = "#182433"
SEQ_HDR      = "#1A3050"
COND_BG      = "#1E1428"
COND_HDR     = "#2D1A48"
START_BG     = "#091A0E"
START_HDR    = "#0E2A16"
START_BORDER = "#22C55E"
NODE_BORDER  = "#1E3A5A"
COND_BORDER  = "#5B21B6"
SEL_BORDER   = "#1E7FD8"
RUN_BORDER   = "#F59E0B"
PORT_IN      = "#7B93AF"
PORT_OUT     = "#7B93AF"
PORT_TRUE    = "#22C55E"
PORT_FALSE   = "#EF4444"
WIRE_OUT     = "#4A6888"
WIRE_TRUE    = "#22C55E"
WIRE_FALSE   = "#EF4444"
WIRE_PEND    = "#F59E0B"
TEXT_HI      = "#E4EFF8"
TEXT_LO      = "#7B93AF"
TEXT_DIM     = "#3D5870"
ORANGE       = "#F97316"
GOLD         = "#F59E0B"
PURPLE       = "#A855F7"
GREEN        = "#22C55E"

# port config: side, rel_y, colour, label
PORT_CFG = {
    "in":    {"side": "left",  "rel_y": 0.50, "col": PORT_IN,   "label": ""},
    "out":   {"side": "right", "rel_y": 0.50, "col": PORT_OUT,  "label": "→"},
    "true":  {"side": "right", "rel_y": 0.33, "col": PORT_TRUE, "label": "✓"},
    "false": {"side": "right", "rel_y": 0.72, "col": PORT_FALSE,"label": "✗"},
}

COND_TYPE_LABELS = {
    "image": ("🖼", "Image Check", WIRE_OUT),
    "ocr":   ("🔤", "OCR Check",   PURPLE),
}


def _node_ports(node: dict) -> list[str]:
    ntype = node.get("node_type", "seq")
    if ntype == "start":     return ["out"]
    if ntype == "condition": return ["in", "true", "false"]
    return ["in", "out"]


def _node_h(node: dict) -> int:
    ntype = node.get("node_type", "seq")
    if ntype == "start":     return START_H
    if ntype == "condition": return COND_H
    return SEQ_H


def _make_start_node(x: float = 80.0, y: float = 160.0) -> dict:
    return {"node_type": "start", "next": None, "x": x, "y": y}


# ─────────────────────────────────────────────────────────────────────────────
class _GraphCanvas(tk.Canvas):
    """Raw tkinter canvas with full node-graph logic."""

    def __init__(self, parent,
                 on_edit_condition: Optional[Callable] = None,
                 on_node_dblclick:  Optional[Callable] = None,
                 on_node_delete:    Optional[Callable] = None,
                 on_changed:        Optional[Callable] = None) -> None:
        super().__init__(parent, bg=BG, highlightthickness=0, cursor="arrow")

        self._nodes: list[dict]  = [_make_start_node()]
        self._selected: set[int] = set()

        self._pan_x = 60.0
        self._pan_y = 80.0
        self._zoom  = 1.0

        self._state       = "idle"
        self._drag_idx    = -1
        self._drag_off    = (0.0, 0.0)
        self._wire_src    = (-1, "")
        self._wire_cur    = (0.0, 0.0)
        self._pan_start: Optional[tuple] = None
        self._space_held  = False
        self._running_idx = -1

        self._on_edit_cond  = on_edit_condition
        self._on_dblclick   = on_node_dblclick
        self._on_delete     = on_node_delete
        self._on_changed    = on_changed
        self._on_zoom_change: Optional[Callable[[float], None]] = None

        self.bind("<ButtonPress-1>",    self._b1_down)
        self.bind("<B1-Motion>",        self._b1_move)
        self.bind("<ButtonRelease-1>",  self._b1_up)
        self.bind("<ButtonPress-2>",    self._b2_down)
        self.bind("<B2-Motion>",        self._b2_move)
        self.bind("<ButtonRelease-2>",  self._b2_up)
        self.bind("<ButtonPress-3>",    self._b3_down)
        self.bind("<Double-Button-1>",  self._dbl)
        self.bind("<MouseWheel>",       self._scroll)
        self.bind("<Configure>",        lambda _: self._redraw())
        self.bind("<Delete>",           lambda _: self._del_selected())
        self.bind("<Key-space>",        lambda _: setattr(self, "_space_held", True))
        self.bind("<KeyRelease-space>", lambda _: setattr(self, "_space_held", False))
        self.focus_set()

    # ── Coord transforms ─────────────────────────────────────────────────────

    def _w2s(self, wx, wy):
        return wx * self._zoom + self._pan_x, wy * self._zoom + self._pan_y

    def _s2w(self, sx, sy):
        return (sx - self._pan_x) / self._zoom, (sy - self._pan_y) / self._zoom

    def _port_world(self, idx: int, port: str) -> tuple[float, float]:
        cfg = PORT_CFG[port]
        n   = self._nodes[idx]
        nx, ny = n["x"], n["y"]
        nh = _node_h(n)
        x = nx if cfg["side"] == "left" else nx + NODE_W
        return x, ny + nh * cfg["rel_y"]

    # ── Hit testing ──────────────────────────────────────────────────────────

    def _hit(self, sx, sy) -> tuple[str, int, str]:
        """Return (kind, node_idx, extra). kind: port|del_btn|cond_btn|node|bg"""
        wx, wy = self._s2w(sx, sy)
        hit_r  = PORT_R * 1.6 / self._zoom
        # Ports first
        for i, n in enumerate(self._nodes):
            for pn in _node_ports(n):
                px, py = self._port_world(i, pn)
                if math.dist((wx, wy), (px, py)) <= hit_r:
                    return "port", i, pn
        # Node buttons
        for i, n in enumerate(self._nodes):
            nx, ny   = n["x"], n["y"]
            nh       = _node_h(n)
            is_start = n.get("node_type") == "start"
            # ✕ delete (not shown on start node)
            if (not is_start and
                    nx + NODE_W - 22 <= wx <= nx + NODE_W - 4 and
                    ny + 4 <= wy <= ny + HDR_H - 4):
                return "del_btn", i, ""
            # ✎ condition / ⚙ settings (only non-start nodes)
            if (not is_start and
                    nx + NODE_W - 40 <= wx <= nx + NODE_W - 22 and
                    ny + HDR_H + 4 <= wy <= ny + nh - 4):
                return "cond_btn", i, ""
            # Node body
            if nx <= wx <= nx + NODE_W and ny <= wy <= ny + nh:
                return "node", i, ""
        return "bg", -1, ""

    def _wire_hit(self, sx, sy, thr=9.0) -> tuple[int, str]:
        wx, wy = self._s2w(sx, sy)
        best_d, best = 1e9, (-1, "")
        for i, n in enumerate(self._nodes):
            for src_port in ("out", "true", "false"):
                dst = self._wire_dst(i, src_port)
                if dst is None: continue
                x1, y1 = self._port_world(i, src_port)
                x2, y2 = self._port_world(dst, "in")
                d = self._bezier_dist(wx, wy, x1, y1, x2, y2)
                if d < best_d: best_d = d; best = (i, src_port)
        return best if best_d <= thr / self._zoom else (-1, "")

    def _wire_dst(self, idx: int, port: str) -> Optional[int]:
        n = self._nodes[idx]
        if port == "out":   v = n.get("next")
        elif port == "true":  v = n.get("on_true")
        elif port == "false": v = n.get("on_false")
        else: return None
        return v if isinstance(v, int) and 0 <= v < len(self._nodes) else None

    @staticmethod
    def _bezier_dist(px, py, x1, y1, x2, y2, steps=20):
        dx = abs(x2 - x1) * 0.55
        best = 1e9
        for k in range(steps + 1):
            t = k / steps; u = 1 - t
            bx = u**3*x1 + 3*u**2*t*(x1+dx) + 3*u*t**2*(x2-dx) + t**3*x2
            by = u**3*y1 + 3*u**2*t*y1       + 3*u*t**2*y2       + t**3*y2
            best = min(best, math.dist((px, py), (bx, by)))
        return best

    # ── Mouse events ─────────────────────────────────────────────────────────

    def _b1_down(self, e: tk.Event) -> None:
        self.focus_set()
        if self._space_held:
            self._state = "pan"; self._pan_start = (e.x, e.y, self._pan_x, self._pan_y)
            self.configure(cursor="fleur"); return

        kind, idx, extra = self._hit(e.x, e.y)

        if kind == "del_btn":
            self._remove_node(idx); return

        if kind == "cond_btn" and self._on_edit_cond:
            self._on_edit_cond(idx); return

        if kind == "port" and extra != "in":
            self._state = "drag_wire"; self._wire_src = (idx, extra)
            self._wire_cur = (e.x, e.y); self.configure(cursor="crosshair"); return

        if kind == "node":
            if idx not in self._selected: self._selected = {idx}
            self._state = "drag_node"; self._drag_idx = idx
            wx, wy = self._s2w(e.x, e.y)
            n = self._nodes[idx]
            self._drag_off = (wx - n["x"], wy - n["y"])
            self.configure(cursor="fleur"); self._redraw(); return

        # Background click: check wire
        wi, wp = self._wire_hit(e.x, e.y)
        if wi >= 0: self._disconnect(wi, wp); return

        self._selected.clear(); self._redraw()

    def _b1_move(self, e: tk.Event) -> None:
        if self._state == "pan":
            ox, oy, px0, py0 = self._pan_start
            self._pan_x = px0 + (e.x - ox); self._pan_y = py0 + (e.y - oy)
            self._redraw(); return
        if self._state == "drag_node":
            wx, wy = self._s2w(e.x, e.y)
            n = self._nodes[self._drag_idx]
            n["x"] = wx - self._drag_off[0]; n["y"] = wy - self._drag_off[1]
            self._redraw(); return
        if self._state == "drag_wire":
            self._wire_cur = (e.x, e.y); self._redraw(); return

    def _b1_up(self, e: tk.Event) -> None:
        self.configure(cursor="arrow")
        prev = self._state; self._state = "idle"
        if prev == "drag_node" and self._on_changed: self._on_changed()
        if prev == "drag_wire":
            kind, dst_idx, port = self._hit(e.x, e.y)
            si, sp = self._wire_src
            if kind == "port" and port == "in" and dst_idx != si:
                self._connect(si, sp, dst_idx)
            self._wire_src = (-1, ""); self._redraw()

    def _b2_down(self, e):
        self._state = "pan"; self._pan_start = (e.x, e.y, self._pan_x, self._pan_y)
        self.configure(cursor="fleur")

    def _b2_move(self, e):
        if self._state == "pan" and self._pan_start:
            ox, oy, px0, py0 = self._pan_start
            self._pan_x = px0+(e.x-ox); self._pan_y = py0+(e.y-oy); self._redraw()

    def _b2_up(self, _):
        self._state = "idle"; self.configure(cursor="arrow")

    def _b3_down(self, e: tk.Event) -> None:
        # Wire hit → remove
        wi, wp = self._wire_hit(e.x, e.y)
        if wi >= 0: self._disconnect(wi, wp); return
        kind, idx, _ = self._hit(e.x, e.y)
        if kind == "node":
            self._ctx_node(e, idx)
        else:
            self._ctx_canvas(e, e.x, e.y)

    def _dbl(self, e: tk.Event) -> None:
        kind, idx, _ = self._hit(e.x, e.y)
        if kind == "node" and self._on_dblclick:
            self._on_dblclick(idx)

    def _scroll(self, e: tk.Event) -> None:
        if e.state & 0x4:  # Ctrl → zoom
            cx, cy = self.winfo_width()/2, self.winfo_height()/2
            f = 1.12 if e.delta > 0 else (1/1.12)
            z = max(MIN_ZOOM, min(MAX_ZOOM, self._zoom * f))
            wx, wy = self._s2w(cx, cy)
            self._zoom = z; self._pan_x = cx - wx*z; self._pan_y = cy - wy*z
            if self._on_zoom_change: self._on_zoom_change(self._zoom)
        else:
            self._pan_y += e.delta * 0.5
        self._redraw()

    def zoom_by(self, factor: float) -> None:
        """Zoom in/out centred on canvas centre."""
        cx = self.winfo_width()  / 2
        cy = self.winfo_height() / 2
        z  = max(MIN_ZOOM, min(MAX_ZOOM, self._zoom * factor))
        wx, wy = self._s2w(cx, cy)
        self._zoom = z; self._pan_x = cx - wx*z; self._pan_y = cy - wy*z
        if self._on_zoom_change: self._on_zoom_change(self._zoom)
        self._redraw()

    def _del_selected(self):
        for idx in sorted(self._selected, reverse=True): self._remove_node(idx)
        self._selected.clear()

    # ── Context menus ─────────────────────────────────────────────────────────

    def _ctx_node(self, e, idx: int) -> None:
        n     = self._nodes[idx]
        ntype = n.get("node_type", "seq")
        menu  = tk.Menu(self, tearoff=0, bg="#182433", fg=TEXT_HI,
                        activebackground=SEL_BORDER, activeforeground="#FFF",
                        font=("Segoe UI", 10))
        if ntype == "start":
            menu.add_command(label="🔌  Disconnect output wire",
                             command=lambda: self._disconnect(idx, "out"))
        elif ntype == "condition":
            menu.add_command(label="✎  Edit condition",
                             command=lambda: self._on_edit_cond and self._on_edit_cond(idx))
            menu.add_separator()
            menu.add_command(label="🔌  Disconnect all wires",
                             command=lambda: self._disconnect_all(idx))
            menu.add_command(label="🗑  Delete node",
                             command=lambda: self._remove_node(idx))
        else:  # seq
            menu.add_command(label="⚙  Edit settings",
                             command=lambda: self._on_dblclick and self._on_dblclick(idx))
            menu.add_separator()
            menu.add_command(label="🔌  Disconnect all wires",
                             command=lambda: self._disconnect_all(idx))
            menu.add_command(label="🗑  Delete node",
                             command=lambda: self._remove_node(idx))
        menu.tk_popup(e.x_root, e.y_root)

    def _ctx_canvas(self, e, sx: float, sy: float) -> None:
        wx, wy = self._s2w(sx, sy)
        menu = tk.Menu(self, tearoff=0, bg="#182433", fg=TEXT_HI,
                       activebackground=COND_BORDER, activeforeground="#FFF",
                       font=("Segoe UI", 10))
        menu.add_command(
            label="🖼  Add Image Condition",
            command=lambda: self._add_condition_node("image", wx, wy))
        menu.add_command(
            label="🔤  Add OCR Condition",
            command=lambda: self._add_condition_node("ocr", wx, wy))
        menu.add_command(
            label="🔀  Add Image + OCR Condition",
            command=lambda: self._add_condition_node("mixed", wx, wy))
        menu.add_separator()
        menu.add_command(label="⌖  Reset view", command=self.reset_view)
        menu.tk_popup(e.x_root, e.y_root)

    # ── Node management ───────────────────────────────────────────────────────

    def add_seq_node(self, step: dict) -> None:
        """Add a sequence node."""
        x, y = self._next_auto_pos()
        node = {**step, "node_type": "seq", "x": x, "y": y,
                "next": None}
        self._nodes.append(node)
        self._selected = {len(self._nodes) - 1}
        self._redraw()
        if self._on_changed: self._on_changed()

    def _add_condition_node(self, ctype: str, wx: float, wy: float) -> None:
        """Create a condition node at world position (wx, wy)."""
        node = {
            "node_type": "condition",
            "condition": {
                "type": ctype, "images": [], "img_threshold": 0.85,
                "ocr_checks": [], "logic": "any",
            },
            "on_true":  None,
            "on_false": None,
            "x": wx - NODE_W / 2,
            "y": wy - COND_H / 2,
        }
        self._nodes.append(node)
        new_idx = len(self._nodes) - 1
        self._selected = {new_idx}
        # Immediately open condition editor for new condition node
        if self._on_edit_cond:
            self.after(80, lambda: self._on_edit_cond(new_idx))
        self._redraw()
        if self._on_changed: self._on_changed()

    def _next_auto_pos(self) -> tuple[float, float]:
        """Place new node to the right of the rightmost non-start node, or right of start."""
        non_start = [n for n in self._nodes if n.get("node_type") != "start"]
        if non_start:
            last = max(non_start, key=lambda n: n["x"])
            return last["x"] + NODE_W + 80, last["y"]
        starts = [n for n in self._nodes if n.get("node_type") == "start"]
        if starts:
            s = starts[0]
            return s["x"] + NODE_W + 80, s["y"]
        return 380.0, 160.0

    def _remove_node(self, idx: int) -> None:
        if not 0 <= idx < len(self._nodes): return
        # Protect start node from deletion
        if self._nodes[idx].get("node_type") == "start": return
        self._nodes.pop(idx)
        for n in self._nodes:
            for key in ("next", "on_true", "on_false"):
                v = n.get(key)
                if v == idx: n[key] = None
                elif isinstance(v, int) and v > idx: n[key] = v - 1
        self._selected = {i if i < idx else i-1 for i in self._selected if i != idx}
        self._redraw()
        if self._on_changed: self._on_changed()
        if self._on_delete:  self._on_delete(idx)

    def _connect(self, src_idx: int, src_port: str, dst_idx: int) -> None:
        n = self._nodes[src_idx]
        if src_port == "out":   n["next"]     = dst_idx
        elif src_port == "true":  n["on_true"]  = dst_idx
        elif src_port == "false": n["on_false"] = dst_idx
        self._redraw()
        if self._on_changed: self._on_changed()

    def _disconnect(self, src_idx: int, src_port: str) -> None:
        n = self._nodes[src_idx]
        if src_port == "out":   n["next"]     = None
        elif src_port == "true":  n["on_true"]  = None
        elif src_port == "false": n["on_false"] = None
        self._redraw()
        if self._on_changed: self._on_changed()

    def _disconnect_all(self, idx: int) -> None:
        n = self._nodes[idx]
        for k in ("next", "on_true", "on_false"): n[k] = None
        for o in self._nodes:
            for k in ("next", "on_true", "on_false"):
                if o.get(k) == idx: o[k] = None
        self._redraw()

    def highlight_node(self, idx: int) -> None:
        self._running_idx = idx; self._redraw()

    def clear_highlights(self) -> None:
        self._running_idx = -1; self._redraw()

    def reset_view(self) -> None:
        self._pan_x = 60.0; self._pan_y = 80.0; self._zoom = 1.0
        if self._on_zoom_change: self._on_zoom_change(self._zoom)
        self._redraw()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _redraw(self) -> None:
        self.delete("all")
        self._draw_grid()
        self._draw_wires()
        for i in range(len(self._nodes)): self._draw_node(i)
        if self._state == "drag_wire": self._draw_pending()

    def _draw_grid(self) -> None:
        W = self.winfo_width()  or 800
        H = self.winfo_height() or 600
        g = GRID * self._zoom
        x = self._pan_x % g
        while x < W: self.create_line(x, 0, x, H, fill=GRID_C, width=1); x += g
        y = self._pan_y % g
        while y < H: self.create_line(0, y, W, y, fill=GRID_C, width=1); y += g

    def _draw_node(self, idx: int) -> None:
        n     = self._nodes[idx]
        ntype = n.get("node_type", "seq")
        is_start = ntype == "start"
        is_cond  = ntype == "condition"
        nh        = _node_h(n)
        sx, sy    = self._w2s(n["x"], n["y"])
        nw        = NODE_W * self._zoom
        nh_s      = nh    * self._zoom
        hh_s      = HDR_H * self._zoom
        z         = self._zoom
        running   = self._running_idx == idx
        selected  = idx in self._selected

        # Shadow
        self.create_rectangle(sx+3, sy+4, sx+nw+3, sy+nh_s+4,
                              fill="#080E18", outline="", stipple="gray50")

        # ── START node ────────────────────────────────────────────────────────
        if is_start:
            border = SEL_BORDER if selected else START_BORDER
            self.create_rectangle(sx, sy, sx+nw, sy+nh_s,
                                  fill=START_BG, outline=border,
                                  width=max(2, int(3*z)))
            # Glowing header fill
            self.create_rectangle(sx+1, sy+1, sx+nw-1, sy+nh_s-1,
                                  fill=START_HDR, outline="")
            fs = max(8, int(10*z))
            self.create_text(sx + nw/2, sy + nh_s/2,
                             text="▶  START",
                             fill=GREEN, font=("Segoe UI", fs, "bold"))
            # Hint label
            hint_fs = max(6, int(7*z))
            self.create_text(sx + nw/2, sy + nh_s - 9*z,
                             text="drag → to connect first node",
                             fill=TEXT_DIM, font=("Segoe UI", hint_fs))
            # Draw only the out port
            self._draw_port(idx, "out")
            return

        # Body
        border = (RUN_BORDER if running else
                  SEL_BORDER if selected else
                  COND_BORDER if is_cond else NODE_BORDER)
        bg = COND_BG if is_cond else SEQ_BG
        self.create_rectangle(sx, sy, sx+nw, sy+nh_s,
                              fill=bg, outline=border,
                              width=max(1, int(2*z)))
        # Header
        hdr = COND_HDR if is_cond else SEQ_HDR
        self.create_rectangle(sx+1, sy+1, sx+nw-1, sy+hh_s,
                              fill=hdr, outline="")

        # ── Header content ────────────────────────────────────────────────────
        fs  = max(7, int(9*z))
        fs8 = max(6, int(8*z))

        if is_cond:
            cond  = n.get("condition") or {}
            ctype = cond.get("type", "image")
            icon, label, color = COND_TYPE_LABELS.get(ctype, ("⚡", "Condition", PURPLE))
            self.create_text(sx + nw/2, sy + hh_s/2,
                             text=f"{icon}  {label}",
                             fill=color, font=("Segoe UI", fs, "bold"))
        else:
            name = (n.get("name") or "?")[:16]
            self.create_text(sx + nw/2, sy + hh_s/2,
                             text=f"🎬  {name}",
                             fill=TEXT_HI, font=("Segoe UI", fs, "bold"))

        # ✕ delete
        self.create_text(sx + nw - 8*z, sy + hh_s/2,
                         text="✕", fill=TEXT_DIM,
                         font=("Segoe UI", max(7, int(9*z))))

        # ── Body content ──────────────────────────────────────────────────────
        if is_cond:
            cond  = n.get("condition") or {}
            ctype = cond.get("type", "image")
            n_img = len(cond.get("images") or [])
            ocr_checks = cond.get("ocr_checks") or []
            thr   = cond.get("img_threshold", 0.85)
            configured = False

            if ctype == "image":
                if n_img:
                    body_txt = f"🖼 {n_img} image{'s' if n_img>1 else ''}  thr={thr:.2f}"
                    col = ORANGE; configured = True
                else:
                    body_txt = "⚠ No images added"; col = TEXT_DIM
            else:  # ocr
                texts = [c.get("text", "").strip() for c in ocr_checks if c.get("text", "").strip()]
                if texts:
                    preview = texts[0][:18] + ("…" if len(texts[0]) > 18 else "")
                    body_txt = f"🔍 \"{preview}\""
                    if len(texts) > 1: body_txt += f" +{len(texts)-1} more"
                    col = PURPLE; configured = True
                else:
                    body_txt = "⚠ No text pattern set"; col = TEXT_DIM

            self.create_text(sx + 10*z, sy + hh_s + (nh_s-hh_s)/2,
                             text=body_txt, fill=col,
                             font=("Segoe UI", fs8), anchor="w")
            # ✎ edit button
            self.create_rectangle(sx+nw-28*z, sy+hh_s+4*z,
                                  sx+nw-8*z,  sy+nh_s-4*z,
                                  fill="#1A0A2E",
                                  outline=COND_BORDER if configured else NODE_BORDER,
                                  width=1)
            self.create_text(sx + nw - 18*z, sy + hh_s + (nh_s-hh_s)/2,
                             text="✎",
                             fill=PURPLE if configured else TEXT_DIM,
                             font=("Segoe UI", max(8, int(10*z))))
        else:
            rep   = n.get("repeats", 1)
            delay = n.get("delay", 0.5)
            self.create_text(sx + 10*z, sy + hh_s + 16*z,
                             text=f"× {rep}  repeat",
                             fill=TEXT_LO, font=("Segoe UI", fs8), anchor="w")
            self.create_text(sx + 10*z, sy + hh_s + 32*z,
                             text=f"⏱ {delay:.1f}s  delay",
                             fill=TEXT_DIM, font=("Segoe UI", fs8), anchor="w")
            # ✎ settings shortcut (shows ⚙)
            self.create_text(sx + nw - 18*z, sy + hh_s + (SEQ_H*z-hh_s)/2,
                             text="⚙",
                             fill=TEXT_DIM, font=("Segoe UI", max(8, int(10*z))))

        # Draw ports
        for port in _node_ports(n): self._draw_port(idx, port)

    def _draw_port(self, idx: int, port: str) -> None:
        cfg    = PORT_CFG[port]
        wx, wy = self._port_world(idx, port)
        sx, sy = self._w2s(wx, wy)
        r      = max(4, int(PORT_R * self._zoom))
        col    = cfg["col"]
        filled = self._port_has_wire(idx, port)
        self.create_oval(sx-r, sy-r, sx+r, sy+r,
                        fill=col if filled else BG, outline=col,
                        width=max(1, int(2*self._zoom)))
        if cfg["label"]:
            off  = r + 5
            side = cfg["side"]
            ax   = sx + off if side == "right" else sx - off
            self.create_text(ax, sy, text=cfg["label"], fill=col,
                            font=("Segoe UI", max(6, int(8*self._zoom)), "bold"),
                            anchor="w" if side == "right" else "e")

    def _port_has_wire(self, idx: int, port: str) -> bool:
        n = self._nodes[idx]
        if port == "in":
            return any(
                o.get("next") == idx or o.get("on_true") == idx or o.get("on_false") == idx
                for o in self._nodes)
        return self._wire_dst(idx, port) is not None

    def _draw_wires(self) -> None:
        for i, n in enumerate(self._nodes):
            d = self._wire_dst(i, "out")
            if d is not None: self._bezier_wire(i, "out", d, WIRE_OUT)
            d = self._wire_dst(i, "true")
            if d is not None: self._bezier_wire(i, "true", d, WIRE_TRUE)
            d = self._wire_dst(i, "false")
            if d is not None: self._bezier_wire(i, "false", d, WIRE_FALSE)

    def _bezier_wire(self, si, sp, di, col, dash=None) -> None:
        x1, y1 = self._port_world(si, sp)
        x2, y2 = self._port_world(di, "in")
        sx1, sy1 = self._w2s(x1, y1); sx2, sy2 = self._w2s(x2, y2)
        self._bezier(sx1, sy1, sx2, sy2, col, dash)

    def _draw_pending(self) -> None:
        si, sp = self._wire_src
        if si < 0: return
        x1, y1 = self._port_world(si, sp)
        sx1, sy1 = self._w2s(x1, y1)
        col = {"out": WIRE_OUT, "true": WIRE_TRUE, "false": WIRE_FALSE}.get(sp, WIRE_PEND)
        self._bezier(sx1, sy1, *self._wire_cur, col, dash=(5, 3))

    def _bezier(self, x1, y1, x2, y2, col, dash=None) -> None:
        dx  = abs(x2 - x1) * 0.55
        pts = []
        for i in range(21):
            t = i/20; u = 1-t
            bx = u**3*x1 + 3*u**2*t*(x1+dx) + 3*u*t**2*(x2-dx) + t**3*x2
            by = u**3*y1 + 3*u**2*t*y1       + 3*u*t**2*y2       + t**3*y2
            pts.extend([bx, by])
        kw = dict(fill=col, width=max(1, int(2*self._zoom)), smooth=True)
        if dash: kw["dash"] = dash
        self.create_line(*pts, **kw)

    # ── Data I/O ──────────────────────────────────────────────────────────────

    def load_nodes(self, nodes: list) -> None:
        self._nodes.clear(); self._selected.clear()
        has_start = any(nd.get("node_type") == "start" for nd in nodes)
        if not has_start:
            # Legacy plan — prepend a start node
            self._nodes.append(_make_start_node(80.0, 160.0))
        for i, nd in enumerate(nodes):
            node = dict(nd)
            if "x" not in node: node["x"] = 380.0 + i * (NODE_W + 80)
            if "y" not in node: node["y"] = 160.0
            self._nodes.append(node)
        self._redraw()

    def get_nodes(self) -> list:
        return [
            {k: v for k, v in n.items()}
            for n in self._nodes
        ]


# ─────────────────────────────────────────────────────────────────────────────
class PlanGraphWidget(ctk.CTkFrame):
    """Outer container: toolbar + graph canvas."""

    def __init__(self, parent,
                 on_edit_condition: Optional[Callable] = None,
                 on_node_dblclick:  Optional[Callable] = None,
                 on_changed:        Optional[Callable] = None) -> None:
        super().__init__(parent, fg_color="transparent")
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._on_edit_condition = on_edit_condition
        self._on_node_dblclick  = on_node_dblclick
        self._on_changed        = on_changed
        self._add_seq_callback: Optional[Callable] = None

        self._build()

    def _build(self) -> None:
        # Toolbar
        tb = ctk.CTkFrame(self, fg_color="#10192A", height=40, corner_radius=0)
        tb.grid(row=0, column=0, sticky="ew")
        tb.grid_propagate(False)

        ctk.CTkLabel(tb, text="🗺  Plan Graph",
                     font=("Segoe UI", 11, "bold"), text_color=TEXT_LO,
                     ).pack(side="left", padx=(12, 16))
        ctk.CTkButton(tb, text="⊕  Add sequence", height=28, width=130,
                      corner_radius=6, fg_color="#1A3050", hover_color=SEL_BORDER,
                      text_color=TEXT_HI, font=("Segoe UI", 10),
                      command=lambda: self._add_seq_callback and self._add_seq_callback(),
                      ).pack(side="left", padx=4)
        ctk.CTkButton(tb, text="⌖  Reset view", height=28, width=100,
                      corner_radius=6, fg_color="#1A3050", hover_color="#1E3A5A",
                      text_color=TEXT_LO, font=("Segoe UI", 10),
                      command=self.reset_view,
                      ).pack(side="left", padx=4)
        ctk.CTkButton(tb, text="🗑  Clear all", height=28, width=90,
                      corner_radius=6, fg_color="#1A1A2E", hover_color="#3A0D0D",
                      text_color=TEXT_DIM, font=("Segoe UI", 10),
                      command=self.clear,
                      ).pack(side="left", padx=4)

        # Zoom controls (right-aligned)
        ctk.CTkButton(tb, text="−", width=28, height=28,
                      corner_radius=6, fg_color="#1A3050", hover_color="#1E3A5A",
                      text_color=TEXT_HI, font=("Segoe UI", 14, "bold"),
                      command=lambda: self.zoom_step(1/1.25),
                      ).pack(side="right", padx=(0, 2))
        self._zoom_lbl = ctk.CTkLabel(tb, text="100%", width=46,
                                      font=("Segoe UI", 10, "bold"),
                                      text_color=TEXT_LO)
        self._zoom_lbl.pack(side="right")
        ctk.CTkButton(tb, text="+", width=28, height=28,
                      corner_radius=6, fg_color="#1A3050", hover_color="#1E3A5A",
                      text_color=TEXT_HI, font=("Segoe UI", 14, "bold"),
                      command=lambda: self.zoom_step(1.25),
                      ).pack(side="right", padx=(4, 0))
        ctk.CTkLabel(tb, text="Zoom:",
                     font=("Segoe UI", 9), text_color=TEXT_DIM,
                     ).pack(side="right", padx=(8, 2))

        ctk.CTkLabel(tb,
                     text="  Drag ● to connect  •  RMB canvas = add condition  •  RMB wire = remove  •  Space+drag / Middle = pan  •  Ctrl+scroll = zoom",
                     font=("Segoe UI", 8), text_color=TEXT_DIM,
                     ).pack(side="left", padx=8)

        # Canvas
        self._canvas = _GraphCanvas(
            self,
            on_edit_condition=self._on_edit_condition,
            on_node_dblclick=self._on_node_dblclick,
            on_changed=self._on_changed,
        )
        self._canvas._on_zoom_change = self._update_zoom_label
        self._canvas.grid(row=1, column=0, sticky="nsew")

    # ── Public API ────────────────────────────────────────────────────────────

    def set_add_seq_callback(self, cb: Callable) -> None:
        self._add_seq_callback = cb

    def zoom_step(self, factor: float) -> None:
        self._canvas.zoom_by(factor)

    def _update_zoom_label(self, z: float) -> None:
        self._zoom_lbl.configure(text=f"{int(z*100)}%")

    def add_node(self, step: dict) -> None:
        self._canvas.add_seq_node(step)

    def load_steps(self, nodes: list) -> None:
        self._canvas.load_nodes(nodes)

    def get_steps(self) -> list:
        return self._canvas.get_nodes()

    def highlight_node(self, idx: int) -> None:
        self._canvas.highlight_node(idx)

    def clear_highlights(self) -> None:
        self._canvas.clear_highlights()

    def reset_view(self) -> None:
        self._canvas.reset_view()
        self._update_zoom_label(self._canvas._zoom)

    def clear(self) -> None:
        # Remove all non-start nodes, keep start node intact
        self._canvas._nodes = [
            n for n in self._canvas._nodes
            if n.get("node_type") == "start"
        ]
        if not self._canvas._nodes:
            self._canvas._nodes.append(_make_start_node())
        self._canvas._selected.clear()
        self._canvas._redraw()
        if self._canvas._on_changed: self._canvas._on_changed()

    @property
    def nodes(self) -> list:
        return self._canvas._nodes
