#!/bin/bash
# Exact owner-authorized X-15 publication. Run by the owner, not generation maintenance.
set -euo pipefail
umask 077

if [ "$(id -u)" -ne 0 ]; then
    echo 'Ejecuta este comando como root en la VPS.' >&2
    exit 2
fi

repo=/home/videoagent/Video-Optimizer-multiplatform
python=/home/videoagent/Video-Optimizer-multiplatform/.venv/bin/python
payload=${1:-}
if [[ ! "$payload" =~ ^[a-f0-9]{40}$ ]]; then
    echo 'Falta el commit verificado de esta entrega.' >&2
    exit 2
fi
job=e280561cf14a4fd28803ae6ec52d60f0
unit=video-documentary-youtube-e280561cf14a4fd28803ae6ec52d60f0

if systemctl is-active --quiet "$unit.service"; then
    echo 'La subida de este documental ya esta en curso en la VPS.'
    journalctl -u "$unit.service" -n 40 -o cat --no-pager
    exit 0
fi

work=$(mktemp -d /tmp/video-x15-youtube-v56.XXXXXX)
for name in publish_documentary.py documentary_youtube_core.py test_publish_documentary.py test_documentary_youtube_core.py test_local_thumbnail.py PUBLISH-X15.md thumbnail.jpg; do
    runuser -u videoagent -- git -C "$repo" show \
        "$payload:automation/documentary/publication-x15-v56/$name" > "$work/$name"
done
(
    cd "$work"
    sha256sum -c <<'HASHES'
619b3ad1678c7fa33ffcdfd474a06c58a5fa82ea524eb9ea7f7d4de227a1f75e  PUBLISH-X15.md
9695d8e4010f6564dfe0e661bdf409dceeb2fa0b685e96f0129a75393c2bf5d3  documentary_youtube_core.py
0feffb8e1d5f0ed112a78aef1efdc95ea526dfbc5caad33bfd08bcc7b30f282c  publish_documentary.py
e3731e9a7b53e5696bfc4c1e7dfd9e4405f26fb2b51baaddd9bf9844e7c21ad6  test_documentary_youtube_core.py
b484274be1178ecdf57c77028a3b1c964cb1635537a6706f56326d17215d28c4  test_local_thumbnail.py
abdb46852f3e38e38437bdfc20f6d7abc827b2cd4c60f68a25c73e747e143891  test_publish_documentary.py
dc4edf5286bc680682b6c595f4ca5535b35d1f934099a497089b202f4b962c20  thumbnail.jpg
HASHES
)

chown -R videoagent:videoagent "$work"
chmod 700 "$work"
chmod 600 "$work"/*
runuser -u videoagent -- "$python" -B -m unittest discover -s "$work" -p 'test_*.py' -q

args=(--job-id "$job"
    --approval-sha256 d858144cf74b1b4ea27fd9b06c2da222671ec6001df87a8da230fd8c1a36c6ae
    --thumbnail-file "$work/thumbnail.jpg"
    --thumbnail-sha256 dc4edf5286bc680682b6c595f4ca5535b35d1f934099a497089b202f4b962c20
    --tag 'X-15' --tag 'X15' --tag 'North American X-15'
    --tag 'rocket plane' --tag 'NASA history' --tag 'hypersonic flight'
    --tag 'B-52' --tag 'Pete Knight' --tag 'Joseph Walker'
    --tag 'Edwards Air Force Base' --tag 'aviation history'
    --tag 'unpowered landing' --tag 'space documentary'
    --tag 'Stunning Revelations')

runuser -u videoagent -- "$python" -B "$work/publish_documentary.py" "${args[@]}" --inspect

echo 'Subiendo X-15 a YouTube / Stunning Revelations con la miniatura elegida y SRT ingles.'
echo 'Primero se carga en privado. Se hara publico al verificar el procesamiento y los subtitulos.'
echo 'Si hay una carga anterior, conserva su sesion y su ID. No genera otro video ni usa IA.'
echo 'El proceso continua en la VPS aunque se cierre SSH.'
echo "Avance: journalctl -u $unit.service -n 40 -o cat --no-pager"

start=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
result=0
systemd-run --unit="$unit" --wait --collect --property=Type=exec \
    --property=User=videoagent --property=Group=videoagent \
    --property=WorkingDirectory="$repo" --property=UMask=0077 \
    --property=RuntimeMaxSec=2h \
    --property=StandardOutput=journal --property=StandardError=journal \
    "$python" -B -u "$work/publish_documentary.py" "${args[@]}" --publish || result=$?

journalctl -u "$unit.service" --since "$start" -n 100 -o cat --no-pager
exit "$result"
