#!/bin/bash
set -euo pipefail
umask 077

repo=/home/videoagent/Video-Optimizer-multiplatform
pythonVideo="$repo/.venv/bin/python"
commit=8ba335176386802c2deb82beef1efed2bdff5dc2
unidad=video-chrome-dome-youtube-20261106
paquete=$(mktemp /tmp/video-chrome-dome-youtube-subtitulos-v2.XXXXXX.tgz)
trap 'rm -f "$paquete"' EXIT

if systemctl is-active --quiet "$unidad.service"; then
    echo 'La continuación de Chrome Dome ya está en curso.'
    journalctl -u "$unidad.service" -n 40 -o cat --no-pager
    exit 0
fi

runuser -u videoagent -- git -C "$repo" show \
    "$commit:deliveries/video-chrome-dome-youtube-subtitulos-v2-20261106.tgz.b64" |
    base64 -d > "$paquete"
printf '%s  %s\n' \
    'd047e03b92eee316d2942e940797e3051a680d81d29187ecccc4bf5e12d9d812' \
    "$paquete" | sha256sum -c -

directorio=$(mktemp -d /tmp/video-chrome-dome-youtube-subtitulos-v2.XXXXXX)
chmod 0755 "$directorio"
tar -xzpf "$paquete" -C "$directorio"
bundle="$directorio/video-chrome-dome-youtube-subtitulos-v2-20261106"
runuser -u videoagent -- test -r "$bundle/publish_chrome_dome.py"
runuser -u videoagent -- "$pythonVideo" -B -m unittest discover \
    -s "$bundle" -p test_publish_chrome_dome.py -q

echo 'Retomando únicamente el vídeo ya cargado: B8QPUmNCfCY.'
echo 'Completa y verifica los subtítulos antes de hacerlo público. No vuelve a subir el MP4.'
echo "Avance: journalctl -u $unidad.service -n 40 -o cat --no-pager"
inicio=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
resultado=0
systemd-run --unit="$unidad" --wait --collect --property=Type=exec \
    --property=User=videoagent --property=Group=videoagent \
    --property=WorkingDirectory="$repo" --property=UMask=0077 \
    --property=RuntimeMaxSec=2h \
    --property=StandardOutput=journal --property=StandardError=journal \
    "$pythonVideo" -B -u "$bundle/publish_chrome_dome.py" --resume-existing || resultado=$?
journalctl -u "$unidad.service" --since "$inicio" -n 100 -o cat --no-pager
exit "$resultado"
