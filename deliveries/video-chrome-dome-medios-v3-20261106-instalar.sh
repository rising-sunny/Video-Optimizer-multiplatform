#!/bin/bash
set -euo pipefail
umask 077
repo=/home/videoagent/Video-Optimizer-multiplatform
commit=e3148b7f428c1847fea795fa1be5f5fb1abcca1c
paquete=$(mktemp /tmp/video-chrome-dome-medios-v3.XXXXXX.tgz)
trap 'rm -f "$paquete"' EXIT
runuser -u videoagent -- git -C "$repo" show "$commit:deliveries/video-chrome-dome-medios-v3-20261106.tgz.b64" | base64 -d > "$paquete"
printf '%s  %s\n' '15d571853b545a8f0015089468516d5ec8d19f1dde1737477a2302fb17158aa2' "$paquete" | sha256sum -c -
directorio=$(mktemp -d /tmp/video-chrome-dome-medios-v3.XXXXXX)
chmod 0755 "$directorio"
tar -xzpf "$paquete" -C "$directorio"
runuser -u videoagent -- test -r "$directorio/video-chrome-dome-medios-v3-20261106/resume_chrome_dome_segments.py"
resultado=0
systemd-run --unit=video-chrome-dome-medios-v3-20261106-install \
    --wait --collect --property=Type=exec \
    --property=StandardOutput=journal --property=StandardError=journal \
    /usr/bin/python3 -B "$directorio/video-chrome-dome-medios-v3-20261106/install.py" || resultado=$?
journalctl -u video-chrome-dome-medios-v3-20261106-install.service -n 100 -o cat --no-pager
exit "$resultado"
