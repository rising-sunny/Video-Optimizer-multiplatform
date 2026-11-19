#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
app=/opt/youtube-short-covers
state=/var/lib/youtube-short-covers
install -d -m 755 "$app" "$app/brand"
install -d -m 700 "$state"
if [[ ! -s "$state/enabled-at" ]]; then date -u +%Y-%m-%dT%H:%M:%S+00:00 > "$state/enabled-at"; fi
install -m 755 cover.py "$app/cover.py"
install -m 644 channels.py reconcile.py "$app/"
install -m 644 brand/*.png "$app/brand/"
targets=(/opt/one-rule-lab/publisher.py /opt/mathrelaxing-auto/worker.py /home/videoagent/foh-daily/foh_publish.py /home/videoagent/nm-daily/run_day.py /opt/mathrelaxing-auto/test_worker.py)
keys=(lab math history mood math-test)
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
for i in "${!keys[@]}"; do
    f=${targets[i]}
    p="hooks/${keys[i]}.patch"
    if patch --reverse --force --dry-run --silent "$f" "$p" >/dev/null 2>&1; then continue; fi
    patch --forward --silent -o "$scratch/${keys[i]}.py" "$f" "$p"
    python3 - "$scratch/${keys[i]}.py" <<'PY'
import sys
from pathlib import Path
p=Path(sys.argv[1]);compile(p.read_text(),str(p),'exec')
PY
done
for i in "${!keys[@]}"; do
    f=${targets[i]}
    result="$scratch/${keys[i]}.py"
    [[ -f "$result" ]] || continue
    tmp=$(mktemp --tmpdir="$(dirname "$f")" .cover-install-XXXXXXXX)
    cp "$result" "$tmp"
    chown --reference="$f" "$tmp"
    chmod --reference="$f" "$tmp"
    mv -f "$tmp" "$f"
done
install -m 644 youtube-short-covers.service youtube-short-covers.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now youtube-short-covers.timer
