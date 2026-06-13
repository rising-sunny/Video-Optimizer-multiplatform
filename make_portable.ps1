# make_portable.ps1
$ErrorActionPreference = "Stop"

$PYTHON_VERSION = "3.11.9"
$PYTHON_ZIP_URL = "https://www.python.org/ftp/python/$PYTHON_VERSION/python-$PYTHON_VERSION-embed-amd64.zip"
$PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
$PORTABLE_DIR = "python_portable"

Write-Host "=== CREADOR DE ENTORNO PORTATIL VIDEO OPTIMIZER ===" -ForegroundColor Cyan
Write-Host "Iniciando instalacion de entorno portatil Python $PYTHON_VERSION"

# 1. Crear carpeta
if (!(Test-Path $PORTABLE_DIR)) {
    New-Item -ItemType Directory -Path $PORTABLE_DIR | Out-Null
    Write-Host "Carpeta $PORTABLE_DIR creada." -ForegroundColor Green
} else {
    Write-Host "La carpeta $PORTABLE_DIR ya existe. Se usara como base." -ForegroundColor Yellow
}

# 2. Descargar Python Embebido
$ZIP_PATH = "$PORTABLE_DIR\python_embed.zip"
if (!(Test-Path "$PORTABLE_DIR\python.exe")) {
    Write-Host "Descargando Python Embebido..."
    Invoke-WebRequest -Uri $PYTHON_ZIP_URL -OutFile $ZIP_PATH
    
    Write-Host "Extrayendo Python..."
    Expand-Archive -Path $ZIP_PATH -DestinationPath $PORTABLE_DIR -Force
    Remove-Item $ZIP_PATH
    Write-Host "Python extraido corectamente." -ForegroundColor Green
} else {
    Write-Host "Python ya esta presente en el entorno portable." -ForegroundColor Green
}

# 3. Activando site-packages (Crucial para pip y entorno portable)
$PTH_FILE = "$PORTABLE_DIR\python311._pth"
if (Test-Path $PTH_FILE) {
    $pthContent = Get-Content $PTH_FILE
    if ($pthContent -match "#import site") {
        $pthContent -replace "#import site", "import site" | Set-Content $PTH_FILE
        Add-Content $PTH_FILE "`n.."
        Write-Host "Se activo 'site' en python311._pth para soportar paquetes nativos." -ForegroundColor Magenta
    }
}

# 4. Instalando pip
if (!(Test-Path "$PORTABLE_DIR\Scripts\pip.exe") -and !(Test-Path "$PORTABLE_DIR\Scripts\pip3.exe")) {
    Write-Host "Descargando instalador de pip..."
    Invoke-WebRequest -Uri $PIP_URL -OutFile "$PORTABLE_DIR\get-pip.py"
    
    Write-Host "Instalando pip en el entorno portable..."
    & "$PORTABLE_DIR\python.exe" "$PORTABLE_DIR\get-pip.py" --no-warn-script-location
    Remove-Item "$PORTABLE_DIR\get-pip.py"
    Write-Host "Pip instalado con exito." -ForegroundColor Green
} else {
    Write-Host "Pip ya esta instalado." -ForegroundColor Green
}

# 5. Instalando requirements.txt
if (Test-Path "requirements.txt") {
    Write-Host "Iniciando instalacion masiva de dependencias (Esto tomara varios minutos debido a PyTorch y Whisper)..." -ForegroundColor Cyan
    & "$PORTABLE_DIR\python.exe" -m pip install -r requirements.txt --no-warn-script-location
    Write-Host "Todas las dependencias instaladas correctamente." -ForegroundColor Green
} else {
    Write-Host "ATENCION: requirements.txt no encontrado en la raiz del proyecto." -ForegroundColor Red
}

Write-Host "=== ENTORNO PORTABLE CREADO EXITOSAMENTE ===" -ForegroundColor Cyan
Write-Host "Usa RUN.bat para iniciar la aplicacion de ahora en adelante." -ForegroundColor Yellow
Write-Host "Presiona cualquier tecla para salir..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
