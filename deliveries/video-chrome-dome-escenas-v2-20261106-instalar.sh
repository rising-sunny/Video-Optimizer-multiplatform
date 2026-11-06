#!/bin/bash
set -euo pipefail
umask 077
repo=/home/videoagent/Video-Optimizer-multiplatform
commit=ff9c0f473e439dcb053e846979487e03cecf6702
paquete=$(mktemp /tmp/video-chrome-dome-escenas-v2.XXXXXX.tgz)
trap 'rm -f "$paquete"' EXIT
runuser -u videoagent -- git -C "$repo" show "$commit:deliveries/video-chrome-dome-escenas-v2-20261106.tgz.b64" | base64 -d > "$paquete"
printf '%s  %s\n' '3e788fcd359ec3ad0f1d00aa76b0734e21c834f51427f3de38fe5526424f8935' "$paquete" | sha256sum -c -
directorio=$(mktemp -d /tmp/video-chrome-dome-escenas-v2.XXXXXX)
chmod 0755 "$directorio"
tar -xzpf "$paquete" -C "$directorio"
runuser -u videoagent -- test -r "$directorio/video-chrome-dome-escenas-v2-20261106/resume_chrome_dome_segments.py"
resultado=0
systemd-run --unit=video-chrome-dome-escenas-v2-20261106-install \
    --wait --collect --property=Type=exec \
    --property=StandardOutput=journal --property=StandardError=journal \
    /usr/bin/python3 -B "$directorio/video-chrome-dome-escenas-v2-20261106/install.py" || resultado=$?
journalctl -u video-chrome-dome-escenas-v2-20261106-install.service -n 100 -o cat --no-pager
exit "$resultado"
