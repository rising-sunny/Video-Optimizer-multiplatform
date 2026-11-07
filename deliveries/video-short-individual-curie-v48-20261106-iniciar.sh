#!/bin/bash
set -euo pipefail
umask 077

repo=/home/videoagent/Video-Optimizer-multiplatform
commit=80cda3552b142bdfe1d724cf8e783e842fe2aed5
unidad=video-short-individual-curie-v48-20261106-install
paquete=$(mktemp /tmp/video-short-individual-curie-v48.XXXXXX.tgz)
trap 'rm -f "$paquete"' EXIT

if systemctl is-active --quiet "$unidad.service"; then
    echo 'La preparación del Short individual ya está en curso.'
    journalctl -u "$unidad.service" -n 50 -o cat --no-pager
    exit 0
fi

# Complete the earlier authorized persistence once, if still pending.
if ! python3 -B - <<'CHECK_WORKFLOW'
import json
from pathlib import Path
try:
    value=json.loads(Path('/home/videoagent/video-automation/ops/documentary/installation-receipt.json').read_text())
except (OSError,ValueError):
    raise SystemExit(1)
raise SystemExit(0 if value.get('state')=='saved' and value.get('release')=='workflow-consolidated-v47-20261106' else 1)
CHECK_WORKFLOW
then
    runuser -u videoagent -- git -C "$repo" show \
        '9cde53734aea33f4215bc9625dbd01f507367d10:deliveries/video-workflow-consolidado-v47-20261106-guardar.sh' | bash
fi

runuser -u videoagent -- git -C "$repo" show \
    "$commit:deliveries/video-short-individual-curie-v48-20261106.tgz.b64" |
    base64 -d > "$paquete"
printf '%s  %s\n' \
    '83e93a83a4cdd7dff663ecbdeb90faada9b7921ff78bdd146b8aada2c745c0e1' \
    "$paquete" | sha256sum -c -

directorio=$(mktemp -d /tmp/video-short-individual-curie-v48.XXXXXX)
chmod 0755 "$directorio"
tar -xzpf "$paquete" -C "$directorio"
bundle="$directorio/video-short-individual-curie-v48-20261106"
runuser -u videoagent -- test -r "$bundle/single_catarsis_request.py"

echo 'Preparando UN Short Catarsis: Marie Curie y las unidades móviles de rayos X.'
echo 'Canal: Stunning Facts of History. Metadatos: YouTube, Facebook e Instagram.'
inicio=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
resultado=0
systemd-run --unit="$unidad" --wait --collect --property=Type=exec \
    --property=StandardOutput=journal --property=StandardError=journal \
    /usr/bin/python3 -B -u "$bundle/install.py" || resultado=$?
journalctl -u "$unidad.service" --since "$inicio" -n 100 -o cat --no-pager
exit "$resultado"
