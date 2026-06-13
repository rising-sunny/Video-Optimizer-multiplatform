@echo off
title Instalador de Dependencias
cd /d "%~dp0"
echo Instalando dependencias en el entorno portatil...
.\python_portable\python.exe -m pip install -r requirements.txt
pause
