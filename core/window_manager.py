"""
Window Manager — enumerate running windows and post virtual input directly to them.

Requires pywin32 (pip install pywin32).
When pywin32 is unavailable the module degrades gracefully: functions return
sensible fallbacks and `is_available()` returns False.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

try:
    import win32api
    import win32con
    import win32gui
    import win32process
    _WIN32 = True
except ImportError:
    _WIN32 = False


# ── Virtual-key map (stored key-string → Windows VK code) ────────────────────

def _vk(name: str) -> int:
    """Return win32con attribute by name, or 0 if unavailable."""
    return getattr(win32con, name, 0) if _WIN32 else 0

# ── Virtual-key lookup ────────────────────────────────────────────────────────

# Static fast-path for the most common keys
_VK_STATIC: dict[str, int] = {
    "Key.up":    0x26, "Key.down":  0x28, "Key.left":  0x25, "Key.right": 0x27,
    "Key.enter": 0x0D, "Key.space": 0x20, "Key.esc":   0x1B, "Key.tab":   0x09,
    "Key.backspace": 0x08, "Key.delete": 0x2E,
    "Key.home":  0x24, "Key.end":   0x23,
    "Key.page_up": 0x21, "Key.page_down": 0x22,
    "Key.insert": 0x2D,
    "Key.f1":  0x70, "Key.f2":  0x71, "Key.f3":  0x72, "Key.f4":  0x73,
    "Key.f5":  0x74, "Key.f6":  0x75, "Key.f7":  0x76, "Key.f8":  0x77,
    "Key.f9":  0x78, "Key.f10": 0x79, "Key.f11": 0x7A, "Key.f12": 0x7B,
    "Key.shift":     0x10, "Key.shift_r":  0xA1,
    "Key.ctrl":      0x11, "Key.ctrl_r":   0xA3, "Key.ctrl_l":  0xA2,
    "Key.alt":       0x12, "Key.alt_r":    0xA5, "Key.alt_l":   0xA4,
    "Key.cmd":       0x5B, "Key.cmd_r":    0x5C,
    "Key.caps_lock": 0x14, "Key.num_lock": 0x90,
    "Key.print_screen": 0x2C, "Key.scroll_lock": 0x91, "Key.pause": 0x13,
    # Full a–z alphabet (VK_A=0x41 … VK_Z=0x5A) — stored lower AND upper
    # so pynput’s "'z'" / "'Z'" keys are always resolved without VkKeyScan.
    **{f"'{chr(c)}'": 0x41 + (c - ord('a')) for c in range(ord('a'), ord('z') + 1)},
    **{f"'{chr(c)}'": 0x41 + (c - ord('A')) for c in range(ord('A'), ord('Z') + 1)},
    # Digits 0–9
    "'0'": 0x30, "'1'": 0x31, "'2'": 0x32, "'3'": 0x33, "'4'": 0x34,
    "'5'": 0x35, "'6'": 0x36, "'7'": 0x37, "'8'": 0x38, "'9'": 0x39,
}


def _get_vk(key_str: str) -> int:
    """Return a Windows virtual-key code for *any* pynput key string.

    Fast-path: static table.  Fallback: VkKeyScan for char keys.
    Returns 0 when the key cannot be mapped.
    """
    vk = _VK_STATIC.get(key_str, 0)
    if vk:
        return vk
    if not _WIN32:
        return 0
    # Quoted single char: "'x'"
    if key_str.startswith("'") and key_str.endswith("'"):
        inner = key_str[1:-1]
        if len(inner) == 1:
            try:
                vk_full = win32api.VkKeyScan(inner)
                vk = vk_full & 0xFF
                return vk if vk != 0xFF else 0
            except Exception:
                return 0
    # Key.xxx — try VK_{NAME}
    if key_str.startswith("Key."):
        name = key_str[4:].upper().replace("_", "")
        vk = getattr(win32con, f"VK_{name}", 0)
        return vk if vk else 0
    return 0



# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class WindowInfo:
    hwnd:  int
    title: str

    def label(self, max_len: int = 36) -> str:
        return self.title[:max_len] + "…" if len(self.title) > max_len else self.title


# ── Public API ────────────────────────────────────────────────────────────────

def is_available() -> bool:
    """Return True if pywin32 is installed and the module is functional."""
    return _WIN32


def list_windows() -> list[WindowInfo]:
    """Return all visible, titled windows sorted by title."""
    if not _WIN32:
        return []
    results: list[WindowInfo] = []

    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                results.append(WindowInfo(hwnd=hwnd, title=title))
        return True

    win32gui.EnumWindows(_cb, None)
    return sorted(results, key=lambda w: w.title.lower())


def is_valid(hwnd: int) -> bool:
    """Check whether the window handle still refers to an existing window."""
    if not _WIN32 or not hwnd:
        return False
    try:
        return bool(win32gui.IsWindow(hwnd))
    except Exception:
        return False


def get_title(hwnd: int) -> str:
    if not _WIN32 or not hwnd:
        return ""
    try:
        return win32gui.GetWindowText(hwnd)
    except Exception:
        return ""


def bring_to_front(hwnd: int) -> None:
    """Restore and foreground the target window."""
    if not _WIN32 or not hwnd:
        return
    try:
        win32gui.ShowWindow(hwnd, 9)       # SW_RESTORE
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.12)
    except Exception:
        pass


def is_foreground(hwnd: int) -> bool:
    """Return True if *hwnd* is currently the foreground (active) window."""
    if not _WIN32 or not hwnd:
        return False
    try:
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        return False


# ── Virtual keyboard ──────────────────────────────────────────────────────────

def send_key_down(hwnd: int, key_str: str) -> bool:
    """Post WM_KEYDOWN to *hwnd* — background-safe.

    Strategy (three messages queued in order):
    1. WM_ACTIVATE(WA_ACTIVE)  — LWJGL / Java AWT tracks an 'activated' flag
       separately from 'focused'.  Both must be true for key events to fire.
    2. WM_SETFOCUS             — sets the 'focused' flag.
    3. WM_KEYDOWN              — the actual key, processed after both flags are set.

    Because all three are PostMessage’d atomically before the game’s message
    pump runs, they arrive in order with no real OS messages interleaved.
    The game’s display thread then processes them sequentially:
    activated=True → focused=True → key accepted.

    Bit 24 (extended key) is set for arrow/nav keys so the game does not
    mistake them for numpad equivalents.
    """
    if not _WIN32:
        return False
    vk = _get_vk(key_str)
    if not vk:
        return False
    try:
        scan   = win32api.MapVirtualKey(vk, 0)
        lparam = 1 | (scan << 16)
        if vk in _EXTENDED_VKS:
            lparam |= (1 << 24)   # extended-key flag — required for arrows/nav
        # Tell the game it is both 'activated' and 'focused' before the key.
        # WA_ACTIVE = 1 (activated, not by mouse click).
        win32gui.PostMessage(hwnd, win32con.WM_ACTIVATE, 1, 0)  # WA_ACTIVE
        win32gui.PostMessage(hwnd, win32con.WM_SETFOCUS, 0, 0)
        win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, lparam)
        return True
    except Exception:
        return False


def send_key_down_repeat(hwnd: int, key_str: str) -> bool:
    """Re-send a held key every ~30 ms while it should be held down.

    Alt-tab problem fix
    -------------------
    When the user alt-tabs, Windows sends WM_ACTIVATE(WA_INACTIVE) to the
    game via SendMessage (synchronous, immediate).  LWJGL / Java AWT react by
    calling ``resetPressed()`` which clears every key from the internal pressed
    set.  If our subsequent repeat WM_KEYDOWN carried bit 30 = 1 ('key already
    held'), the game would see "repeat of a key it doesn't know is pressed" and
    ignore the movement.

    To recover automatically we:
    1. Re-send WM_ACTIVATE(WA_ACTIVE) + WM_SETFOCUS so the game considers
       itself focused again (same as the initial key-down).
    2. Use bit 30 = 0 (fresh press, not repeat) so the game re-adds the key
       to its pressed set even after a resetPressed() call.

    For movement keys in PokeMMO this is completely transparent — the game
    loop checks 'is key in pressed set' not 'was this a first-press vs repeat'.
    """
    if not _WIN32:
        return False
    vk = _get_vk(key_str)
    if not vk:
        return False
    try:
        scan   = win32api.MapVirtualKey(vk, 0)
        # bit 30 = 0: treat every repeat interval as a fresh press so the
        # game re-adds the key to its pressed set even after resetPressed().
        lparam = 1 | (scan << 16)
        if vk in _EXTENDED_VKS:
            lparam |= (1 << 24)   # extended-key flag
        # Re-establish focus context so the game accepts the key.
        win32gui.PostMessage(hwnd, win32con.WM_ACTIVATE, 1, 0)  # WA_ACTIVE
        win32gui.PostMessage(hwnd, win32con.WM_SETFOCUS, 0, 0)
        win32gui.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, lparam)
        return True
    except Exception:
        return False


def send_key_up(hwnd: int, key_str: str) -> bool:
    """Post WM_KEYUP to *hwnd*."""
    if not _WIN32:
        return False
    vk = _get_vk(key_str)
    if not vk:
        return False
    try:
        scan   = win32api.MapVirtualKey(vk, 0)
        lparam = 1 | (scan << 16) | (3 << 30)
        if vk in _EXTENDED_VKS:
            lparam |= (1 << 24)   # extended-key flag
        win32gui.PostMessage(hwnd, win32con.WM_KEYUP, vk, lparam)
        return True
    except Exception:
        return False


# ── Virtual mouse ─────────────────────────────────────────────────────────────

_BTN = {   # button name → (down_msg, up_msg, mk_flag, di_down, di_up)
    "left":   (0x0201, 0x0202, 0x0001, 0x0002, 0x0004),
    "right":  (0x0204, 0x0205, 0x0002, 0x0008, 0x0010),
    "middle": (0x0207, 0x0208, 0x0010, 0x0020, 0x0040),
}

# ctypes structures for SendInput (keyboard + mouse)
import ctypes
import ctypes.wintypes

class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         ctypes.c_ushort),
        ("wScan",       ctypes.c_ushort),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),  # ULONG_PTR: 4 bytes on 32-bit, 8 on 64-bit
    ]

class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx",          ctypes.c_long),
        ("dy",          ctypes.c_long),
        ("mouseData",   ctypes.c_ulong),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_size_t),  # ULONG_PTR: 4 bytes on 32-bit, 8 on 64-bit
    ]

class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]
    _anonymous_ = ("_u",)
    _fields_    = [("type", ctypes.c_ulong), ("_u", _U)]

_SendInput = ctypes.windll.user32.SendInput if _WIN32 else None

# Keyboard SendInput flags
_KEYEVENTF_KEYUP       = 0x0002
_KEYEVENTF_EXTENDEDKEY = 0x0001

# VK codes that require the EXTENDED_KEY flag
_EXTENDED_VKS: frozenset[int] = frozenset({
    0x21, 0x22, 0x23, 0x24,       # PgUp PgDn End Home
    0x25, 0x26, 0x27, 0x28,       # Left Up Right Down  ← movement arrows
    0x2D, 0x2E,                   # Insert Delete
    0x5B, 0x5C,                   # Left Win Right Win
    0x90, 0x91,                   # NumLock ScrollLock
    0xA1, 0xA3, 0xA5,             # Right Shift/Ctrl/Alt
})


def _si_flags(vk: int, key_up: bool = False) -> int:
    f = _KEYEVENTF_KEYUP if key_up else 0
    if vk in _EXTENDED_VKS:
        f |= _KEYEVENTF_EXTENDEDKEY
    return f


def send_key_down_input(key_str: str) -> bool:
    """Send KEYDOWN via SendInput.

    Unlike PostMessage, this sets GetAsyncKeyState so games that poll
    the hardware key state (e.g. PokeMMO movement) detect the key press.
    The game window must be in the foreground for the event to reach it.
    """
    if not _WIN32 or not _SendInput:
        return False
    vk = _get_vk(key_str)
    if not vk:
        return False
    try:
        scan = win32api.MapVirtualKey(vk, 0)
        inp  = _INPUT(type=1, ki=_KEYBDINPUT(
            wVk=vk, wScan=scan, dwFlags=_si_flags(vk)))
        _SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
        return True
    except Exception:
        return False


def send_key_up_input(key_str: str) -> bool:
    """Send KEYUP via SendInput — clears GetAsyncKeyState."""
    if not _WIN32 or not _SendInput:
        return False
    vk = _get_vk(key_str)
    if not vk:
        return False
    try:
        scan = win32api.MapVirtualKey(vk, 0)
        inp  = _INPUT(type=1, ki=_KEYBDINPUT(
            wVk=vk, wScan=scan, dwFlags=_si_flags(vk, key_up=True)))
        _SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
        return True
    except Exception:
        return False



def _find_target_child(hwnd: int, client_x: int, client_y: int) -> int:
    """Return the deepest visible child window at client-area (x,y), or hwnd itself."""
    if not _WIN32:
        return hwnd
    try:
        child = win32gui.ChildWindowFromPoint(hwnd, (client_x, client_y))
        if child and child != hwnd and win32gui.IsWindowVisible(child):
            return child
    except Exception:
        pass
    return hwnd


def virtual_click(hwnd: int, x: int, y: int, button: str = "left") -> None:
    """Send a virtual mouse click at client-area coords (x, y).

    Strategy (tried in order):
    1. SendMessage → parent hwnd directly
       Sending to the parent (not a child canvas) keeps Java AWT's internal
       keyboard-focus on the main frame so subsequent WM_KEYDOWN events work.
       Posts WM_SETFOCUS afterward to reinforce keyboard context.
    2. SendInput (no cursor restore)
       SetCursorPos(old_pos) would fire WM_MOUSELEAVE to the game and reset
       its key state, breaking movement after the click.  Instead we leave
       the cursor at the click position (inside the game window).
    3. PostMessage fallback.
    """
    if not _WIN32 or not hwnd:
        return

    entry = _BTN.get(button, _BTN["left"])
    down_msg, up_msg, mk, di_down, di_up = entry
    l_param = (y << 16) | (x & 0xFFFF)

    # ── Tier 1: SendMessage → parent hwnd ────────────────────────────────────
    try:
        win32gui.PostMessage(hwnd, win32con.WM_MOUSEMOVE, 0, l_param)
        time.sleep(0.02)
        win32gui.SendMessage(hwnd, down_msg, mk, l_param)
        time.sleep(0.06)
        win32gui.SendMessage(hwnd, up_msg, 0, l_param)
        # Tell the window it still owns keyboard focus
        win32gui.PostMessage(hwnd, win32con.WM_SETFOCUS, 0, 0)
        return
    except Exception:
        pass

    # ── Tier 2: PostMessage fallback (no cursor movement) ────────────────────
    try:
        win32gui.PostMessage(hwnd, down_msg, mk, l_param)
        time.sleep(0.06)
        win32gui.PostMessage(hwnd, up_msg, 0, l_param)
    except Exception:
        pass


# ── Coordinate conversion ─────────────────────────────────────────────────────

def screen_to_client(hwnd: int, sx: int, sy: int) -> tuple[int, int]:
    """Convert screen-absolute (sx, sy) → window client-area (cx, cy)."""
    if not _WIN32 or not hwnd:
        return sx, sy
    try:
        return win32gui.ScreenToClient(hwnd, (sx, sy))
    except Exception:
        return sx, sy
