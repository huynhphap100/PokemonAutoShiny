# PyInstaller runtime hook for PyTorch and Windows DLL loading
import os
import sys

# Prevent OpenMP runtime clash between torch, cv2, and other C libraries
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

if sys.platform.startswith("win"):
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    torch_lib_dir = os.path.join(base_dir, "torch", "lib")

    # Add directories to Windows DLL search path (Python 3.8+)
    if hasattr(os, "add_dll_directory"):
        for p in (torch_lib_dir, base_dir):
            if os.path.isdir(p):
                try:
                    os.add_dll_directory(p)
                except Exception:
                    pass

    # Prepend to PATH for legacy DLL loading
    path_entries = [p for p in (torch_lib_dir, base_dir) if os.path.isdir(p)]
    if path_entries:
        os.environ["PATH"] = os.pathsep.join(path_entries) + os.pathsep + os.environ.get("PATH", "")

    # Pre-import torch so that its internal DLL loading completes before any GUI or other C extensions load
    try:
        import torch
    except Exception:
        pass
