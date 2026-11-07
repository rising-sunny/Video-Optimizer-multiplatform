#!/bin/bash
set -euo pipefail
umask 077
repo=/home/videoagent/Video-Optimizer-multiplatform
commit=89d89073c60501bbdfcd084273b29a55d143d100
unidad=video-short-curie-json-v48-2-20261107-install
paquete=$(mktemp /tmp/video-short-curie-json-v48-2.XXXXXX.tgz)
trap 'rm -f "$paquete"' EXIT

if systemctl is-active --quiet "$unidad.service"; then
    echo 'La recuperación de este Short ya está en curso.'
    journalctl -u "$unidad.service" -n 50 -o cat --no-pager
    exit 0
fi
runuser -u videoagent -- git -C "$repo" show \
    "$commit:deliveries/video-short-curie-json-v48-2-20261107.tgz.b64" |
    base64 -d > "$paquete"
printf '%s  %s\n' \
    '55d9cc9e7ac5584ce3927ab9dc8178a1b862f52e29d0978615e7c74f579bf76f' \
    "$paquete" | sha256sum -c -
directorio=$(mktemp -d /tmp/video-short-curie-json-v48-2.XXXXXX)
chmod 0755 "$directorio"
tar -xzpf "$paquete" -C "$directorio"
bundle="$directorio/video-short-curie-json-v48-2-20261107"
runuser -u videoagent -- test -r "$bundle/shorts_single_json.py"
echo 'Validando y recuperando el plan guardado del mismo Short de Marie Curie.'
echo 'Conserva el lote y presupuesto originales. Canal: Stunning Facts of History.'
inicio=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
resultado=0
systemd-run --unit="$unidad" --wait --collect --property=Type=exec \
    --property=StandardOutput=journal --property=StandardError=journal \
    /usr/bin/python3 -B -u "$bundle/install_recovery.py" || resultado=$?
journalctl -u "$unidad.service" --since "$inicio" -n 100 -o cat --no-pager
exit "$resultado"
