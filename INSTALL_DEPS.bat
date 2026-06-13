@echo off
title Instalador de Dependencias (venv local)
cd /d "%~dp0"

IF NOT EXIST ".venv\Scripts\python.exe" (
    echo Creando entorno virtual con Python 3.11...
    py -3.11 -m venv .venv
    IF %ERRORLEVEL% NEQ 0 (
        echo [ERROR] No se pudo crear el venv. Tenes Python 3.11 instalado?
        echo Instalalo desde https://www.python.org/downloads/release/python-3110/
        pause
        exit /b 1
    )
)

echo Actualizando pip/wheel...
.venv\Scripts\python.exe -m pip install -U pip wheel

echo Instalando dependencias livianas (sin torch/whisper; Whisper corre en el VPS)...
.venv\Scripts\python.exe -m pip install -r requirements_local.txt

echo.
echo Listo. Para generar subtitulos con timing por palabra, abri start_whisper_tunnel.bat
echo en otra ventana antes de usar RUN.bat.
pause
