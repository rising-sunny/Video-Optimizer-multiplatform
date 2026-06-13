@echo off
title Video Optimizer Pro
chcp 65001 > nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo ================================================================
echo Video Optimizer Pro - Inicio Portable
echo ================================================================
echo.

cd /d "%~dp0"

IF NOT EXIST ".\python_portable\python.exe" (
    echo [ERROR] No se encontro el entorno portable en '.\python_portable\python.exe'
    echo Usa el script 'make_portable.ps1' [Boton derecho Ejecutar con PowerShell] primero para descargarlo.
    pause
    exit /b 1
)

echo Iniciando aplicacion aislada del sistema operativo...
.\python_portable\python.exe video_optimizer_pyqt6.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Ocurrio un error critico. Deteniendo la app para inspeccion.
    pause
)
