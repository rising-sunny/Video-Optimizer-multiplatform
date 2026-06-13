<#
.SYNOPSIS
    Guarda cambios en git y los sube a GitHub en un paso.

.EXAMPLE
    .\save.ps1 "arreglo bug del timeline"
    .\save.ps1                    # usa timestamp como mensaje
#>
param(
    [string]$Message
)

# git escribe progreso/warnings a stderr; PS los trata como errores con Stop.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$changes = git status --short 2>&1
if (-not $changes) {
    Write-Host "Sin cambios para guardar." -ForegroundColor Yellow
    exit 0
}

Write-Host "Cambios detectados:" -ForegroundColor Cyan
$changes | ForEach-Object { Write-Host "  $_" }

if (-not $Message) {
    $Message = "WIP {0}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm')
}

Write-Host "`nCommiteando: $Message" -ForegroundColor Cyan
git add -A 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "git add fallo." -ForegroundColor Red; exit 1 }

git commit -m $Message 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "git commit fallo." -ForegroundColor Red; exit 1 }

Write-Host "Pusheando a GitHub..." -ForegroundColor Cyan
git push 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "git push fallo." -ForegroundColor Red; exit 1 }

Write-Host "Listo." -ForegroundColor Green
