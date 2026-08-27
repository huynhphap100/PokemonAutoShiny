"""
core/input_guard.py — Detects real physical keyboard activity and lets the
automation player yield gracefully while the user is typing.

How it works
------------
1. ``MovementRecorder._on_key_press`` (pynput listener, catches physical keys)
   calls ``notify_user_key()`` on every real keystroke.
   pynput uses a WH_KEYBOARD_LL low-level hook that fires for physical and
   SendInput events, but NOT for PostMessage events.  Because our automation
   sends keys via PostMessage (background mode), those events are invisible to
   pynput, so we never get false positives from our own injected keys.

   EXCEPTION: when the game window is in the foreground, the player also calls
   ``send_key_down_input`` (SendInput) so that GetAsyncKeyState is updated for
   LWJGL-style games.  SendInput *is* visible to WH_KEYBOARD_LL, which would
   cause false-positive guard triggers (delaying key-up events → character
   overshooting by 1-3 tiles).  The ``_player_active`` flag suppresses
   ``notify_user_key`` for the entire duration of playback to prevent this.

2. ``MovementPlayer._play_once`` calls ``is_user_active()`` inside its wait
   loop.  If the user is typing, the player stretches the sequence timeline
   (adds the sleep time back to ``t0``) instead of advancing toward the next
   action.  This transparently pauses all pending actions — including held-key
   repeats — until the user has been idle for ``RESUME_DELAY`` seconds.

3. After ``RESUME_DELAY`` of silence the guard clears automatically and the
   player resumes from exactly where it left off.
"""
from __future__ import annotations

import time
import threading

# How long after the last physical keypress before automation resumes (seconds)
RESUME_DELAY: float = 0.030   # 30 ms

_lock = threading.Lock()
_last_user_key: float = 0.0   # perf_counter timestamp of the last real key

# True while MovementPlayer is actively replaying a sequence.
# Suppresses notify_user_key() so the player's own SendInput calls don't
# falsely trigger the guard and delay key-up events.
_player_active: bool = False


def set_player_active(active: bool) -> None:
    """Call with True before playback starts, False when it ends."""
    global _player_active
    _player_active = active


def notify_user_key() -> None:
    """Record that a physical keyboard key was just pressed.

    Call this from the pynput listener thread whenever a real (non-synthetic)
    key event is received.  No-op while the player is active (the player's own
    SendInput calls must not interfere with the timeline).
    """
    global _last_user_key
    if _player_active:
        return   # ignore — this is the player's own SendInput event
    with _lock:
        _last_user_key = time.perf_counter()


def is_user_active() -> bool:
    """Return True if a real key was pressed within the last RESUME_DELAY s.

    When True the player should back off instead of sending the next action.
    """
    with _lock:
        return (time.perf_counter() - _last_user_key) < RESUME_DELAY


def idle_since() -> float:
    """Return seconds elapsed since the last physical keypress (0 if active)."""
    with _lock:
        elapsed = time.perf_counter() - _last_user_key
    return max(elapsed, 0.0)
