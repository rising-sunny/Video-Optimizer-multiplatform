@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

:: ================================================================
:: Video Optimizer Pro - Inicio con Progreso Visible
:: ================================================================

title Video Optimizer Pro - Inicio con Progreso
color 0A

:: Configuracion
set "APP_NAME=Video Optimizer Pro"
set "SCRIPT_DIR=%~dp0"
set "MAIN_SCRIPT=video_optimizer_pyqt6.py"
set "START_SCRIPT=start.py"

:: ID unico para esta PC
set "PC_ID=%COMPUTERNAME%_%USERNAME%"
set "PC_ID=%PC_ID: =_%"

echo.
echo ================================================================================
echo   %APP_NAME% - Inicio
echo   PC ID: %PC_ID%
echo ================================================================================
echo.

:: Buscar Python 3.11 primero (estable), luego 3.12, luego cualquiera
set "PYTHON_EXE="
set "PYTHON_ARGS="
set "HAS_PY_RUNTIME="

where py >nul 2>&1
if not errorlevel 1 (
    py -0p 2>nul | findstr /R /C:" -V:[0-9]" >nul 2>&1
    if not errorlevel 1 (
        set "HAS_PY_RUNTIME=1"
    )
)

:: Opcion 1: Python 3.11 via py launcher
if defined HAS_PY_RUNTIME (
    py -0p 2>nul | findstr /C:" -V:3.11" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3.11"
        echo [INFO] Usando Python 3.11 via py launcher
    )
)

:: Opcion 2: Python 3.11 en ruta comun
if not defined PYTHON_EXE (
    if exist "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe" (
        set "PYTHON_EXE=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe"
        set "PYTHON_ARGS="
        echo [INFO] Usando Python 3.11 directo
    )
)

:: Opcion 3: Python 3.12 via py launcher
if not defined PYTHON_EXE if defined HAS_PY_RUNTIME (
    py -0p 2>nul | findstr /C:" -V:3.12" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3.12"
        echo [INFO] Usando Python 3.12 via py launcher
    )
)

:: Opcion 4: Python 3.12 en ruta comun
if not defined PYTHON_EXE (
    if exist "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe" (
        set "PYTHON_EXE=C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe"
        set "PYTHON_ARGS="
        echo [INFO] Usando Python 3.12 directo
    )
)

:: Opcion 5: py generico (cualquier version instalada)
if not defined PYTHON_EXE if defined HAS_PY_RUNTIME (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS="
    echo [INFO] Usando Python default via py launcher
)

:: Opcion 6: python generico (sin py launcher)
if not defined PYTHON_EXE (
    python --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=python"
        set "PYTHON_ARGS="
        echo [INFO] Usando Python via comando python
    )
)

:: Opcion 7: WinPython fallback
if not defined PYTHON_EXE (
    echo [ADVERTENCIA] Python no encontrado en el sistema. Intentando WinPython...
    set "WINPYTHON_BASE=C:\Scripts\WPy64-312101"
    if exist "!WINPYTHON_BASE!\python\python.exe" (
        echo [INFO] WinPython encontrado en: !WINPYTHON_BASE!\python\python.exe
        set "PYTHON_EXE=!WINPYTHON_BASE!\python\python.exe"
        set "PYTHON_ARGS="
    ) else (
        echo [ERROR] No se encontro Python en el sistema
        goto :no_python
    )
)

set "PYTHON_VERSION=Desconocida"
for /f "tokens=2" %%a in ('"!PYTHON_EXE!" !PYTHON_ARGS! --version 2^>^&1') do set "PYTHON_VERSION=%%a"
echo [INFO] Python detectado: !PYTHON_VERSION!

:: Preferir el venv local si ya existe y funciona
set "VENV_PATH="
set "LOCAL_VENV_DIR=%USERPROFILE%\VideoOptimizer_VEnvs"
set "LOCAL_VENV_PATH=!LOCAL_VENV_DIR!\!PC_ID!"
set "REGISTRY_FILE=%SCRIPT_DIR%.venv_registry.json"

if exist "!LOCAL_VENV_PATH!\Scripts\python.exe" (
    "!LOCAL_VENV_PATH!\Scripts\python.exe" --version >nul 2>&1
    if not errorlevel 1 (
        set "VENV_PATH=!LOCAL_VENV_PATH!"
        echo [INFO] Usando venv local existente: !VENV_PATH!
    )
)

:: Si no hay venv local utilizable, buscar en registro
if not defined VENV_PATH if exist "%REGISTRY_FILE%" (
    for /f "tokens=*" %%a in ('powershell -NoProfile -Command "try { $json = Get-Content '%REGISTRY_FILE%' | ConvertFrom-Json; $key = 'PC_' + '%PC_ID%' -replace '-', '-'; $entry = $json.PSObject.Properties | Where-Object { $_.Name -eq $key -or ($_.Value.hostname -eq '%COMPUTERNAME%' -and $_.Value.venv_path -like '*%USERNAME%*') } | Select-Object -First 1; if ($entry) { $entry.Value.venv_path } } catch { }"') do (
        set "VENV_PATH=%%a"
    )
)

:: Si no se encontro ningun venv utilizable, usar la ruta local por defecto
if not defined VENV_PATH (
    set "VENV_PATH=!LOCAL_VENV_PATH!"
    echo [INFO] Usando ruta local del venv: !VENV_PATH!
) else (
    if /I not "!VENV_PATH!"=="!LOCAL_VENV_PATH!" (
        echo [INFO] Venv encontrado en registro: !VENV_PATH!
    )
)

:: Usar entorno virtual existente o crear uno
set "VENV_OK=0"
if exist "!VENV_PATH!\Scripts\python.exe" (
    :: Validar que el python del venv funciona
    "!VENV_PATH!\Scripts\python.exe" --version >nul 2>&1
    if not errorlevel 1 (
        echo [INFO] Usando entorno virtual existente
        set "PYTHON_EXE=!VENV_PATH!\Scripts\python.exe"
        set "PYTHON_ARGS="
        set "VENV_OK=1"
    ) else (
        echo [WARN] Venv encontrado pero no funciona. Eliminando...
        rmdir /s /q "!VENV_PATH!" 2>nul
    )
)
if "!VENV_OK!"=="0" (
    echo [INFO] Creando entorno virtual: !VENV_PATH!
    mkdir "!VENV_PATH!" 2>nul
    "!PYTHON_EXE!" !PYTHON_ARGS! -m venv "!VENV_PATH!"
    if errorlevel 1 (
        echo [ERROR] Fallo al crear venv
        pause
        exit /b 1
    )
    set "PYTHON_EXE=!VENV_PATH!\Scripts\python.exe"
    set "PYTHON_ARGS="

    echo [INFO] Actualizando pip...
    "!PYTHON_EXE!" !PYTHON_ARGS! -m ensurepip --upgrade >nul 2>&1
    "!PYTHON_EXE!" !PYTHON_ARGS! -m pip install --upgrade pip
)

:: Verificar que estamos usando el python del venv
echo [INFO] Python del venv: !PYTHON_EXE!
for /f "tokens=*" %%a in ('"!PYTHON_EXE!" !PYTHON_ARGS! --version 2^>^&1') do echo [INFO] Version: %%a

:: Verificar si las dependencias criticas estan instaladas
echo.
echo [INFO] Verificando dependencias...

"!PYTHON_EXE!" !PYTHON_ARGS! -c "import dotenv; import PyQt6; import groq; import edge_tts" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Faltan dependencias criticas. Instalando desde requirements.txt...
    echo.
    echo [INFO] Reparando/actualizando pip...
    "!PYTHON_EXE!" !PYTHON_ARGS! -m ensurepip --upgrade >nul 2>&1
    "!PYTHON_EXE!" !PYTHON_ARGS! -m pip install --upgrade pip
    echo [INFO] Instalando dependencias...
    "!PYTHON_EXE!" !PYTHON_ARGS! -m pip install -r "%SCRIPT_DIR%requirements.txt"

    if errorlevel 1 (
        echo [ERROR] Fallo al instalar dependencias
        pause
        exit /b 1
    )
    echo [INFO] Dependencias instaladas correctamente.
) else (
    echo [INFO] Dependencias OK. Inicio rapido.
)
echo.
echo [INFO] Iniciando aplicacion...
cd /d "%SCRIPT_DIR%"

echo [INFO] Ejecutando: "!PYTHON_EXE!" !PYTHON_ARGS! "%MAIN_SCRIPT%"
if exist "%START_SCRIPT%" (
    echo [INFO] Usando script de inicio: %START_SCRIPT%
    "!PYTHON_EXE!" !PYTHON_ARGS! "%START_SCRIPT%" --auto --skip-deps
) else (
    echo [INFO] Usando script principal: %MAIN_SCRIPT%
    "!PYTHON_EXE!" !PYTHON_ARGS! "%MAIN_SCRIPT%"
)

if errorlevel 2 (
    echo [ERROR] La aplicacion se cerro con errores graves.
    echo Revise el mensaje anterior.
) else if errorlevel 1 (
    echo [ERROR] La aplicacion termino con codigo 1.
    echo Revise crash_log.txt para ver el traceback mas reciente.
) else (
    echo [INFO] Aplicacion finalizada correctamente.
)

echo.
echo [INFO] Aplicacion cerrada.
pause
endlocal
goto :eof

:no_python
echo [INFO] Por favor instale Python desde python.org o asegure que WinPython este en la ruta especificada
pause
exit /b 1
