@echo off
cd /d "%~dp0"
chcp 65001 >nul
title Pokemon Auto Shiny

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found! Please run install.bat first.
    pause
    exit /b 1
)

:: Run the app (hide console window)
start "" pythonw main.py
