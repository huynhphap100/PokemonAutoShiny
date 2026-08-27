import os
import sys

# Prevent OpenMP and DLL initialization conflicts on Windows (WinError 1114)
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

if sys.platform.startswith("win"):
    base_dir = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))
    torch_lib_dir = os.path.join(base_dir, "torch", "lib")
    if hasattr(os, "add_dll_directory"):
        for p in (torch_lib_dir, base_dir):
            if os.path.isdir(p):
                try:
                    os.add_dll_directory(p)
                except Exception:
                    pass
    path_entries = [p for p in (torch_lib_dir, base_dir) if os.path.isdir(p)]
    if path_entries:
        os.environ["PATH"] = os.pathsep.join(path_entries) + os.pathsep + os.environ.get("PATH", "")

# Pre-import torch before any GUI or OpenCV imports
try:
    import torch  # noqa: F401
except Exception:
    pass

import customtkinter as ctk
from core.debug_log  import clear_log, dlog
from core.first_run  import ensure_models_ready
from ui.app          import App



def main() -> None:
    clear_log()                              # fresh log each run
    dlog("=== App starting ===")

    # First-launch: download EasyOCR model weights if absent (shows splash)
    ensure_models_ready()

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")     # baseline; colours overridden in App
    app = App()
    dlog("=== App mainloop entered ===")
    app.mainloop()
    dlog("=== App exited ===")


if __name__ == "__main__":
    main()
