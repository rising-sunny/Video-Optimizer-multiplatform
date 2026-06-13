@echo off
title Video Optimizer Pro
chcp 65001 > nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo ================================================================
echo Video Optimizer Pro - venv local (sin torch; Whisper en el VPS)
echo ================================================================
echo.

cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
IF NOT EXIST "%VENV_PY%" (
    echo [ERROR] No se encontro el entorno virtual en '.venv\Scripts\python.exe'
    echo Corre INSTALL_DEPS.bat primero para crearlo e instalar dependencias.
    pause
    exit /b 1
)

REM (Opcional) Para subtitulos con timing por palabra, abri start_whisper_tunnel.bat
REM en otra ventana antes de generar. Si el tunel no esta, la app sigue funcionando
REM con timings por segmento.

echo Iniciando aplicacion con el venv local...
"%VENV_PY%" video_optimizer_pyqt6.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Ocurrio un error critico. Deteniendo la app para inspeccion.
    pause
)
