#!/bin/bash
set -euo pipefail
umask 077
repo=/home/videoagent/Video-Optimizer-multiplatform
commit=87fe77af984e5b503fb2ef0f768b156d4c7c15e3
paquete=$(mktemp /tmp/video-chrome-dome-segmentos.XXXXXX.tgz)
trap 'rm -f "$paquete"' EXIT
runuser -u videoagent -- git -C "$repo" show "$commit:deliveries/video-chrome-dome-segmentos-20261106.tgz.b64" | base64 -d > "$paquete"
printf '%s  %s\n' '7ea92858b7f2a97c8730fd85a2195ea3c6bb795c615125156a87b299b59ad1a3' "$paquete" | sha256sum -c -
directorio=$(mktemp -d /tmp/video-chrome-dome-segmentos.XXXXXX)
chmod 0755 "$directorio"
tar -xzpf "$paquete" -C "$directorio"
runuser -u videoagent -- test -r "$directorio/video-chrome-dome-segmentos-20261106/resume_chrome_dome_segments.py"
resultado=0
systemd-run --unit=video-chrome-dome-segmentos-20261106-install \
    --wait --collect --property=Type=exec \
    --property=StandardOutput=journal --property=StandardError=journal \
    /usr/bin/python3 -B "$directorio/video-chrome-dome-segmentos-20261106/install.py" || resultado=$?
journalctl -u video-chrome-dome-segmentos-20261106-install.service -n 100 -o cat --no-pager
exit "$resultado"
