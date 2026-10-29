#!/bin/bash
set -euo pipefail
umask 077
repo=/home/videoagent/Video-Optimizer-multiplatform
commit=148b1a456736d8812f87f06ef7784f6bed64531f
paquete=$(mktemp /tmp/video-finalizar-shorts-v45.XXXXXX.tgz)
trap 'rm -f "$paquete"' EXIT

runuser -u videoagent -- git -C "$repo" show "$commit:deliveries/video-finalizar-shorts-v45.tgz.b64" | base64 -d > "$paquete"
printf '%s  %s\n' '4a936b823cc0fccd3644114b8ced6ea5c84595f433dbaac2d1457c0345644aa5' "$paquete" | sha256sum -c -
if [ -L /tmp/video-finalizar-shorts-v45 ]; then
    echo 'Directorio de instalación no válido.'
    exit 1
fi
tar -xzpf "$paquete" -C /tmp
runuser -u videoagent -- test -r /tmp/video-finalizar-shorts-v45/shorts_finish.py
resultado=0
systemd-run --unit=video-finalizar-shorts-v45-install --wait --collect --property=Type=exec --property=StandardOutput=journal --property=StandardError=journal /bin/bash /tmp/video-finalizar-shorts-v45/install.sh --resume-pair || resultado=$?
journalctl -u video-finalizar-shorts-v45-install.service -n 100 -o cat --no-pager
exit "$resultado"
