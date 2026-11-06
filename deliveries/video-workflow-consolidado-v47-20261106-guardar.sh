#!/bin/bash
set -euo pipefail
umask 077

repo=/home/videoagent/Video-Optimizer-multiplatform
commit=8b25a1b1075417398efb576e75ab82f60f0d8a70
unidad=video-workflow-consolidado-v47-20261106
paquete=$(mktemp /tmp/video-workflow-consolidado-v47.XXXXXX.tgz)
trap 'rm -f "$paquete"' EXIT

if systemctl is-active --quiet "$unidad.service"; then
    echo 'La consolidación del flujo ya está en curso.'
    journalctl -u "$unidad.service" -n 40 -o cat --no-pager
    exit 0
fi

runuser -u videoagent -- git -C "$repo" show \
    "$commit:deliveries/video-workflow-consolidado-v47-20261106.tgz.b64" |
    base64 -d > "$paquete"
printf '%s  %s\n' \
    '2a9fbe80dae93feb18a5ced2ed3fbcf38fb8b391d5f5b251519109818bf6b8da' \
    "$paquete" | sha256sum -c -

directorio=$(mktemp -d /tmp/video-workflow-consolidado-v47.XXXXXX)
chmod 0755 "$directorio"
tar -xzpf "$paquete" -C "$directorio"
bundle="$directorio/video-workflow-consolidado-v47-20261106"
runuser -u videoagent -- test -r "$bundle/repo/automation/documentary/publication/publish_documentary.py"

echo 'Guardando el historial de correcciones, las fuentes y el publicador permanente.'
echo 'La instalación ejecutará sus pruebas y devolverá un recibo de persistencia.'
inicio=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
resultado=0
systemd-run --unit="$unidad" --wait --collect --property=Type=exec \
    --property=StandardOutput=journal --property=StandardError=journal \
    /usr/bin/python3 -B -u "$bundle/install_workflow.py" || resultado=$?
journalctl -u "$unidad.service" --since "$inicio" -n 100 -o cat --no-pager
exit "$resultado"
