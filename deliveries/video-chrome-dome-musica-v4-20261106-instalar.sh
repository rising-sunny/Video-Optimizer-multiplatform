#!/bin/bash
set -euo pipefail
umask 077
repo=/home/videoagent/Video-Optimizer-multiplatform
commit=c0b20f05b2d98e878907b49533d3c82760516de3
paquete=$(mktemp /tmp/video-chrome-dome-musica-v4.XXXXXX.tgz)
trap 'rm -f "$paquete"' EXIT
runuser -u videoagent -- git -C "$repo" show "$commit:deliveries/video-chrome-dome-musica-v4-20261106.tgz.b64" | base64 -d > "$paquete"
printf '%s  %s\n' 'b4b529d6d3a048b36dbeee37f0257c19811342d86a300d2f68120352badb4fa7' "$paquete" | sha256sum -c -
directorio=$(mktemp -d /tmp/video-chrome-dome-musica-v4.XXXXXX)
chmod 0755 "$directorio"
tar -xzpf "$paquete" -C "$directorio"
runuser -u videoagent -- test -r "$directorio/video-chrome-dome-musica-v4-20261106/resume_chrome_dome_music.py"
resultado=0
systemd-run --unit=video-chrome-dome-musica-v4-20261106-install \
    --wait --collect --property=Type=exec \
    --property=StandardOutput=journal --property=StandardError=journal \
    /usr/bin/python3 -B "$directorio/video-chrome-dome-musica-v4-20261106/install.py" || resultado=$?
journalctl -u video-chrome-dome-musica-v4-20261106-install.service -n 100 -o cat --no-pager
exit "$resultado"
