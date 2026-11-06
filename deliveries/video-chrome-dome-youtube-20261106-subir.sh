#!/bin/bash
set -euo pipefail
umask 077

repo=/home/videoagent/Video-Optimizer-multiplatform
pythonVideo="$repo/.venv/bin/python"
commit=c17f6aaaa02fd02114afd5c5379700bcd5f5f1de
unidad=video-chrome-dome-youtube-20261106
paquete=$(mktemp /tmp/video-chrome-dome-youtube.XXXXXX.tgz)
trap 'rm -f "$paquete"' EXIT

if systemctl is-active --quiet "$unidad.service"; then
    echo 'La subida de Chrome Dome ya está en curso; no se inicia otra.'
    journalctl -u "$unidad.service" -n 40 -o cat --no-pager
    exit 0
fi

runuser -u videoagent -- git -C "$repo" show \
    "$commit:deliveries/video-chrome-dome-youtube-20261106.tgz.b64" |
    base64 -d > "$paquete"
printf '%s  %s\n' \
    'e96ecdfa1066136730c7563d0b3971875d75326a20d39aedbee66900b28f7e75' \
    "$paquete" | sha256sum -c -

directorio=$(mktemp -d /tmp/video-chrome-dome-youtube.XXXXXX)
chmod 0755 "$directorio"
tar -xzpf "$paquete" -C "$directorio"
bundle="$directorio/video-chrome-dome-youtube-20261106"
runuser -u videoagent -- test -r "$bundle/publish_chrome_dome.py"
runuser -u videoagent -- "$pythonVideo" -B -m unittest discover \
    -s "$bundle" -p test_publish_chrome_dome.py -q

echo 'Subiendo Chrome Dome a Stunning Revelations con miniatura y SRT inglés.'
echo 'Se hará público al completar y verificar la carga. El proceso sigue en la VPS si se corta SSH.'
echo "Puede consultar el avance con: journalctl -u $unidad.service -n 40 -o cat --no-pager"
resultado=0
systemd-run --unit="$unidad" --wait --collect --property=Type=exec \
    --property=User=videoagent --property=Group=videoagent \
    --property=WorkingDirectory="$repo" --property=UMask=0077 \
    --property=RuntimeMaxSec=2h \
    --property=StandardOutput=journal --property=StandardError=journal \
    "$pythonVideo" -B -u "$bundle/publish_chrome_dome.py" --publish || resultado=$?
journalctl -u "$unidad.service" -n 100 -o cat --no-pager
exit "$resultado"
