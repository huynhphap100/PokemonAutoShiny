"""
Movement Player — replays recorded keyboard + mouse actions with correct timing.

Priority:
  1. If target_hwnd is supplied → use Win32 PostMessage (background window, cursor stays put).
  2. Fallback → pynput Controller (requires game window to be in focus).

Hold-key support:
  While a key is held between its 'press' and 'release' events, the player
  sends repeated WM_KEYDOWN (with bit30 = previous-key-down) every KEY_REPEAT_MS
  to simulate the OS auto-repeat that games rely on for continuous movement.
"""
from __future__ import annotations

from core.debug_log import dlog

import time
import threading

from pynput import keyboard as kb
from pynput import mouse   as ms

from core import window_manager as wm
from core import input_guard

# Approximate Windows key auto-repeat interval (default ~30 ms)
KEY_REPEAT_MS: float = 0.033

# pynput fallback — dynamic key resolver
_KB_STATIC: dict[str, kb.Key | kb.KeyCode] = {
    "Key.up":    kb.Key.up,    "Key.down":  kb.Key.down,
    "Key.left":  kb.Key.left,  "Key.right": kb.Key.right,
    "Key.enter": kb.Key.enter, "Key.space": kb.Key.space,
    "Key.esc":   kb.Key.esc,   "Key.tab":   kb.Key.tab,
    "Key.backspace": kb.Key.backspace,
    "Key.delete":    kb.Key.delete,
    "Key.home":      kb.Key.home,
    "Key.end":       kb.Key.end,
    "Key.page_up":   kb.Key.page_up,
    "Key.page_down": kb.Key.page_down,
    "Key.insert":    kb.Key.insert,
    "Key.shift":     kb.Key.shift,   "Key.shift_r":  kb.Key.shift_r,
    "Key.ctrl":      kb.Key.ctrl,    "Key.ctrl_r":   kb.Key.ctrl_r,
    "Key.alt":       kb.Key.alt,     "Key.alt_r":    kb.Key.alt_r,
    "Key.caps_lock": kb.Key.caps_lock,
    **{f"Key.f{i}": getattr(kb.Key, f"f{i}") for i in range(1, 13)},
    # WASD
    "'w'": kb.KeyCode.from_char("w"), "'a'": kb.KeyCode.from_char("a"),
    "'s'": kb.KeyCode.from_char("s"), "'d'": kb.KeyCode.from_char("d"),
    "'W'": kb.KeyCode.from_char("w"), "'A'": kb.KeyCode.from_char("a"),
    "'S'": kb.KeyCode.from_char("s"), "'D'": kb.KeyCode.from_char("d"),
    **{f"'{i}'": kb.KeyCode.from_char(str(i)) for i in range(10)},
}


def _key_from_str(key_str: str) -> kb.Key | kb.KeyCode | None:
    """Convert a stored pynput key string to a pynput key object.

    Works for any key: single characters, Key.* specials, F-keys, etc.
    """
    # Fast static path
    k = _KB_STATIC.get(key_str)
    if k is not None:
        return k
    # Quoted single char: "'x'"
    if key_str.startswith("'") and key_str.endswith("'"):
        inner = key_str[1:-1]
        if len(inner) == 1:
            return kb.KeyCode.from_char(inner)
    # Key.xxx — look up in pynput's Key enum
    if key_str.startswith("Key."):
        name = key_str[4:]
        try:
            return kb.Key[name]
        except KeyError:
            pass
    return None

_MS_MAP: dict[str, ms.Button] = {
    "MOUSE_LEFT":   ms.Button.left,
    "MOUSE_RIGHT":  ms.Button.right,
    "MOUSE_MIDDLE": ms.Button.middle,
}


class MovementPlayer:
    """Replays a recorded sequence of movement actions.

    Callbacks are called from the player thread — callers must marshal UI
    updates onto the main thread via tkinter ``after``.
    """

    def __init__(
        self,
        on_step=None,        # callable(current: int, total: int)
        on_complete=None,    # callable()  — sequence finished (non-loop)
        on_stopped=None,     # callable()  — manually stopped
        on_ocr_check=None,   # callable() -> bool  — called at ocr_check action;
                             #   return True  → shiny found, stop immediately
                             #   return False → not shiny, continue
                             #   None         → skip the checkpoint silently
    ):
        self.on_step      = on_step
        self.on_complete  = on_complete
        self.on_stopped   = on_stopped
        self.on_ocr_check = on_ocr_check

        self.is_playing   = False
        self.loop         = False
        self.current_name = ""

        self._stop_flag  = False
        self._hwnd: int | None = None
        self._thread: threading.Thread | None = None

        # pynput fallback controllers
        self._kb_ctrl = kb.Controller()
        self._ms_ctrl = ms.Controller()

    # ── Public ───────────────────────────────────────────────────────────────

    def play(
        self,
        sequence: dict,
        loop: bool = False,
        target_hwnd: int | None = None,
    ) -> None:
        """Start playback. No-op if already playing."""
        if self.is_playing:
            return
        self.current_name = sequence.get("name", "")
        self.loop         = loop
        self._hwnd        = target_hwnd
        self.is_playing   = True
        self._stop_flag   = False
        self._thread = threading.Thread(
            target=self._run,
            args=(sequence.get("actions", []),),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Request stop. Effective within ~50 ms."""
        self._stop_flag = True

    def wait_for_completion(self, timeout: float | None = None) -> None:
        """Wait for the playback thread to finish."""
        if self._thread:
            self._thread.join(timeout)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _run(self, actions: list[dict]) -> None:
        # NOTE: We intentionally do NOT call bring_to_front() here.
        # All keyboard/mouse input is sent via PostMessage/SendMessage directly
        # to the game hwnd, so the user can keep working in other windows.

        # Suppress the input_guard during playback: our own SendInput calls
        # (used to keep GetAsyncKeyState current for foreground LWJGL games)
        # are visible to pynput's WH_KEYBOARD_LL hook.  Without suppression
        # they would falsely trigger the guard and delay key-up events,
        # causing the character to overshoot by 1-3 tiles.
        input_guard.set_player_active(True)
        try:
            while not self._stop_flag:
                self._play_once(actions)
                if not self.loop or self._stop_flag:
                    break
        finally:
            input_guard.set_player_active(False)
            self.is_playing = False
            if self._stop_flag:
                if self.on_stopped:
                    self.on_stopped()
            else:
                if self.on_complete:
                    self.on_complete()

    def _play_once(self, actions: list[dict]) -> None:
        if not actions:
            return

        # Count only visible user actions (not release or ocr_check)
        countable  = [a for a in actions if a["event"] in ("press", "click")]
        total      = len(countable)
        step       = 0
        t0         = time.perf_counter()
        use_hwnd   = bool(self._hwnd and wm.is_valid(self._hwnd))

        # Keys currently held (key_str → presses in progress)
        held: set[str] = set()

        for action in actions:
            if self._stop_flag:
                break

            target_time = action["time"]

            # ── Wait loop with hold-key repeat ────────────────────────────
            while not self._stop_flag:
                remaining = target_time - (time.perf_counter() - t0)
                if remaining <= 0.001:
                    break

                # ── User-input pause ──────────────────────────────────────
                # If the user is pressing real keys, yield: sleep a short
                # interval and stretch t0 forward by the same amount so that
                # *all* future actions are delayed without losing timing fidelity.
                # Held-key repeats are also suspended during this window.
                # Automation auto-resumes once the user has been idle for
                # input_guard.RESUME_DELAY (30 ms) with no further keypresses.
                if use_hwnd and input_guard.is_user_active():
                    pause = 0.005
                    time.sleep(pause)
                    t0 += pause   # shift timeline → next action waits longer
                    continue
                # ─────────────────────────────────────────────────────────

                if held:
                    # Sleep one repeat interval then re-send all held keys
                    chunk = min(remaining, KEY_REPEAT_MS)
                    time.sleep(chunk)
                    # Verify we haven't overshot the target
                    if (target_time - (time.perf_counter() - t0)) <= 0:
                        break
                    for k in held:
                        self._repeat_key(use_hwnd, k)
                else:
                    # No held keys — simple sleep
                    time.sleep(min(remaining, 0.05))

            if self._stop_flag:
                break

            event   = action["event"]
            key_str = action["key"]

            if event == "ocr_check":
                # ── Inline OCR checkpoint ─────────────────────────────────
                # Release any held keys before checking (game should be idle)
                for k in list(held):
                    self._do_key_up(use_hwnd, k)
                held.clear()

                dlog(f"[player] hit ocr_check action at t={action.get('time')}")
                if self.on_ocr_check is not None:
                    should_stop = self.on_ocr_check()  # True → shiny found
                    dlog(f"[player] ocr_check returned should_stop={should_stop}")
                    if should_stop:
                        self._stop_flag = True  # triggers stopped callback
                        break
                else:
                    dlog("[player] ocr_check: no handler set")
                # else: no handler → skip checkpoint silently

            elif event == "click":
                self._do_click(use_hwnd, action)
                step += 1
                if self.on_step:
                    self.on_step(step, total)

            elif event == "press":
                self._do_key_down(use_hwnd, key_str)
                held.add(key_str)
                step += 1
                if self.on_step:
                    self.on_step(step, total)

            elif event == "release":
                held.discard(key_str)
                self._do_key_up(use_hwnd, key_str)

        # Release any still-held keys (safety cleanup)
        for k in list(held):
            self._do_key_up(use_hwnd, k)  # send WM_KEYUP

    # ── Input dispatchers ─────────────────────────────────────────────────────

    def _do_key_down(self, use_hwnd: bool, key_str: str) -> None:
        """Send key-down to the game window.

        Strategy (both fired when game is foreground):
        1. PostMessage(WM_KEYDOWN) — delivers to the window message queue
           (AWT/Swing KeyListeners, works in background too).
        2. SendInput — updates GetAsyncKeyState and raw-input state
           (required for LWJGL/DirectInput games that poll hardware state).
           Only sent when the game window is the current foreground window
           so keystrokes don’t leak into other apps.
        """
        if use_hwnd:
            wm.send_key_down(self._hwnd, key_str)          # always: WM_KEYDOWN
            if wm.is_foreground(self._hwnd):
                wm.send_key_down_input(key_str)            # foreground only: GetAsyncKeyState
        else:
            key = _key_from_str(key_str)
            if key:
                try:
                    self._kb_ctrl.press(key)
                except Exception:
                    pass

    def _repeat_key(self, use_hwnd: bool, key_str: str) -> None:
        """Send repeat key-down while a key is held.

        PostMessage carries the repeat WM event; SendInput keeps GetAsyncKeyState
        showing the key as pressed for LWJGL-style polling games.
        """
        if use_hwnd:
            wm.send_key_down_repeat(self._hwnd, key_str)  # WM repeat event
            if wm.is_foreground(self._hwnd):
                wm.send_key_down_input(key_str)            # keep async state set
        else:
            key = _key_from_str(key_str)
            if key:
                try:
                    self._kb_ctrl.press(key)
                except Exception:
                    pass

    def _do_key_up(self, use_hwnd: bool, key_str: str) -> None:
        if use_hwnd:
            wm.send_key_up(self._hwnd, key_str)            # WM_KEYUP → hwnd
            if wm.is_foreground(self._hwnd):
                wm.send_key_up_input(key_str)              # clear GetAsyncKeyState
        else:
            key = _key_from_str(key_str)
            if key:
                try:
                    self._kb_ctrl.release(key)
                except Exception:
                    pass

    def _do_click(self, use_hwnd: bool, action: dict) -> None:
        x      = action.get("x", 0)
        y      = action.get("y", 0)
        button = action.get("button", "left")

        if use_hwnd:
            wm.virtual_click(self._hwnd, x, y, button)
        else:
            # Fallback: move cursor and click
            btn = _MS_MAP.get(action["key"], ms.Button.left)
            try:
                self._ms_ctrl.position = (x, y)
                time.sleep(0.03)
                self._ms_ctrl.click(btn)
            except Exception:
                pass
