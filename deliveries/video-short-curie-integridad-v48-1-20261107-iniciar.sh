#!/bin/bash
set -euo pipefail
umask 077

repo=/home/videoagent/Video-Optimizer-multiplatform
commit=f0f982f5d9eede234f617823de5dbcdd5cc58d45
unidad=video-short-curie-integridad-v48-1-20261107-install
paquete=$(mktemp /tmp/video-short-curie-integridad-v48-1.XXXXXX.tgz)
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
    "$commit:deliveries/video-short-curie-integridad-v48-1-20261107.tgz.b64" |
    base64 -d > "$paquete"
printf '%s  %s\n' \
    'f71f0f820930ebbf2b9ef4b7d1d6881655fa2c352678d01954aa52a3dd8d1b2c' \
    "$paquete" | sha256sum -c -

directorio=$(mktemp -d /tmp/video-short-curie-integridad-v48-1.XXXXXX)
chmod 0755 "$directorio"
tar -xzpf "$paquete" -C "$directorio"
bundle="$directorio/video-short-curie-integridad-v48-1-20261107"
runuser -u videoagent -- test -r "$bundle/single_catarsis_request.py"

echo 'Validando los cuatro hashes aprobados y preparando UN Short Catarsis de Marie Curie.'
echo 'Canal: Stunning Facts of History. Metadatos: YouTube, Facebook e Instagram.'
inicio=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
resultado=0
systemd-run --unit="$unidad" --wait --collect --property=Type=exec \
    --property=StandardOutput=journal --property=StandardError=journal \
    /usr/bin/python3 -B -u "$bundle/source_pin_recovery.py" || resultado=$?
journalctl -u "$unidad.service" --since "$inicio" -n 100 -o cat --no-pager
exit "$resultado"
