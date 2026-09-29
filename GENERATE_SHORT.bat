@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

:: ══════════════════════════════════════════════════════════════
::  GENERATE_SHORT.bat — Genera un Short diario con un click
:: ══════════════════════════════════════════════════════════════

title Daily Short Pipeline - Stunning Revelations

:: Venv local del repo (el mismo que crea INSTALL_DEPS.bat y usa RUN.bat)
set "VENV_PYTHON=%~dp0.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo.
    echo ERROR: No se encontro el entorno virtual.
    echo Ejecuta INSTALL_DEPS.bat primero para crear el venv.
    echo.
    pause
    exit /b 1
)

echo.
echo ══════════════════════════════════════════════════════════
echo   Using Python: %VENV_PYTHON%
echo ══════════════════════════════════════════════════════════
echo.

:: Ejecutar pipeline con argumentos pasados al .bat
"%VENV_PYTHON%" "%~dp0daily_short_pipeline.py" %*

echo.
pause
