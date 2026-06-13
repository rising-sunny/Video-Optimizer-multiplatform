@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

:: ══════════════════════════════════════════════════════════════
::  GENERATE_SHORT.bat — Genera un Short diario con un click
:: ══════════════════════════════════════════════════════════════

title Daily Short Pipeline - Stunning Revelations

:: Buscar el venv
set "VENV_BASE=%LOCALAPPDATA%\venvs"
set "VENV_PYTHON="

:: Buscar cualquier venv de video_optimizer
for /d %%D in ("%VENV_BASE%\video_optimizer_*") do (
    if exist "%%D\Scripts\python.exe" (
        set "VENV_PYTHON=%%D\Scripts\python.exe"
    )
)

if "%VENV_PYTHON%"=="" (
    echo.
    echo ERROR: No se encontro el entorno virtual.
    echo Ejecuta START_VISIBLE.bat primero para crear el venv.
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
