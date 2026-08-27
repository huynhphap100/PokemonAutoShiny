@echo off
cd /d "%~dp0"
chcp 65001 >nul
title Pokemon Auto Shiny - Install

echo ============================================
echo  Pokemon Auto Shiny - Installing dependencies
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo Please install Python 3.10+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo [OK] Python found:
python --version
echo.

:: Upgrade pip
echo [1/3] Upgrading pip...
python -m pip install --upgrade pip -q

:: Install PyTorch CPU
echo [2/3] Installing PyTorch (CPU)...
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 (
    echo [ERROR] Failed to install PyTorch. Check your internet connection.
    pause
    exit /b 1
)

:: Verify torch works
echo Verifying PyTorch...
python -c "import torch; print('[OK] PyTorch', torch.__version__, '- CPU:', not torch.cuda.is_available() or True)"
if errorlevel 1 (
    echo [ERROR] PyTorch installed but cannot be imported.
    echo Your CPU may not support AVX2. Try Windows Update or contact support.
    pause
    exit /b 1
)

:: Install other requirements
echo [3/3] Installing other packages...
python -m pip install customtkinter pynput pywin32 pillow numpy easyocr
if errorlevel 1 (
    echo [ERROR] Failed to install packages. Check your internet connection.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Installation complete!
echo  Run "run.bat" to start the app.
echo ============================================
pause
