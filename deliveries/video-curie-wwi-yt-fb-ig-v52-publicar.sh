#!/bin/bash
# Explicit user request: publish the approved Curie WWI Short to Facts YT/FB/IG.
# This bootstrap must be invoked by the owner in the VPS, never maintenance MCP.
set -euo pipefail
umask 077

if [ "$(id -u)" -ne 0 ]; then
    echo 'Ejecuta este comando como root en la VPS.' >&2
    exit 2
fi

repo=/home/videoagent/Video-Optimizer-multiplatform
payload=7cc3c932cfc3b1469f3d9aabde7c32766bdbdf89
python=/home/videoagent/Video-Optimizer-multiplatform/.venv/bin/python
work=$(mktemp -d /tmp/video-curie-publicar-v52.XXXXXX)
state=/var/lib/video-agent-prepare/catarsis-single-publication

runuser -u videoagent -- git -C "$repo" show \
    "$payload:automation/catarsis-single/publication/publish_single.py" > "$work/publish_single.py"
runuser -u videoagent -- git -C "$repo" show \
    "$payload:automation/catarsis-single/publication/test_publish_single.py" > "$work/test_publish_single.py"

printf '%s  %s\n' \
    'df81c123035ea136cd71b5ebdf433f833471a0cafa111d2fd8bc9e4d9b008df8' "$work/publish_single.py" \
    'bf013563f69092ebdd3bf6fd50a7e6b4f2f29f908ca8a5d4c168fc7862fbada2' "$work/test_publish_single.py" |
    sha256sum -c -

if [ -L "$state" ]; then
    echo 'Directorio de publicacion no valido.' >&2
    exit 2
fi
install -d -m 700 -o videoagent -g videoagent "$state"
chown -R videoagent:videoagent "$work"
chmod 700 "$work"
chmod 600 "$work/publish_single.py" "$work/test_publish_single.py"

runuser -u videoagent -- "$python" -B -m unittest discover -s "$work" -p test_publish_single.py -q
runuser -u videoagent -- "$python" -B "$work/publish_single.py" --inspect

echo 'Publicando la version WWI aprobada de Marie Curie en Stunning Facts of History: YouTube, Facebook e Instagram.'
echo 'El proceso sigue en la VPS si se corta SSH. No genera otro video ni usa IA.'
echo 'Avance: journalctl -u video-curie-wwi-publicar-v52.service -n 30 -o cat --no-pager'

resultado=0
systemd-run --unit=video-curie-wwi-publicar-v52 \
    --wait --collect --property=Type=exec \
    --property=StandardOutput=journal --property=StandardError=journal \
    /usr/sbin/runuser -u videoagent -- "$python" -B -u "$work/publish_single.py" --publish || resultado=$?

journalctl -u video-curie-wwi-publicar-v52.service -n 50 -o cat --no-pager
exit "$resultado"
