"""
core/auto_runner.py — Automated shiny-hunting loop with mid-sequence OCR check.

Flow per iteration
------------------
1. Start playing the movement sequence (background thread).
2. In parallel, wait ``ocr_check_delay`` seconds.
3. At that moment, OCR the name-bar region.
   • Shiny found → stop player immediately → alert → exit loop.
   • Not shiny   → let sequence finish normally → loop.
4. If no OCR region is configured, fall back to pixel-diff after sequence ends.
"""
from __future__ import annotations

from core.debug_log import dlog

import threading
import time
from typing import Callable, Optional

from core.player import MovementPlayer
from core.detector import ScreenDetector

try:
    import winsound
    _WINSOUND = True
except ImportError:
    _WINSOUND = False


class AutoRunner:
    """Loop a movement sequence and stop on shiny detection.

    The runner owns its own ``MovementPlayer`` so it never interferes
    with the Movement tab's manual-playback player.

    Callbacks run on the runner's background thread — callers MUST
    marshal UI updates with ``widget.after(0, ...)``.

    on_loop(loop_n, info)
        info dict keys: method ("ocr"|"pixel"), is_shiny, text, similarity
    on_shiny(loop_n, info)
    on_stopped()   — user manually stopped (no shiny)
    on_started()
    """

    def __init__(
        self,
        detector: ScreenDetector,
        on_loop:    Optional[Callable] = None,
        on_shiny:   Optional[Callable] = None,
        on_stopped: Optional[Callable] = None,
        on_started: Optional[Callable] = None,
    ) -> None:
        self.detector       = detector
        self.on_loop        = on_loop
        self.on_shiny       = on_shiny
        self.on_stopped     = on_stopped
        self.on_started     = on_started

        # Config
        self.threshold       = 85.0    # pixel-diff fallback
        self.ocr_check_delay = 3.0     # seconds into sequence → OCR check

        # State
        self.is_running  = False
        self.loop_count  = 0
        self.start_time: Optional[float] = None

        self._stop_flag  = False
        self._shiny_flag = False
        self._hwnd:      Optional[int] = None
        self._sequence:  Optional[dict] = None
        self._thread:    Optional[threading.Thread] = None

        self._play_done  = threading.Event()
        self._player = MovementPlayer(
            on_complete=self._on_play_done,
            on_stopped=self._on_play_done,
        )
        # on_ocr_check is wired in start() so it can reference self correctly

    # ── Public ────────────────────────────────────────────────────────────────

    def start(
        self,
        sequence: dict,
        hwnd: Optional[int],
        threshold: float = 85.0,
        ocr_check_delay: float = 3.0,
    ) -> None:
        if self.is_running:
            return
        self._sequence       = sequence
        self._hwnd           = hwnd
        self.threshold       = threshold
        self.ocr_check_delay = ocr_check_delay
        self.loop_count      = 0
        self.start_time      = time.time()
        self.is_running      = True
        self._stop_flag      = False
        self._shiny_flag     = False

        # Wire the inline OCR callback so player can trigger checks mid-sequence
        self._player.on_ocr_check = self._do_inline_ocr_check

        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if self.on_started:
            self.on_started()

    def stop(self) -> None:
        self._stop_flag = True
        self._player.stop()
        self._play_done.set()

    def elapsed_str(self) -> str:
        if self.start_time is None:
            return "00:00:00"
        s = int(time.time() - self.start_time)
        return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"

    # ── Internal ─────────────────────────────────────────────────────────────

    def _on_play_done(self) -> None:
        self._play_done.set()

    @staticmethod
    def _has_inline_ocr(sequence: dict) -> bool:
        """Return True if any action in *sequence* is an ocr_check checkpoint."""
        return any(
            a.get("event") == "ocr_check"
            for a in sequence.get("actions", [])
        )

    def _run(self) -> None:
        use_ocr     = self.detector.has_ocr_region()
        has_inline  = self._has_inline_ocr(self._sequence)
        dlog(f"[run] use_ocr={use_ocr} has_inline={has_inline}")
        try:
            while not self._stop_flag:
                self._play_done.clear()
                self._shiny_flag = False

                # ── Start sequence ────────────────────────────────────────────
                self._player.play(
                    self._sequence, loop=False, target_hwnd=self._hwnd
                )

                if use_ocr and not has_inline:
                    # ── Timer-based OCR check (no inline checkpoints in seq) ──
                    self._ocr_during_play()
                else:
                    # ── Wait for sequence to finish ───────────────────────────
                    # Inline OCR checks (if any) are handled by the player
                    # calling _do_inline_ocr_check(); we just wait here.
                    self._play_done.wait()

                if self._stop_flag:
                    break

                if self._shiny_flag:
                    break

                if not use_ocr and not has_inline:
                    # Pixel-diff fallback
                    time.sleep(0.8)
                    similarity = self.detector.compare(self._hwnd)
                    self.loop_count += 1
                    info = {
                        "method": "pixel",
                        "is_shiny": similarity < self.threshold,
                        "text": None,
                        "similarity": similarity,
                    }
                    if self.on_loop:
                        self.on_loop(self.loop_count, info)
                    if info["is_shiny"]:
                        self._shiny_flag = True
                        if self.on_shiny:
                            self.on_shiny(self.loop_count, info)
                        self._alert()
                        break

                # Wait for sequence to finish (OCR path: sequence may still be running)
                self._play_done.wait()

                if self._stop_flag or self._shiny_flag:
                    break

                time.sleep(0.2)

        finally:
            self.is_running = False
            if self._stop_flag and not self._shiny_flag and self.on_stopped:
                self.on_stopped()

    def _do_inline_ocr_check(self) -> bool:
        """Called by MovementPlayer when an ocr_check action is reached.

        Runs OCR, fires callbacks, returns True if shiny was found (player
        should stop), False if the hunt should continue.
        """
        dlog("[inline_ocr] called")
        if self._stop_flag:
            dlog("[inline_ocr] stop_flag set, aborting")
            return True  # abort if runner already stopped

        try:
            is_shiny, text = self.detector.check_shiny_ocr()
        except Exception as exc:
            dlog(f"[inline_ocr] detector error: {exc}")
            return False

        dlog(f"[inline_ocr] is_shiny={is_shiny} text={repr(text)}")
        self.loop_count += 1
        info = {
            "method":     "ocr_inline",
            "is_shiny":   is_shiny,
            "text":       text,
            "similarity": None,
        }
        if self.on_loop:
            dlog("[inline_ocr] firing on_loop")
            self.on_loop(self.loop_count, info)

        if is_shiny:
            self._shiny_flag = True
            if self.on_shiny:
                self.on_shiny(self.loop_count, info)
            self._alert()
            return True   # tell player to stop

        return False  # not shiny, continue


    def _ocr_during_play(self) -> None:
        """Wait ocr_check_delay seconds then OCR. Runs on the run-thread."""
        deadline = time.time() + self.ocr_check_delay
        while time.time() < deadline:
            if self._stop_flag or self._play_done.is_set():
                # Sequence ended early (or stopped) before check time
                return
            time.sleep(0.05)

        if self._stop_flag:
            return

        # Do OCR
        is_shiny, text = self.detector.check_shiny_ocr()
        self.loop_count += 1
        info = {
            "method": "ocr",
            "is_shiny": is_shiny,
            "text": text,
            "similarity": None,
        }

        if self.on_loop:
            self.on_loop(self.loop_count, info)

        if is_shiny:
            self._shiny_flag = True
            self._player.stop()   # stop sequence immediately
            if self.on_shiny:
                self.on_shiny(self.loop_count, info)
            self._alert()

    @staticmethod
    def _alert() -> None:
        if not _WINSOUND:
            return
        try:
            for freq in (880, 1046, 1318):
                winsound.Beep(freq, 350)
                time.sleep(0.08)
        except Exception:
            pass
