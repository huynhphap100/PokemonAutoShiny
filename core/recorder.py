"""
Movement Recorder — captures ALL keyboard input + mouse clicks with timestamps.

Every key pressed while recording is active is stored. The only keys excluded are:
  - The configured toggle key
  - Modifier keys during one-shot hotkey-capture mode
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from pynput import keyboard as kb
from pynput import mouse as ms

from core import settings as cfg
from core import input_guard

# ── Key display helpers ───────────────────────────────────────────────────────

_DISPLAY: dict[str, str] = {
    "Key.up": "↑", "Key.down": "↓", "Key.left": "←", "Key.right": "→",
    "Key.enter": "↵", "Key.space": "⎵", "Key.backspace": "⌫",
    "Key.delete": "Del", "Key.esc": "Esc", "Key.tab": "Tab",
    "Key.home": "Home", "Key.end": "End",
    "Key.page_up": "PgUp", "Key.page_down": "PgDn",
    "Key.insert": "Ins",
    "Key.f1":  "F1",  "Key.f2":  "F2",  "Key.f3":  "F3",  "Key.f4":  "F4",
    "Key.f5":  "F5",  "Key.f6":  "F6",  "Key.f7":  "F7",  "Key.f8":  "F8",
    "Key.f9":  "F9",  "Key.f10": "F10", "Key.f11": "F11", "Key.f12": "F12",
    "Key.shift":      "⇧",   "Key.shift_r":  "⇧",
    "Key.ctrl":       "Ctrl", "Key.ctrl_r":   "Ctrl", "Key.ctrl_l": "Ctrl",
    "Key.alt":        "Alt",  "Key.alt_r":    "Alt",  "Key.alt_l":  "Alt",
    "Key.alt_gr":     "AltGr",
    "Key.cmd":        "Win",  "Key.cmd_r":    "Win",
    "Key.caps_lock":  "Caps",
    "Key.num_lock":   "NumLk",
    "Key.print_screen": "PrtSc",
    "Key.pause":      "Pause",
}


def key_str_display(key_str: str) -> str:
    """Return a short human-readable label for a pynput key string."""
    if key_str in _DISPLAY:
        return _DISPLAY[key_str]
    # Quoted char: "'a'" → "A", "' '" → "Spc"
    if key_str.startswith("'") and key_str.endswith("'"):
        inner = key_str[1:-1]
        if inner == " ":
            return "⎵"
        return inner.upper() if len(inner) == 1 else inner
    # Key.xxx → "Xxx"
    if key_str.startswith("Key."):
        name = key_str[4:]
        return name.replace("_", "").title()[:5]
    return key_str[:5]


# ── Mouse button mapping ──────────────────────────────────────────────────────

_MOUSE_KEY: dict[ms.Button, str] = {
    ms.Button.left:   "MOUSE_LEFT",
    ms.Button.right:  "MOUSE_RIGHT",
    ms.Button.middle: "MOUSE_MIDDLE",
}

MOUSE_DISPLAY: dict[str, str] = {
    "MOUSE_LEFT":   "🖱L",
    "MOUSE_RIGHT":  "🖱R",
    "MOUSE_MIDDLE": "🖱M",
}

# Modifier keys to ignore during one-shot capture mode
_MODIFIERS = {
    kb.Key.shift, kb.Key.shift_r,
    kb.Key.ctrl,  kb.Key.ctrl_r,  kb.Key.ctrl_l,
    kb.Key.alt,   kb.Key.alt_r,   kb.Key.alt_l,
    kb.Key.cmd,   kb.Key.cmd_r,
    kb.Key.caps_lock,
}


class MovementRecorder:
    """Records all keyboard input + mouse clicks with timestamps.

    All callbacks are invoked from the pynput listener thread; callers must
    marshal UI updates onto the main thread (e.g. tkinter ``after``).
    """

    def __init__(
        self,
        on_toggle=None,   # callable(is_recording: bool)
        on_action=None,   # callable(action: dict)
    ):
        self.on_toggle = on_toggle
        self.on_action = on_action

        saved = cfg.load()
        self.toggle_key    = cfg.parse_key(saved.get("toggle_key",    "Key.f8"))
        self.ocr_check_key = cfg.parse_key(saved.get("ocr_check_key", "Key.f9"))

        self.is_recording: bool = False
        self.actions: list[dict] = []
        self.start_time: float | None = None

        self._kb_listener: kb.Listener | None = None
        self._ms_listener: ms.Listener | None = None
        self._held: set[str] = set()

        self._target_hwnd: int | None = None

        # Hotkey capture state
        self._capturing: bool = False
        self._capture_cb = None

    # ── Listener lifecycle ───────────────────────────────────────────────────

    def start_listener(self) -> None:
        self._kb_listener = kb.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._kb_listener.daemon = True
        self._kb_listener.start()

        self._ms_listener = ms.Listener(on_click=self._on_mouse_click)
        self._ms_listener.daemon = True
        self._ms_listener.start()

    def stop_listener(self) -> None:
        for lst in (self._kb_listener, self._ms_listener):
            if lst:
                lst.stop()
        self._kb_listener = None
        self._ms_listener = None

    # ── Public API ───────────────────────────────────────────────────────────

    def set_toggle_key(self, key) -> None:
        self.toggle_key = key

    def set_ocr_check_key(self, key) -> None:
        """Update the hotkey that inserts an OCR checkpoint mid-recording."""
        self.ocr_check_key = key

    def set_target_hwnd(self, hwnd: int | None) -> None:
        self._target_hwnd = hwnd

    def capture_next_key(self, callback) -> None:
        self._capturing = True
        self._capture_cb = callback

    def insert_ocr_check(self) -> None:
        """Insert an OCR-check checkpoint at the current recording time.

        Call while recording is active (e.g. user pressed the OCR-check button
        in the UI).  The checkpoint is stored as a special action with
        event='ocr_check'.  During auto-hunt playback the player will pause
        here, run OCR, and stop the whole sequence if Shiny is found.

        No-op when not currently recording.
        """
        if not self.is_recording or self.start_time is None:
            return
        ts = round(time.time() - self.start_time, 4)
        action = {
            "key":     "OCR_CHECK",
            "event":   "ocr_check",
            "time":    ts,
            "display": "\U0001f4f8 OCR",
        }
        self.actions.append(action)
        if self.on_action:
            self.on_action(action)

    # ── Keyboard handlers ────────────────────────────────────────────────────

    def _on_key_press(self, key) -> None:
        # Every physical key press updates the global idle timer so the
        # automation player knows to yield while the user is typing.
        input_guard.notify_user_key()

        # One-shot capture mode: grab next non-modifier key for hotkey remapping
        if self._capturing:
            if key in _MODIFIERS:
                return
            self._capturing = False
            cb = self._capture_cb
            self._capture_cb = None
            if cb:
                cb(key)
            return

        # Toggle recording on/off
        if key == self.toggle_key:
            self._toggle()
            return

        # OCR check hotkey: insert checkpoint WITHOUT recording the keypress
        if self.is_recording and key == self.ocr_check_key:
            self.insert_ocr_check()
            return

        if not self.is_recording:
            return

        key_str = str(key)

        # Skip already-held keys (OS auto-repeat would send duplicates)
        if key_str in self._held:
            return

        self._held.add(key_str)
        action = self._make_action(key_str, "press", key_str_display(key_str))
        self.actions.append(action)
        if self.on_action:
            self.on_action(action)

    def _on_key_release(self, key) -> None:
        if not self.is_recording:
            return
        key_str = str(key)
        if key_str not in self._held:
            return
        self._held.discard(key_str)
        action = self._make_action(key_str, "release", key_str_display(key_str))
        self.actions.append(action)

    # ── Mouse handler ────────────────────────────────────────────────────────

    def _on_mouse_click(self, x: int, y: int, button: ms.Button, pressed: bool) -> None:
        if not self.is_recording or not pressed:
            return

        btn_key  = _MOUSE_KEY.get(button, "MOUSE_LEFT")
        btn_name = button.name

        cx, cy = x, y
        if self._target_hwnd:
            from core import window_manager as wm
            if wm.is_valid(self._target_hwnd):
                cx, cy = wm.screen_to_client(self._target_hwnd, x, y)

        ts = round(time.time() - self.start_time, 4)
        action = {
            "key":     btn_key,
            "event":   "click",
            "time":    ts,
            "display": MOUSE_DISPLAY.get(btn_key, "🖱"),
            "x":       cx,
            "y":       cy,
            "button":  btn_name,
        }
        self.actions.append(action)
        if self.on_action:
            self.on_action(action)

    # ── Toggle ───────────────────────────────────────────────────────────────

    def _make_action(self, key_str: str, event: str, display: str) -> dict:
        return {
            "key":     key_str,
            "event":   event,
            "time":    round(time.time() - self.start_time, 4),
            "display": display,
        }

    def _toggle(self) -> None:
        if self.is_recording:
            self.is_recording = False
            self._held.clear()
        else:
            self.is_recording = True
            self.actions = []
            self.start_time = time.time()

        if self.on_toggle:
            self.on_toggle(self.is_recording)

    # ── Persistence ──────────────────────────────────────────────────────────

    def save(self, name: str, save_dir: Path) -> Path:
        save_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in name if c.isalnum() or c in "- _").strip() or "sequence"
        filepath = save_dir / f"{safe}.json"
        steps = [a for a in self.actions if a["event"] in ("press", "click")]
        payload = {
            "name":       name,
            "actions":    self.actions,
            "step_count": len(steps),
            "total_time": round(self.actions[-1]["time"], 2) if self.actions else 0.0,
        }
        filepath.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return filepath

    @staticmethod
    def load_all(save_dir: Path) -> list[dict]:
        if not save_dir.exists():
            return []
        results = []
        for path in sorted(save_dir.glob("*.json")):
            try:
                results.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass
        return results

    @staticmethod
    def delete(name: str, save_dir: Path) -> None:
        safe = "".join(c for c in name if c.isalnum() or c in "- _").strip()
        target = save_dir / f"{safe}.json"
        if target.exists():
            target.unlink()
