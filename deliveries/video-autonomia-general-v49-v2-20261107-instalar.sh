#!/bin/bash
set -euo pipefail
umask 077
repo=/home/videoagent/Video-Optimizer-multiplatform
commit=fcc7a395810a5659e688e8e9b0df18576c3b599e
unidad=video-autonomia-general-v49-v2-20261107-install
paquete=$(mktemp /tmp/video-autonomia-general-v49-v2.XXXXXX.tgz)
trap 'rm -f "$paquete"' EXIT
if systemctl is-active --quiet "$unidad.service"; then
    echo 'La instalación de autonomía general ya está en curso.'
    journalctl -u "$unidad.service" -n 30 -o cat --no-pager
    exit 0
fi
runuser -u videoagent -- git -C "$repo" show \
    "$commit:deliveries/video-autonomia-general-v49-20261107.tgz.b64" |
    base64 -d > "$paquete"
printf '%s  %s\n' \
    'dbc66d8354fc7b8be23e76f277c0f70b095a1a4b89205a225f212c46f163bac6' \
    "$paquete" | sha256sum -c -
directorio=$(mktemp -d /tmp/video-autonomia-general-v49-v2.XXXXXX)
chmod 0755 "$directorio"
tar -xzpf "$paquete" -C "$directorio"
bundle="$directorio/video-autonomia-general-v49-20261107"
runuser -u videoagent -- test -r "$bundle/bootstrap.py"
echo 'Instalando autonomía general para futuros Shorts y documentales horizontales, ambos canales.'
echo 'Incluye diagnóstico, reanudación del mismo trabajo y mantenimiento desde el conector.'
inicio=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
resultado=0
systemd-run --unit="$unidad" --wait --collect --property=Type=exec \
    --property=StandardOutput=journal --property=StandardError=journal \
    /usr/bin/python3 -B -u "$bundle/bootstrap.py" || resultado=$?
journalctl -u "$unidad.service" --since "$inicio" -n 100 -o cat --no-pager
exit "$resultado"
