#!/bin/bash
set -euo pipefail
umask 077
repo=/home/videoagent/Video-Optimizer-multiplatform
commit=06ccbc0ab4376d7855dce0da1792c247ab6da328
paquete=$(mktemp /tmp/video-chrome-dome-clips-v5.XXXXXX.tgz)
trap 'rm -f "$paquete"' EXIT
runuser -u videoagent -- git -C "$repo" show "$commit:deliveries/video-chrome-dome-clips-v5-20261106.tgz.b64" | base64 -d > "$paquete"
printf '%s  %s\n' '27260feba6f3e2d78bdb3a801f4c5b58ca370326a6a9607da95a96bf0d4a01ff' "$paquete" | sha256sum -c -
directorio=$(mktemp -d /tmp/video-chrome-dome-clips-v5.XXXXXX)
chmod 0755 "$directorio"
tar -xzpf "$paquete" -C "$directorio"
runuser -u videoagent -- test -r "$directorio/video-chrome-dome-clips-v5-20261106/resume_chrome_dome_clips.py"
resultado=0
systemd-run --unit=video-chrome-dome-clips-v5-20261106-install \
    --wait --collect --property=Type=exec \
    --property=StandardOutput=journal --property=StandardError=journal \
    /usr/bin/python3 -B "$directorio/video-chrome-dome-clips-v5-20261106/install.py" || resultado=$?
journalctl -u video-chrome-dome-clips-v5-20261106-install.service -n 100 -o cat --no-pager
exit "$resultado"
