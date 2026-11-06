#!/bin/bash
set -euo pipefail
umask 077
repo=/home/videoagent/Video-Optimizer-multiplatform
commit=5490c78e73a6bd7ebcd074c80b1653952ad84d42
paquete=$(mktemp /tmp/video-chrome-dome-fuentes.XXXXXX.tgz)
trap 'rm -f "$paquete"' EXIT
runuser -u videoagent -- git -C "$repo" show "$commit:deliveries/video-chrome-dome-fuentes-20261106.tgz.b64" | base64 -d > "$paquete"
printf '%s  %s\n' 'f5c47d779a7c2ec9cc8d7b6c3476791f39a7997cb43338adc9c5df378c35175b' "$paquete" | sha256sum -c -
directorio=$(mktemp -d /tmp/video-chrome-dome-fuentes.XXXXXX)
chmod 0755 "$directorio"
tar -xzpf "$paquete" -C "$directorio"
runuser -u videoagent -- test -r "$directorio/video-chrome-dome-fuentes-20261106/resume_chrome_dome.py"
resultado=0
systemd-run --unit=video-chrome-dome-fuentes-20261106-install \
    --wait --collect --property=Type=exec \
    --property=StandardOutput=journal --property=StandardError=journal \
    /usr/bin/python3 -B "$directorio/video-chrome-dome-fuentes-20261106/install.py" || resultado=$?
journalctl -u video-chrome-dome-fuentes-20261106-install.service -n 100 -o cat --no-pager
exit "$resultado"
