@echo off
cd /d "%~dp0"
setlocal EnableDelayedExpansion
title Pokemon Auto Shiny — Build Installer

echo.
echo ============================================================
echo   Pokemon Auto Shiny — 1-Click Installer Builder
echo ============================================================
echo.

:: ── Locate Python ──────────────────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo         Please install Python 3.10+ and check "Add to PATH"
    pause & exit /b 1
)

for /f "delims=" %%V in ('python --version 2^>^&1') do set PYVER=%%V
echo [OK] %PYVER%

:: ── Check / install PyInstaller ────────────────────────────────────────────
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [..] Installing PyInstaller...
    python -m pip install pyinstaller --quiet
)
for /f "delims=" %%V in ('python -m PyInstaller --version 2^>^&1') do set PIVER=%%V
echo [OK] PyInstaller %PIVER%

:: ── Step 1: PyInstaller Build ──────────────────────────────────────────────
echo.
echo [1/2] Đang đóng gói ứng dụng (PyInstaller)...
echo       Vui lòng đợi một chút...
echo.

python -m PyInstaller PokemonAutoShiny.spec --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller gặp lỗi. Vui lòng kiểm tra log phía trên.
    pause & exit /b 1
)

if not exist "dist\PokemonAutoShiny\PokemonAutoShiny.exe" (
    echo [ERROR] Không tìm thấy file dist\PokemonAutoShiny\PokemonAutoShiny.exe sau khi build!
    pause & exit /b 1
)
echo.
echo [OK] Đóng gói hoàn tất — thư mục: dist\PokemonAutoShiny\

:: ── Step 2: Locate Inno Setup ──────────────────────────────────────────────
echo.
echo [2/2] Đang tìm công cụ đóng gói cài đặt (Inno Setup)...

set ISCC=
where iscc >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%I in ('where iscc 2^>nul') do set ISCC="%%I"
)

if "!ISCC!"=="" (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    ) do (
        if exist %%P set ISCC=%%P
    )
)

if "!ISCC!"=="" (
    echo.
    echo [WARN] Không tìm thấy Inno Setup 6 để tạo file Setup.exe.
    echo        Tải Inno Setup tại: https://jrsoftware.org/isdl.php
    echo.
    echo        Ứng dụng dạng Portable đã sẵn sàng tại: dist\PokemonAutoShiny\
    echo        Bạn có thể mở dist\PokemonAutoShiny\PokemonAutoShiny.exe để dùng ngay.
    explorer dist\PokemonAutoShiny
    pause & exit /b 0
)

echo [OK] Đã tìm thấy: !ISCC!
echo.
echo Đang nén và tạo file cài đặt Setup.exe...
!ISCC! /DCompressionMode=lzma2/fast installer.iss
if errorlevel 1 (
    echo.
    echo [ERROR] Inno Setup gặp lỗi khi tạo file cài đặt.
    pause & exit /b 1
)

:: ── Complete ───────────────────────────────────────────────────────────────
echo.
echo ============================================================
echo   BUILD HOÀN TẤT THÀNH CÔNG!
echo ============================================================
echo.

if exist "installer\PokemonAutoShiny_Setup.exe" (
    echo   File cài đặt đã sẵn sàng: installer\PokemonAutoShiny_Setup.exe
    for %%F in ("installer\PokemonAutoShiny_Setup.exe") do (
        set /a SIZE_MB=%%~zF / 1048576
        echo   Dung lượng: !SIZE_MB! MB
    )
    echo.
    echo   Đang mở thư mục chứa file cài đặt...
    explorer /select,"installer\PokemonAutoShiny_Setup.exe"
) else (
    echo   Thư mục app: dist\PokemonAutoShiny\
    explorer dist\PokemonAutoShiny
)

echo.
pause
