#!/bin/bash
set -euo pipefail
umask 077
repo=/home/videoagent/Video-Optimizer-multiplatform
commit=4505fafe7dce6c04e82745034325ae2edee502e7
paquete=$(mktemp /tmp/video-finalizacion-v46-v2.XXXXXX.tgz)
trap 'rm -f "$paquete"' EXIT
runuser -u videoagent -- git -C "$repo" show "$commit:deliveries/video-finalizacion-v46-v2.tgz.b64" | base64 -d > "$paquete"
printf '%s  %s\n' '126a2bf29c989e12457155c896400815e299979cfb18b30d0cf40334578f48c2' "$paquete" | sha256sum -c -
if [ -L /tmp/video-finalizacion-v46-v2 ]; then
    echo 'Directorio de instalacion no valido.'
    exit 1
fi
tar -xzpf "$paquete" -C /tmp
runuser -u videoagent -- test -r /tmp/video-finalizacion-v46-v2/shorts_finish.py
resultado=0
systemd-run --unit=video-finalizacion-v46-v2-install --wait --collect --property=Type=exec --property=StandardOutput=journal --property=StandardError=journal /bin/bash /tmp/video-finalizacion-v46-v2/install.sh --resume-pair || resultado=$?
journalctl -u video-finalizacion-v46-v2-install.service -n 100 -o cat --no-pager
exit "$resultado"
