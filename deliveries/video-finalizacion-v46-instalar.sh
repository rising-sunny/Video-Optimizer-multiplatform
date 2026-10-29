#!/bin/bash
set -euo pipefail
umask 077
repo=/home/videoagent/Video-Optimizer-multiplatform
commit=76ce7ad016a2ea13aabb09feef408a0f5a40e185
paquete=$(mktemp /tmp/video-finalizacion-v46.XXXXXX.tgz)
trap 'rm -f "$paquete"' EXIT
runuser -u videoagent -- git -C "$repo" show "$commit:deliveries/video-finalizacion-v46.tgz.b64" | base64 -d > "$paquete"
printf '%s  %s\n' '4e109edf21bf297c434f5b442a535afdefdb5cb1d5717801578d4a07f6655ed4' "$paquete" | sha256sum -c -
if [ -L /tmp/video-finalizacion-v46 ]; then
    echo 'Directorio de instalación no válido.'
    exit 1
fi
tar -xzpf "$paquete" -C /tmp
runuser -u videoagent -- test -r /tmp/video-finalizacion-v46/shorts_finish.py
resultado=0
systemd-run --unit=video-finalizacion-v46-install --wait --collect --property=Type=exec --property=StandardOutput=journal --property=StandardError=journal /bin/bash /tmp/video-finalizacion-v46/install.sh --resume-pair || resultado=$?
journalctl -u video-finalizacion-v46-install.service -n 100 -o cat --no-pager
exit "$resultado"
