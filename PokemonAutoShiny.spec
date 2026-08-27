# -*- mode: python ; coding: utf-8 -*-
"""
PokemonAutoShiny.spec — PyInstaller build configuration.

Build:
    pyinstaller PokemonAutoShiny.spec --noconfirm

Output: dist\PokemonAutoShiny\PokemonAutoShiny.exe  (folder distribution)

Notes
-----
* EasyOCR model weights (~150 MB) are downloaded on first app launch to
  %USERPROFILE%\.EasyOCR\model\ — NOT bundled to keep installer size sane.
  A first-run splash shows progress so the user knows what is happening.
* torch + easyocr make the dist folder large (~1–3 GB).
* Inno Setup (installer.iss) wraps the dist folder into a single Setup.exe.
"""

import os
import glob
import torch
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

block_cipher = None

# ── Collect data files from packages ─────────────────────────────────────────
ctk_datas    = collect_data_files("customtkinter")
easyocr_data = collect_data_files("easyocr")

# ── Collect Torch DLLs & MSVC Runtime DLLs explicitly ─────────────────────────
torch_lib_dir = os.path.join(os.path.dirname(torch.__file__), "lib")
torch_dlls = []
if os.path.exists(torch_lib_dir):
    for f in os.listdir(torch_lib_dir):
        if f.lower().endswith(".dll"):
            full_path = os.path.join(torch_lib_dir, f)
            torch_dlls.append((full_path, "torch/lib"))

msvc_dlls = []
for pattern in ("msvcp140*.dll", "vcruntime140*.dll", "vcomp140*.dll"):
    for f in glob.glob(os.path.join(r"C:\Windows\System32", pattern)):
        msvc_dlls.append((f, "."))

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[
        *torch_dlls,
        *msvc_dlls,
    ],
    datas=[
        # ── App own data ──────────────────────────────────────────────────────
        ("data",   "data"),          # movement sequences folder
        # ── Library assets ────────────────────────────────────────────────────
        *ctk_datas,
        *easyocr_data,
    ],
    hiddenimports=[
        # ── CustomTkinter ──────────────────────────────────────────────────────
        "customtkinter",
        # ── PIL / Pillow ──────────────────────────────────────────────────────
        "PIL._tkinter_finder",
        "PIL.Image", "PIL.ImageTk", "PIL.ImageDraw",
        # ── pynput Windows backend ────────────────────────────────────────────
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
        # ── pywin32 ───────────────────────────────────────────────────────────
        "win32api", "win32con", "win32gui", "win32process",
        "pywintypes",
        # ── EasyOCR + deps ────────────────────────────────────────────────────
        "easyocr",
        "skimage", "skimage.transform", "skimage.morphology",
        "scipy", "scipy.special", "scipy.ndimage",
        "scipy.spatial", "scipy.sparse",
        # ── torch / torchvision ───────────────────────────────────────────────
        "torch", "torch.nn", "torch.nn.functional",
        "torchvision", "torchvision.transforms",
        # ── OpenCV ────────────────────────────────────────────────────────────
        "cv2",
        # ── Misc ──────────────────────────────────────────────────────────────
        "packaging.version",
        "numpy",
    ],
    hookspath=["hooks"],
    hooksconfig={},
    runtime_hooks=["hooks/rthook_torch.py"],
    excludes=[
        # Strip test/notebook bloat
        "IPython", "jupyter", "matplotlib", "pandas",
        "pytest", "unittest", "tkinter.test",
        # Heavy AI packages not used by PokemonAutoShiny
        "transformers", "llvmlite", "tokenizers", "onnxruntime", "hf_xet",
        "torch.testing", "torch.distributed",
        "scipy.signal", "scipy.optimize", "scipy.interpolate", "scipy.integrate",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PokemonAutoShiny",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX off — torch DLLs corrupt under UPX
    console=False,      # GUI app: no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,          # icon="assets\\icon.ico" if you add one
    version=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PokemonAutoShiny",
)
