"""
core/plan_runner.py — Multi-sequence hunt plan runner.

Executes an ordered list of step dicts, each carrying:
    seq       : dict  — sequence to play
    repeats   : int   — how many times to play
    delay     : float — seconds to wait after each repeat
    condition : dict | None — optional image-match gate:
        {
          "type":      "image_match" | "image_list",
          "images":    [str, ...],          # paths to PNG/JPG templates
          "region":    [x,y,w,h] | null,   # None → full game window
          "threshold": float,              # 0-1 match confidence cutoff
          "on_true":   int | null,         # step index to jump to on MATCH
          "on_false":  int | null          # step index to jump to on NO-MATCH
        }
      If condition is None, execution falls through to the next step.
      on_true / on_false == null → continue to next step sequentially.

Stops immediately if shiny is detected at any step.
"""
from __future__ import annotations

import threading
import time
import random
import re
import traceback
from typing import Callable, Optional
from enum import Enum

from core.debug_log import dlog


class MatchMode(str, Enum):
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    EQUALS = "equals"
    REGEX = "regex"


def _has_inline_ocr(seq: dict) -> bool:
    """True if *seq* contains at least one ocr_check action."""
    return any(a.get("event") == "ocr_check" for a in seq.get("actions", []))


def _text_matches(text: str, pattern: str, mode: str | MatchMode, is_shiny_func: Optional[Callable[[str], bool]] = None) -> bool:
    """Check whether *text* satisfies *pattern* according to *mode*.

    Modes
    -----
    ``contains``     — pattern appears anywhere in text (case-insensitive)
    ``not_contains`` — pattern does NOT appear in text (case-insensitive)
    ``equals``       — exact match after stripping whitespace (case-insensitive)
    ``regex``        — pattern is a Python regex applied with re.IGNORECASE
    """
    lo_text    = text.lower()
    lo_pattern = pattern.lower()
    
    # AutoShiny hack: if looking for "shiny", use the robust fuzzy matcher
    if lo_pattern in ("shiny", "shimy") and is_shiny_func:
        is_shiny = is_shiny_func(text)
        if mode == MatchMode.CONTAINS: return is_shiny
        if mode == MatchMode.NOT_CONTAINS: return not is_shiny
        if mode == MatchMode.EQUALS: return is_shiny

    if mode == MatchMode.CONTAINS:
        return lo_pattern in lo_text
    if mode == MatchMode.NOT_CONTAINS:
        return lo_pattern not in lo_text
    if mode == MatchMode.EQUALS:
        return lo_text.strip() == lo_pattern.strip()
    if mode == MatchMode.REGEX:
        try:
            # Prevent ReDoS on very long strings by limiting text length
            return bool(re.search(pattern, text[:2000], re.IGNORECASE))
        except re.error:
            return False
    return lo_pattern in lo_text   # default fallback


class PlanRunner:
    """Runs a user-defined hunt plan: multiple sequences with optional conditional branches."""

    def __init__(self, player, detector) -> None:
        self.player    = player
        self.detector  = detector
        self.is_running = False
        self.loop_count = 0

        # ── Callbacks (fired from runner/player thread;
        #              UI must marshal to main thread via widget.after(0, ...))
        self.on_started:   Optional[Callable] = None  # ()
        self.on_step:      Optional[Callable] = None  # (step_idx, repeat_n, loop_n)
        self.on_ocr:       Optional[Callable] = None  # (loop_n, is_shiny, text)
        self.on_shiny:     Optional[Callable] = None  # (loop_n, text)
        self.on_stopped:   Optional[Callable] = None  # ()
        self.on_condition: Optional[Callable] = None  # (step_idx, matched, confidence, next_idx)

        self._abort_event = threading.Event()
        self._shiny_flag = False
        self._start_time = 0.0
        self._thread: Optional[threading.Thread] = None
        self._jitter_min = 0  # ms
        self._jitter_max = 0  # ms

    # ── Public ────────────────────────────────────────────────────────────────

    def set_jitter(self, min_ms: int, max_ms: int) -> None:
        """Set random jitter range (ms) added to every inter-sequence delay."""
        self._jitter_min = max(0, min_ms)
        self._jitter_max = max(self._jitter_min, max_ms)

    def start(
        self,
        steps: list,           # list of step dicts (seq, repeats, delay, condition?)
        total_loops: int,      # 0 = infinite
        hwnd: Optional[int],
    ) -> None:
        if self.is_running:
            return
        self._steps       = steps
        self._total_loops = total_loops
        self._hwnd        = hwnd
        self._abort_event.clear()
        self._shiny_flag  = False
        self._start_time  = time.time()
        self.loop_count   = 0
        self.is_running   = True

        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="PlanRunner")
        self._thread.start()
        if self.on_started:
            self.on_started()

    def stop(self) -> None:
        self._abort_event.set()
        self.player.stop()

    def elapsed_str(self) -> str:
        secs = int(time.time() - self._start_time)
        return f"{secs // 60}m {secs % 60:02d}s"

    # ── Runner thread ─────────────────────────────────────────────────────────

    def _process_condition_node(self, step_idx: int, raw: dict, default_next: int, n_steps: int) -> int:
        condition = raw.get("condition")
        on_true   = raw.get("on_true")
        on_false  = raw.get("on_false")

        timeout = 0
        interval = 1.0
        if condition:
            timeout = float(condition.get("timeout", 0))
            interval = float(condition.get("interval", 1.0))
            if interval <= 0: interval = 1.0

        matched, conf = False, 0.0
        if timeout > 0:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and not self._abort_event.is_set():
                matched, conf = self._eval_condition_bool(step_idx, condition)
                if matched:
                    break
                self._abort_event.wait(interval)
        else:
            matched, conf = self._eval_condition_bool(step_idx, condition)

        if self._abort_event.is_set():
            return -1

        if matched:
            next_idx = on_true if on_true is not None else default_next
        else:
            next_idx = on_false if on_false is not None else default_next

        dlog(f"[plan] cond node={step_idx} matched={matched} "
             f"conf={conf:.3f} → step {next_idx}")
        if self.on_condition:
            self.on_condition(step_idx, matched, conf, next_idx)

        if next_idx == -1:
            dlog("[plan] sentinel -1 → stop")
            self._abort_event.set()
            return -1
        return max(0, min(next_idx, n_steps))

    def _process_seq_node(self, step_idx: int, raw, default_next: int) -> int:
        if isinstance(raw, (list, tuple)):
            seq, repeats, delay_sec = raw[0], raw[1], raw[2]
        else:
            seq       = raw.get("seq", {})
            repeats   = raw.get("repeats", 1)
            delay_sec = raw.get("delay", 0.5)

        use_inline = _has_inline_ocr(seq)
        self.player.on_ocr_check = (
            self._make_inline_handler(self.loop_count)
            if use_inline else None
        )

        for repeat_n in range(repeats):
            if self._abort_event.is_set():
                break
            dlog(f"[plan] seq node={step_idx} '{seq.get('name')}' "
                 f"rep {repeat_n+1}/{repeats}")
            if self.on_step:
                self.on_step(step_idx, repeat_n, self.loop_count)
            self.player.play(seq, loop=False, target_hwnd=self._hwnd)
            self.player.wait_for_completion()
            if self._abort_event.is_set():
                break
            
            jitter_sec = (
                random.randint(self._jitter_min, self._jitter_max) / 1000.0
                if self._jitter_max > 0 else 0.0
            )
            total_delay = delay_sec + jitter_sec
            if total_delay > 0:
                dlog(f"[plan] delay={delay_sec:.2f}s jitter={jitter_sec*1000:.0f}ms")
                self._abort_event.wait(total_delay)

        raw_next = raw.get("next") if isinstance(raw, dict) else None
        return raw_next if raw_next is not None else default_next

    def _handle_start_node(self, step_idx: int, raw: dict, default_next: int, n_steps: int) -> int:
        nxt = raw.get("next") if isinstance(raw, dict) else None
        return nxt if nxt is not None else default_next

    def _handle_condition_node(self, step_idx: int, raw: dict, default_next: int, n_steps: int) -> int:
        return self._process_condition_node(step_idx, raw, default_next, n_steps)

    def _handle_seq_node(self, step_idx: int, raw: dict, default_next: int, n_steps: int) -> int:
        return self._process_seq_node(step_idx, raw, default_next)

    def _run_node_loop(self) -> None:
        """Helper method to run the node-pointer loop for a single plan loop."""
        n_steps = len(self._steps)
        # Find the start node and use its "next" as the initial step
        initial_idx = 0
        is_graph = False
        for step_idx_temp, step_node in enumerate(self._steps):
            if isinstance(step_node, dict) and step_node.get("node_type") == "start":
                is_graph = True
                _first = step_node.get("next")
                if _first is None:
                    dlog("[plan] start node has no connection — nothing to run")
                    self._abort_event.set()
                    return
                initial_idx = _first
                break

        step_idx = initial_idx
        
        node_handlers = {
            "start": self._handle_start_node,
            "condition": self._handle_condition_node,
            "seq": self._handle_seq_node,
        }
        
        while 0 <= step_idx < n_steps:
            if self._abort_event.is_set():
                break
                
            default_next = -1 if is_graph else step_idx + 1

            raw   = self._steps[step_idx]
            ntype = raw.get("node_type", "seq") if isinstance(raw, dict) else "seq"

            handler = node_handlers.get(ntype, self._handle_seq_node)
            step_idx = handler(step_idx, raw, default_next, n_steps)
            
            if self._shiny_flag:
                return

    def _run(self) -> None:
        n_steps = len(self._steps)
        dlog(f"[plan] started — {n_steps} steps, "
             f"loops={self._total_loops or '∞'}")
        try:
            while not self._abort_event.is_set():
                if self._total_loops > 0 and self.loop_count >= self._total_loops:
                    dlog("[plan] total loops reached")
                    break
                self.loop_count += 1
                dlog(f"[plan] === loop {self.loop_count} ===")
                
                self._run_node_loop()
                if self._shiny_flag:
                    return
        except Exception as exc:
            dlog(f"[plan] FATAL ERROR in run loop: {exc}")
            self._abort_event.set()
        finally:
            self.is_running = False
            dlog(f"[plan] finished — shiny={self._shiny_flag} "
                 f"loops={self.loop_count}")
            if not self._shiny_flag and self.on_stopped:
                self.on_stopped()

    # ── Condition evaluation ──────────────────────────────────────────────────

    def _eval_condition_bool(self, step_idx: int,
                              condition: Optional[dict]) -> tuple[bool, float]:
        """Evaluate *condition* and return (matched, confidence).
        Used by CONDITION nodes (node_type='condition') in the graph.
        """
        if not condition:
            return False, 0.0
        ctype = condition.get("type", "")
        if not ctype:
            return False, 0.0

        is_image = ctype in ("image_match", "image_list", "image", "mixed")
        is_ocr   = ctype in ("ocr", "mixed")
        logic    = condition.get("logic", "any")
        raw_thresh = condition.get("img_threshold", condition.get("threshold", 0.85))
        try:
            threshold = float(raw_thresh)
        except (ValueError, TypeError):
            threshold = 0.85

        results: list[bool] = []
        best_conf = 0.0

        if is_image:
            images = condition.get("images") or []
            if images:
                try:
                    matched, conf = self.detector.match_any_image(
                        images, region=None, threshold=threshold)
                    best_conf = max(best_conf, conf)
                    results.append(matched)
                    dlog(f"[plan cond bool] step={step_idx} img matched={matched} conf={conf:.3f}")
                except (ValueError, TypeError, KeyError) as exc:
                    dlog(f"[plan cond bool] step={step_idx} logic error in img config: {exc}")
                    results.append(False)
                except Exception as exc:
                    dlog(f"[plan cond bool] step={step_idx} img error: {exc}\n{traceback.format_exc()}")
                    results.append(False)

        if is_ocr:
            for ocr_check in (condition.get("ocr_checks") or []):
                raw_reg = ocr_check.get("region")
                region  = tuple(raw_reg) if raw_reg else None
                pattern = ocr_check.get("text", "").strip()
                
                mode_str = ocr_check.get("mode", "contains")
                try:
                    mode = MatchMode(mode_str)
                except ValueError:
                    mode = MatchMode.CONTAINS
                
                if not pattern:
                    continue
                try:
                    text    = self.detector.scan_text(region=region)
                    shiny_func = getattr(self.detector, 'is_shiny_text', getattr(self.detector, '_is_shiny_text', None))
                    matched = _text_matches(text, pattern, mode, shiny_func)
                    results.append(matched)
                    dlog(f"[plan cond bool] step={step_idx} ocr pattern={repr(pattern)} "
                         f"mode={mode.value} matched={matched} text={repr(text)}")
                except (ValueError, TypeError, KeyError) as exc:
                    dlog(f"[plan cond bool] step={step_idx} logic error in ocr config: {exc}")
                    results.append(False)
                except Exception as exc:
                    dlog(f"[plan cond bool] step={step_idx} ocr error: {exc}\n{traceback.format_exc()}")
                    results.append(False)

        if not results:
            return False, 0.0

        overall = all(results) if logic == "all" else any(results)
        return overall, best_conf

    # ── Inline OCR handler ────────────────────────────────────────────────────

    def _make_inline_handler(self, loop_n: int):
        """Return the ocr_check callback for a specific loop."""
        def _handler() -> bool:
            if self._abort_event.is_set():
                return True
            try:
                is_shiny, text = self.detector.check_shiny_ocr()
            except Exception as exc:
                dlog(f"[plan ocr] error: {exc}\n{traceback.format_exc()}")
                return False

            dlog(f"[plan ocr] shiny={is_shiny} text={repr(text)}")
            if self.on_ocr:
                self.on_ocr(loop_n, is_shiny, text)
            if is_shiny:
                self._shiny_flag = True
                self._abort_event.set()
                if self.on_shiny:
                    self.on_shiny(loop_n, text)
                return True   # tell player to stop immediately
            return False
        return _handler
