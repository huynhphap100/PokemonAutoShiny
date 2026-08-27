============================================================
  POKEMON AUTO SHINY — Installation Guide
============================================================

SYSTEM REQUIREMENTS
-------------------
  - Windows 10 / 11  (64-bit)
  - Internet connection on first launch (to download AI models ~150 MB)
  - 2 GB free disk space

HOW TO INSTALL
--------------
  1. Double-click  PokemonAutoShiny_Setup.exe
  2. Follow the installer wizard (click Next → Install)
  3. Check "Launch Pokemon Auto Shiny now" at the end

FIRST LAUNCH
------------
  The first time you open the app, a setup window will appear:

    "Downloading OCR model weights..."

  This downloads the AI text-recognition models (~150 MB) once.
  Requires internet. Takes 1–3 minutes depending on your connection.
  After that, the app opens instantly every time.

WHAT GETS INSTALLED
-------------------
  - The app itself (in Program Files)
  - Microsoft Visual C++ 2022 Runtime (if not already present)
  - AI models are saved to: %USERPROFILE%\.EasyOCR\model\

UNINSTALL
---------
  Control Panel → Programs → Pokemon Auto Shiny → Uninstall
  (or Settings → Apps → Pokemon Auto Shiny → Uninstall)

TROUBLESHOOTING
---------------
  • App won't open:
    Make sure you are on Windows 10 or later (64-bit).

  • First-launch download fails:
    Check your internet connection and try again.
    The app will retry the download on next launch.

  • Black screen / crash:
    Delete the folder  %USERPROFILE%\.EasyOCR\  and relaunch
    to re-download models fresh.

  • Sequences not found:
    Place your .json sequence files in the  data\movements\  folder
    next to PokemonAutoShiny.exe.

============================================================
