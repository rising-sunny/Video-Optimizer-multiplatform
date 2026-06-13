@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

echo === DEBUG START === > "%~dp0debug_log.txt" 2>&1
echo Fecha: %date% %time% >> "%~dp0debug_log.txt" 2>&1

echo [1] Buscando Python... >> "%~dp0debug_log.txt" 2>&1

set "PYTHON_EXE="
set "PYTHON_ARGS="
set "HAS_PY_RUNTIME="

py -0p 2>nul | findstr /R /C:" -V:[0-9]" >nul 2>&1
if not errorlevel 1 (
    set "HAS_PY_RUNTIME=1"
    echo [1a] py launcher encontrado >> "%~dp0debug_log.txt" 2>&1
) else (
    echo [1a] py launcher NO encontrado >> "%~dp0debug_log.txt" 2>&1
)

echo [2] Probando python directo... >> "%~dp0debug_log.txt" 2>&1
python --version >> "%~dp0debug_log.txt" 2>&1
echo [2a] errorlevel python: !errorlevel! >> "%~dp0debug_log.txt" 2>&1

if not defined PYTHON_EXE (
    python --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=python"
        set "PYTHON_ARGS="
        echo [2b] PYTHON_EXE=python >> "%~dp0debug_log.txt" 2>&1
    ) else (
        echo [2b] python fallo con errorlevel !errorlevel! >> "%~dp0debug_log.txt" 2>&1
    )
)

echo [3] PYTHON_EXE=!PYTHON_EXE! >> "%~dp0debug_log.txt" 2>&1

if not defined PYTHON_EXE (
    echo [3a] NO SE ENCONTRO PYTHON >> "%~dp0debug_log.txt" 2>&1
    echo No se encontro Python. Ver debug_log.txt
    pause
    exit /b 1
)

echo [4] Buscando venv... >> "%~dp0debug_log.txt" 2>&1
set "PC_ID=%COMPUTERNAME%_%USERNAME%"
set "PC_ID=%PC_ID: =_%"
set "LOCAL_VENV_DIR=%USERPROFILE%\VideoOptimizer_VEnvs"
set "LOCAL_VENV_PATH=!LOCAL_VENV_DIR!\!PC_ID!"
echo [4a] VENV_PATH=!LOCAL_VENV_PATH! >> "%~dp0debug_log.txt" 2>&1

if exist "!LOCAL_VENV_PATH!\Scripts\python.exe" (
    echo [4b] Venv existe >> "%~dp0debug_log.txt" 2>&1
    "!LOCAL_VENV_PATH!\Scripts\python.exe" --version >> "%~dp0debug_log.txt" 2>&1
    echo [4c] venv python errorlevel: !errorlevel! >> "%~dp0debug_log.txt" 2>&1
) else (
    echo [4b] Venv NO existe en !LOCAL_VENV_PATH! >> "%~dp0debug_log.txt" 2>&1
)

echo [5] Probando start.py... >> "%~dp0debug_log.txt" 2>&1
cd /d "%~dp0"
echo [5a] CWD=%CD% >> "%~dp0debug_log.txt" 2>&1

if exist "start.py" (
    echo [5b] start.py existe >> "%~dp0debug_log.txt" 2>&1
) else (
    echo [5b] start.py NO existe >> "%~dp0debug_log.txt" 2>&1
)

echo [6] Ejecutando app... >> "%~dp0debug_log.txt" 2>&1
echo === Ejecutando app. Revise debug_log.txt si se cierra ===

if exist "!LOCAL_VENV_PATH!\Scripts\python.exe" (
    echo [6a] Usando venv python >> "%~dp0debug_log.txt" 2>&1
    "!LOCAL_VENV_PATH!\Scripts\python.exe" "start.py" --auto --skip-deps >> "%~dp0debug_log.txt" 2>&1
    echo [6b] exit code: !errorlevel! >> "%~dp0debug_log.txt" 2>&1
) else (
    echo [6a] Usando python global >> "%~dp0debug_log.txt" 2>&1
    python "start.py" --auto --skip-deps >> "%~dp0debug_log.txt" 2>&1
    echo [6b] exit code: !errorlevel! >> "%~dp0debug_log.txt" 2>&1
)

echo [7] FIN >> "%~dp0debug_log.txt" 2>&1
echo.
echo === Terminado. Revise debug_log.txt ===
pause
