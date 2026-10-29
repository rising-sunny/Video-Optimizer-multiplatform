#!/bin/bash
set -euo pipefail
umask 077

repo=/home/videoagent/Video-Optimizer-multiplatform
commit=29474a71ed5c56cbb225b07def20becb4153092c
paquete=$(mktemp /tmp/video-permisos-pruebas-v44-v4.XXXXXX.tgz)
trap 'rm -f "$paquete"' EXIT

runuser -u videoagent -- git -C "$repo" show "$commit:deliveries/video-permisos-pruebas-v44-v4.tgz.b64" | base64 -d > "$paquete"
printf '%s  %s\n' '96f563d4b172727678a35cf2a48bcf9d319050d1084727b43389996b59e1e525' "$paquete" | sha256sum -c -

if [ -L /tmp/video-permisos-pruebas-v44-v4 ]; then
    echo 'Directorio de instalación no válido.'
    exit 1
fi
tar -xzpf "$paquete" -C /tmp
runuser -u videoagent -- test -r /tmp/video-permisos-pruebas-v44-v4/shorts_handoff_resume.py

resultado=0
systemd-run --unit=video-permisos-pruebas-v44-v4-install --wait --collect --property=Type=exec --property=StandardOutput=journal --property=StandardError=journal /bin/bash /tmp/video-permisos-pruebas-v44-v4/install.sh --resume-pair || resultado=$?
journalctl -u video-permisos-pruebas-v44-v4-install.service -n 100 -o cat --no-pager
exit "$resultado"
