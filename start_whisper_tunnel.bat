@echo off
title Whisper Tunnel (VPS) - dejar abierto
chcp 65001 > nul
echo ================================================================
echo  Tunel SSH para transcripcion Whisper en el VPS
echo  local 127.0.0.1:8771  -^>  VPS 127.0.0.1:8771 (whisper-svc)
echo ================================================================
echo.
echo  Deja esta ventana ABIERTA mientras generas videos.
echo  Cerrarla corta el tunel (la app cae al whisper local).
echo  Ctrl+C para salir.
echo.

:loop
echo [%date% %time%] Conectando tunel...
ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -N -L 8771:127.0.0.1:8771 root@5.78.125.169
echo.
echo [%date% %time%] Tunel cerrado/caido. Reintento en 5s... (Ctrl+C para abortar)
timeout /t 5 > nul
goto loop
