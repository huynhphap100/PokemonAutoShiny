"""
core/detector.py — Screen capture + OCR shiny detection.

Primary OCR:   EasyOCR (neural-network, no preprocessing needed, highly accurate)
Fallback OCR:  pytesseract + Tesseract-OCR (classic, lower accuracy on game fonts)
Pixel diff:    Last-resort comparison when no OCR is set up
Image match:   OpenCV matchTemplate (primary) or PIL histogram (fallback)

Dependencies:
  - pillow       — screen capture + image preprocessing
  - numpy        — pixel comparison
  - easyocr      — neural-network OCR (recommended, pip install easyocr)
  - pytesseract + Tesseract-OCR — fallback OCR (optional)
  - opencv-python — image template matching (recommended, pip install opencv-python)
"""
from __future__ import annotations

import os
import threading
from typing import Optional, Tuple

try:
    import numpy as np
    _NP = True
except ImportError:
    _NP = False

try:
    import cv2 as _cv2
    _CV2 = True
except ImportError:
    _CV2 = False

try:
    from PIL import ImageGrab, Image, ImageFilter, ImageEnhance
    _PIL = True
except ImportError:
    _PIL = False

try:
    import pytesseract

    # Auto-detect Tesseract on Windows
    _TESS_PATHS = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        r"C:\Users\%s\AppData\Local\Tesseract-OCR\tesseract.exe" % os.environ.get("USERNAME", ""),
    ]
    for _p in _TESS_PATHS:
        if os.path.exists(_p):
            pytesseract.pytesseract.tesseract_cmd = _p
            break

    # Verify Tesseract is actually usable
    pytesseract.get_tesseract_version()
    _TESS = True
except Exception:
    _TESS = False

# ── EasyOCR (neural-network, primary engine) ──────────────────────────────────
try:
    import easyocr as _easyocr_module
    _EASYOCR_AVAILABLE = True
except ImportError:
    _EASYOCR_AVAILABLE = False

# Singleton reader — loaded once, reused for every call
_EASYOCR_READER = None
_EASYOCR_LOCK   = threading.Lock()
_EASYOCR_READY  = False   # True once model weights are loaded


def _get_easyocr_reader():
    """Return the shared EasyOCR reader, initialising on first call.

    First call takes 3-10 seconds (downloads + loads model weights).
    Subsequent calls return instantly.
    """
    global _EASYOCR_READER, _EASYOCR_READY
    if not _EASYOCR_AVAILABLE:
        return None
    if _EASYOCR_READER is None:
        with _EASYOCR_LOCK:
            if _EASYOCR_READER is None:
                try:
                    _EASYOCR_READER = _easyocr_module.Reader(
                        ['en'],
                        gpu=False,      # CPU-only; safer for all machines
                        verbose=False,
                    )
                    _EASYOCR_READY = True
                except Exception:
                    _EASYOCR_READER = None
    return _EASYOCR_READER


def _group_detections(
    detections: list,
    region_x: int,
    region_y: int,
    gap_y: int = 35,
    gap_x: int = 80,
) -> list:
    """Cluster EasyOCR detections into nameplate-sized groups.

    Phase 1 — Rows: sort by Y, group items whose Y-centers are within
    *gap_y* px of each other into the same horizontal row.

    Phase 2 — Columns: within each row, sort by X, then split whenever
    the pixel gap between adjacent items' bounding boxes exceeds *gap_x*.
    This separates Pokemon nameplates that share a horizontal row but are
    physically distant (e.g. left-side vs right-side names in battle).

    Returns
    -------
    list of (text, sx, sy, sw, sh)
        Screen-absolute coordinates, one entry per connected region.
    """
    if not detections:
        return []

    # ── Parse bounding boxes ──────────────────────────────────────────────────
    items = []
    for (bbox, text, conf) in detections:
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        items.append({
            "cx": (min_x + max_x) / 2,
            "cy": (min_y + max_y) / 2,
            "min_x": min_x, "min_y": min_y,
            "max_x": max_x, "max_y": max_y,
            "text": text,
        })

    # ── Phase 1: group into horizontal rows by Y proximity ────────────────────
    items.sort(key=lambda i: (i["cy"], i["cx"]))

    rows: list[list] = []
    current_row: list = []
    last_cy: float | None = None

    for item in items:
        if last_cy is None or abs(item["cy"] - last_cy) <= gap_y:
            current_row.append(item)
        else:
            rows.append(current_row)
            current_row = [item]
        # Track the average cy of the current row
        last_cy = sum(i["cy"] for i in current_row) / len(current_row)
    if current_row:
        rows.append(current_row)

    # ── Phase 2: split each row by X gaps ────────────────────────────────────
    result = []
    for row in rows:
        row.sort(key=lambda i: i["cx"])       # left-to-right

        segments: list[list] = []
        seg: list = [row[0]]

        for item in row[1:]:
            prev = seg[-1]
            x_gap = item["min_x"] - prev["max_x"]  # gap between bboxes
            if x_gap <= gap_x:
                seg.append(item)
            else:
                segments.append(seg)
                seg = [item]
        segments.append(seg)

        for seg in segments:
            text = " ".join(i["text"] for i in seg)
            min_x = int(min(i["min_x"] for i in seg))
            min_y = int(min(i["min_y"] for i in seg))
            max_x = int(max(i["max_x"] for i in seg))
            max_y = int(max(i["max_y"] for i in seg))
            result.append((
                text,
                region_x + min_x,
                region_y + min_y,
                max_x - min_x,
                max_y - min_y,
            ))

    return result


def preload_easyocr() -> None:
    """Call this from a background thread at startup so the model is ready
    before the user clicks 'Test OCR'."""
    _get_easyocr_reader()

try:
    import win32gui
    import win32ui
    import win32con
    import ctypes as _ctypes
    _WIN32 = True
except ImportError:
    _WIN32 = False

_PW_RENDERFULLCONTENT = 0x2   # PrintWindow flag — renders GPU/DX surfaces


def _capture_via_hwnd(hwnd: int, region: tuple) -> "Image.Image":
    """Capture a screen-absolute region by rendering the game window via Win32.

    Uses ``PrintWindow(PW_RENDERFULLCONTENT)`` so it works even when the
    game window is partially covered by other windows or the app itself.

    Parameters
    ----------
    hwnd   : window handle of the target application
    region : (x, y, w, h) in screen-absolute coordinates (same as stored
             in _ocr_region)
    """
    if not _WIN32:
        raise RuntimeError("pywin32 not available")

    cl = win32gui.GetClientRect(hwnd)   # (0, 0, cw, ch) client-relative
    cw, ch = cl[2], cl[3]
    if cw <= 0 or ch <= 0:
        raise ValueError(f"Invalid client rect: {cl}")

    hwnd_dc = win32gui.GetDC(hwnd)
    try:
        mfc_dc  = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp     = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, cw, ch)
        save_dc.SelectObject(bmp)

        # Render the window (including GPU content) into our bitmap
        _ctypes.windll.user32.PrintWindow(
            hwnd, save_dc.GetSafeHdc(), _PW_RENDERFULLCONTENT
        )

        bmp_info = bmp.GetInfo()
        bmp_str  = bmp.GetBitmapBits(True)
        full_img = Image.frombuffer(
            "RGB",
            (bmp_info["bmWidth"], bmp_info["bmHeight"]),
            bmp_str, "raw", "BGRX", 0, 1,
        )
    finally:
        try:
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)
            win32ui.DeleteObject(bmp.GetHandle())
        except Exception:
            pass

    # Convert region from screen-absolute → window-client coordinates
    client_origin = win32gui.ClientToScreen(hwnd, (0, 0))
    rx, ry, rw, rh = region
    rel_x = rx - client_origin[0]
    rel_y = ry - client_origin[1]
    return full_img.crop((rel_x, rel_y, rel_x + rw, rel_y + rh))


# ─────────────────────────────────────────────────────────────────────────────
# Preprocessing helper
# ─────────────────────────────────────────────────────────────────────────────

def _preprocess_name_bars(img: "Image.Image") -> "Image.Image":
    """Convert a raw PokeMMO battle-screen crop to black-on-white binary.

    Why B–R dominance works
    -----------------------
    PokeMMO battle background: blue  → B ≈ 180-210, R ≈ 40-80  → B-R ≈ 100-150
    Pokemon name text:         white → B ≈ R ≈ G ≈ 220-255     → B-R ≈ 0-20
    Anti-aliased edge pixels:          blend of both            → B-R ≈ 30-90

    Simply rejecting pixels where (B – R) > 70 cleanly separates
    the blue background from the white text without losing anti-aliased edges.

    Steps
    -----
    1. B–R < 70   → text pixel (not blue-dominated)
    2. Require overall brightness > 300 (avg > 100 each channel)
       to exclude dark outlines and shadows.
    3. Output: black text (0) on white background (255)  ← Tesseract-standard.
    4. Scale 3× with NEAREST (preserves crisp binary edges).
    5. Add 20 px white border padding.
    """
    if not _NP:
        return img.convert("L")

    arr = np.array(img.convert("RGB"), dtype=np.int16)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

    # Text  : B – R ≈ 0     (all channels equal = white)
    # Bg    : B – R ≈ 120+  (blue-dominant)
    # Threshold 70 sits comfortably between the two distributions.
    not_blue_bg = (b - r) < 70

    # Brightness guard: discard dark pixels (outlines, shadows, black areas).
    bright = (r + g + b) > 300  # per-channel average > 100

    is_text = not_blue_bg & bright

    # Black text on white background
    binary = np.full(arr.shape[:2], 255, dtype=np.uint8)
    binary[is_text] = 0

    proc = Image.fromarray(binary, mode="L")

    # Scale 3× with NEAREST — preserves crisp edges on binary images
    w, h = proc.size
    proc = proc.resize((w * 3, h * 3), Image.NEAREST)

    # Border padding — Tesseract misses characters near the edge otherwise
    pad = 20
    padded = Image.new("L", (proc.width + pad * 2, proc.height + pad * 2), 255)
    padded.paste(proc, (pad, pad))
    return padded


# ─────────────────────────────────────────────────────────────────────────────

class ScreenDetector:
    """Detect shiny encounters via OCR or pixel-diff comparison.

    OCR workflow (preferred)
    ------------------------
    1. ``set_ocr_region(x, y, w, h)``  — mark the name-bar area on screen
    2. ``check_shiny_ocr()``           — read text; returns (is_shiny, text)

    Pixel-diff workflow (fallback)
    ------------------------------
    1. ``capture_reference(hwnd)``     — save "normal" frame
    2. ``compare(hwnd)``               — 0-100 % similarity
    """

    def __init__(self) -> None:
        self._reference: Optional["np.ndarray"] = None
        self._ocr_region: Optional[Tuple[int, int, int, int]] = None  # x,y,w,h screen-abs
        self._target_hwnd: Optional[int] = None
        self._lock = threading.Lock()

    # ── Target window ─────────────────────────────────────────────────────────

    def set_target_hwnd(self, hwnd: Optional[int]) -> None:
        """Set the game window handle used for direct window capture."""
        with self._lock:
            self._target_hwnd = hwnd

    def _capture_region(self, region: tuple) -> "Image.Image":
        """Capture the OCR region from the game window or screen.

        Priority:
          1. Win32 PrintWindow (hwnd-based) — works even if window is covered
          2. ImageGrab.grab() — fallback when pywin32 unavailable or hwnd unset
        """
        with self._lock:
            hwnd = self._target_hwnd

        if hwnd and _WIN32:
            try:
                return _capture_via_hwnd(hwnd, region)
            except Exception as exc:
                from core.debug_log import dlog
                dlog(f"[capture] hwnd capture failed ({exc}), falling back to ImageGrab")

        # Fallback: screen coordinates capture
        x, y, w, h = region
        return ImageGrab.grab(bbox=(x, y, x + w, y + h))

    # ── OCR region ────────────────────────────────────────────────────────────

    def set_ocr_region(self, x: int, y: int, w: int, h: int) -> None:
        with self._lock:
            self._ocr_region = (x, y, w, h)

    def get_ocr_region(self) -> Optional[Tuple[int, int, int, int]]:
        with self._lock:
            return self._ocr_region

    def has_ocr_region(self) -> bool:
        with self._lock:
            return self._ocr_region is not None

    def clear_ocr_region(self) -> None:
        with self._lock:
            self._ocr_region = None

    # ── OCR detection ─────────────────────────────────────────────────────────

    def check_shiny_ocr(self) -> Tuple[bool, str]:
        """Capture OCR region and look for 'Shiny' in any Pokémon name bar.

        Engine priority
        ---------------
        1. EasyOCR  — neural-network OCR, no preprocessing needed,
                      handles game fonts and anti-aliasing very well.
        2. Tesseract — classic OCR with B-R dominance preprocessing,
                       used as fallback when EasyOCR is not installed.

        Returns
        -------
        (is_shiny, text)
        """
        if not _PIL:
            return False, "Pillow not installed"

        with self._lock:
            region = self._ocr_region
        if region is None:
            return False, "No OCR region set"

        x, y, w, h = region
        try:
            raw_img = self._capture_region(region)

            # ── EasyOCR path (primary) ─────────────────────────────────────────
            reader = _get_easyocr_reader()
            if reader is not None and _NP:
                arr = np.array(raw_img)
                detections = reader.readtext(
                    arr,
                    detail=1,
                    paragraph=False,
                    batch_size=4,
                )
                # Collect all words with confidence >= 30%
                words = [
                    text
                    for (_, text, conf) in detections
                    if conf >= 0.30
                ]
                combined = " | ".join(words)
                is_shiny = self._is_shiny_text(combined)
                return is_shiny, combined

            # ── Tesseract fallback ─────────────────────────────────────────────
            if not _TESS:
                return False, "No OCR engine available (install easyocr or Tesseract)"

            processed = _preprocess_name_bars(raw_img)
            results: list[str] = []
            for psm in (11, 6):
                cfg = f"--psm {psm} --oem 1"
                try:
                    raw = pytesseract.image_to_string(
                        processed, lang="eng", config=cfg)
                    results.append(raw.strip())
                except Exception:
                    pass
            combined = "\n".join(results)
            best = max(results, key=len) if results else ""
            return self._is_shiny_text(combined), best

        except Exception as exc:
            return False, f"OCR error: {exc}"

    def check_shiny_ocr_with_boxes(self):
        """Like check_shiny_ocr() but also returns grouped bounding boxes.

        Returns
        -------
        (is_shiny, text, groups)
            groups — list of (group_text, screen_x, screen_y, width, height)
                     Each group is a cluster of nearby OCR detections.
                     Coordinates are absolute screen pixels.
                     Empty list when EasyOCR is unavailable or no detections.
        """
        with self._lock:
            region = self._ocr_region
        if region is None:
            return False, "No OCR region set", []

        rx, ry, rw, rh = region
        try:
            raw_img = self._capture_region(region)

            reader = _get_easyocr_reader()
            if reader is not None and _NP:
                arr = np.array(raw_img)
                detections = reader.readtext(
                    arr, detail=1, paragraph=False, batch_size=4,
                )
                good = [(bbox, text, conf)
                        for (bbox, text, conf) in detections
                        if conf >= 0.25 and text.strip()]
                combined = " | ".join(t for _, t, _ in good)
                is_shiny = self._is_shiny_text(combined)
                groups = _group_detections(good, rx, ry)
                return is_shiny, combined, groups

        except Exception as exc:
            pass

        # Fallback: plain check, no boxes
        is_shiny, text = self.check_shiny_ocr()
        return is_shiny, text, []

    def scan_text(
        self,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> str:
        """Capture *region* (or full game window) and return all OCR text.

        Unlike ``check_shiny_ocr``, this is a general-purpose scan that
        returns the raw concatenated text from every detected word, with
        no shiny-specific filtering.  Useful for plan conditions that need
        to detect arbitrary game text (dialog boxes, menus, HP bars, etc.)

        Parameters
        ----------
        region : (x, y, w, h) screen-absolute, optional
            If None, the **entire game window** client area is scanned.

        Returns
        -------
        str
            Whitespace-separated OCR words joined by spaces.
            Empty string on failure.
        """
        if not _PIL:
            return ""

        try:
            if region is not None:
                raw_img = self._capture_region(region)
            else:
                raw_img = self._capture_full_window()
                if raw_img is None:
                    return ""
            raw_img = raw_img.convert("RGB")
        except Exception as exc:
            from core.debug_log import dlog
            dlog(f"[scan_text] capture failed: {exc}")
            return ""

        # ── EasyOCR path (primary) ─────────────────────────────────────────────
        reader = _get_easyocr_reader()
        if reader is not None and _NP:
            try:
                arr = np.array(raw_img)
                detections = reader.readtext(arr, detail=1, paragraph=False, batch_size=4)
                words = [text for (_, text, conf) in detections if conf >= 0.25]
                return " ".join(words)
            except Exception as exc:
                from core.debug_log import dlog
                dlog(f"[scan_text] EasyOCR error: {exc}")

        # ── Tesseract fallback ─────────────────────────────────────────────────
        if _TESS:
            try:
                processed = _preprocess_name_bars(raw_img)
                cfg = "--psm 11 --oem 1"
                text = pytesseract.image_to_string(processed, lang="eng", config=cfg)
                return text.strip()
            except Exception as exc:
                from core.debug_log import dlog
                dlog(f"[scan_text] Tesseract error: {exc}")

        return ""


    @staticmethod
    def _is_shiny_text(text: str) -> bool:
        """Return True if ``text`` contains 'Shiny' or a common OCR misreading.

        Known EasyOCR substitutions observed on PokeMMO game font:
          'i' -> '1' / 'l' / '!' / 'f'   (thin strokes misread)
          'n' -> 'm'                       (EasyOCR reads 'Shiny' as 'Shimy')
          'y' -> 'v'                       (descender misread)
          'Lv.' -> 'Lvo'                   (period fused with 'o')
        """
        lo = text.lower()
        if "shiny" in lo:
            return True
        import re as _re
        # sh + [i/l/1/!/f] + [n/m] + [y/v]
        # covers: shiny, sh1ny, shlny, shimy, sh1my, shinv, shimv …
        return bool(_re.search(r'sh[il1!f][nm][yv]', lo))

    def test_ocr(self) -> Tuple[bool, str]:
        """Convenience alias for UI 'Test OCR' button."""
        return self.check_shiny_ocr()

    def get_ocr_preview(self, size: Tuple[int, int] = (220, 108)) -> Optional["Image.Image"]:
        """Return a PIL thumbnail of the raw OCR region (for the thumbnail widget)."""
        if not _PIL:
            return None
        with self._lock:
            region = self._ocr_region
        if region is None:
            return None
        x, y, w, h = region
        try:
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            img.thumbnail(size, Image.LANCZOS)
            return img
        except Exception:
            return None

    def get_preprocessed_preview(self, size: Tuple[int, int] = (220, 108)) -> Optional["Image.Image"]:
        """Return the preprocessed (black-on-white) image so the user can verify OCR input."""
        if not (_PIL and _NP):
            return None
        with self._lock:
            region = self._ocr_region
        if region is None:
            return None
        x, y, w, h = region
        try:
            raw_img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            proc = _preprocess_name_bars(raw_img)
            proc.thumbnail(size, Image.LANCZOS)
            return proc
        except Exception:
            return None

    # ── Availability checks ───────────────────────────────────────────────────

    @staticmethod
    def is_ocr_available() -> bool:
        return _TESS and _PIL

    @staticmethod
    def is_available() -> bool:
        return _PIL and _NP and _WIN32

    # ── Pixel-diff (fallback) ─────────────────────────────────────────────────

    def capture_window(self, hwnd: int) -> "Optional[np.ndarray]":
        if not (_PIL and _NP and _WIN32 and hwnd):
            return None
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            if right <= left or bottom <= top:
                return None
            img = ImageGrab.grab(bbox=(left, top, right, bottom))
            return np.array(img.convert("RGB"), dtype=np.uint8)
        except Exception:
            return None

    def capture_reference(self, hwnd: int) -> bool:
        arr = self.capture_window(hwnd)
        if arr is None:
            return False
        with self._lock:
            self._reference = arr
        return True

    def has_reference(self) -> bool:
        with self._lock:
            return self._reference is not None

    def clear_reference(self) -> None:
        with self._lock:
            self._reference = None

    def compare(self, hwnd: int) -> float:
        if not _NP:
            return 100.0
        with self._lock:
            if self._reference is None:
                return 100.0
            ref = self._reference.copy()
        current = self.capture_window(hwnd)
        if current is None:
            return 100.0
        if current.shape != ref.shape:
            try:
                img = Image.fromarray(current)
                img = img.resize((ref.shape[1], ref.shape[0]), Image.LANCZOS)
                current = np.array(img, dtype=np.uint8)
            except Exception:
                return 100.0
        mean_diff = float(np.mean(np.abs(
            current.astype(np.float32) - ref.astype(np.float32)
        )))
        return round(max(0.0, 100.0 - mean_diff / 2.55), 1)

    def get_reference_thumbnail(self, size: Tuple[int, int] = (220, 130)) -> Optional["Image.Image"]:
        if not _PIL:
            return None
        with self._lock:
            if self._reference is None:
                return None
            ref = self._reference.copy()
        try:
            img = Image.fromarray(ref)
            img.thumbnail(size, Image.LANCZOS)
            return img
        except Exception:
            return None

    # ── Image template matching ───────────────────────────────────────────────

    def _capture_full_window(self) -> "Optional[Image.Image]":
        """Capture the entire client area of the target game window.

        Falls back to a full-screen grab when pywin32 is unavailable or no
        hwnd is set.  Returns None on failure.
        """
        if not _PIL:
            return None
        with self._lock:
            hwnd = self._target_hwnd

        if hwnd and _WIN32:
            try:
                import win32gui as _wg
                cl = _wg.GetClientRect(hwnd)   # (0, 0, cw, ch)
                cw, ch = cl[2], cl[3]
                if cw > 0 and ch > 0:
                    # Use the existing _capture_via_hwnd with full-client region.
                    # ClientToScreen gives us the screen-absolute origin.
                    ox, oy = _wg.ClientToScreen(hwnd, (0, 0))
                    return _capture_via_hwnd(hwnd, (ox, oy, cw, ch))
            except Exception as exc:
                from core.debug_log import dlog
                dlog(f"[capture_full_window] hwnd failed ({exc}), using ImageGrab")

        # Fallback: full screen grab
        try:
            return ImageGrab.grab()
        except Exception:
            return None

    def match_image(
        self,
        template_path: str,
        region: Optional[Tuple[int, int, int, int]] = None,
        threshold: float = 0.85,
    ) -> Tuple[bool, float]:
        """Capture *region* (or the full game window if None) and check if
        *template_path* appears inside it via template matching.

        Uses OpenCV ``matchTemplate`` (TM_CCOEFF_NORMED) when available,
        falls back to a simple PIL histogram correlation otherwise.

        Parameters
        ----------
        template_path : str
            Absolute or relative path to the reference PNG/JPG image.
        region : (x, y, w, h) screen-absolute, optional
            If None, the **entire game window** client area is scanned.
        threshold : float
            Match is considered positive when confidence >= threshold.

        Returns
        -------
        (matched: bool, confidence: float 0-1)
        """
        if not _PIL:
            return False, 0.0

        try:
            template_img = Image.open(template_path).convert("RGB")
        except Exception as exc:
            from core.debug_log import dlog
            dlog(f"[match_image] cannot load template '{template_path}': {exc}")
            return False, 0.0

        # Capture source: full game window when no region given
        try:
            if region is not None:
                screen_img = self._capture_region(region).convert("RGB")
            else:
                screen_img = self._capture_full_window()
                if screen_img is None:
                    return False, 0.0
                screen_img = screen_img.convert("RGB")
        except Exception as exc:
            from core.debug_log import dlog
            dlog(f"[match_image] capture failed: {exc}")
            return False, 0.0

        # ── OpenCV path (primary) ─────────────────────────────────────────────
        if _CV2 and _NP:
            try:
                screen_arr = _cv2.cvtColor(np.array(screen_img), _cv2.COLOR_RGB2BGR)
                tmpl_arr   = _cv2.cvtColor(np.array(template_img), _cv2.COLOR_RGB2BGR)

                # Template must not be larger than screen
                sh, sw = screen_arr.shape[:2]
                th, tw = tmpl_arr.shape[:2]
                if th > sh or tw > sw:
                    # Scale template down to fit
                    scale = min(sh / th, sw / tw)
                    new_w, new_h = max(1, int(tw * scale)), max(1, int(th * scale))
                    tmpl_arr = _cv2.resize(tmpl_arr, (new_w, new_h))
                    th, tw = tmpl_arr.shape[:2]

                if th > sh or tw > sw:
                    return False, 0.0

                result = _cv2.matchTemplate(screen_arr, tmpl_arr, _cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = _cv2.minMaxLoc(result)
                confidence = float(max_val)
                from core.debug_log import dlog
                dlog(f"[match_image] '{template_path}' confidence={confidence:.3f} thresh={threshold}")
                return confidence >= threshold, confidence
            except Exception as exc:
                from core.debug_log import dlog
                dlog(f"[match_image] OpenCV error: {exc}")

        # ── PIL histogram fallback ────────────────────────────────────────────
        try:
            tw, th = template_img.size
            screen_img = screen_img.resize((tw, th), Image.LANCZOS)
            h1 = screen_img.histogram()
            h2 = template_img.histogram()
            # Correlation coefficient between histograms
            n = len(h1)
            mean1 = sum(h1) / n
            mean2 = sum(h2) / n
            num   = sum((a - mean1) * (b - mean2) for a, b in zip(h1, h2))
            den1  = sum((a - mean1) ** 2 for a in h1) ** 0.5
            den2  = sum((b - mean2) ** 2 for b in h2) ** 0.5
            if den1 == 0 or den2 == 0:
                return False, 0.0
            confidence = float(num / (den1 * den2))
            confidence = max(0.0, min(1.0, (confidence + 1) / 2))  # map [-1,1] → [0,1]
            from core.debug_log import dlog
            dlog(f"[match_image PIL] '{template_path}' confidence={confidence:.3f} thresh={threshold}")
            return confidence >= threshold, confidence
        except Exception as exc:
            from core.debug_log import dlog
            dlog(f"[match_image PIL] error: {exc}")
            return False, 0.0

    def match_any_image(
        self,
        template_paths: list,
        region: Optional[Tuple[int, int, int, int]] = None,
        threshold: float = 0.85,
    ) -> Tuple[bool, float]:
        """Return True if *any* image in *template_paths* matches the screen region.

        Short-circuits on first match. Returns (matched, best_confidence).
        """
        best_conf = 0.0
        for path in template_paths:
            matched, conf = self.match_image(path, region=region, threshold=threshold)
            if conf > best_conf:
                best_conf = conf
            if matched:
                return True, best_conf
        return False, best_conf

    @staticmethod
    def is_image_match_available() -> bool:
        """Return True if OpenCV is installed (best-quality matching)."""
        return _CV2 and _NP
