#!/bin/bash
# Exact owner-authorized Skylab publication. Run by the owner, not generation maintenance.
set -euo pipefail
umask 077

if [ "$(id -u)" -ne 0 ]; then
    echo 'Ejecuta este comando como root en la VPS.' >&2
    exit 2
fi

repo=/home/videoagent/Video-Optimizer-multiplatform
python=/home/videoagent/Video-Optimizer-multiplatform/.venv/bin/python
payload=a8a41df7f5d470c12d378920cb43f8f338c655bf
job=51c0cfdb56e743d88c68859e5b6df165
unit=video-documentary-youtube-51c0cfdb56e743d88c68859e5b6df165

if systemctl is-active --quiet "$unit.service"; then
    echo 'La subida de este documental ya esta en curso en la VPS.'
    journalctl -u "$unit.service" -n 40 -o cat --no-pager
    exit 0
fi

work=$(mktemp -d /tmp/video-skylab-youtube-v54.XXXXXX)
for name in publish_documentary.py documentary_youtube_core.py test_publish_documentary.py test_documentary_youtube_core.py test_local_thumbnail.py PUBLISH-SKYLAB.md thumbnail.jpg; do
    runuser -u videoagent -- git -C "$repo" show \
        "$payload:automation/documentary/publication-v54/$name" > "$work/$name"
done
(
    cd "$work"
    sha256sum -c <<'HASHES'
0feffb8e1d5f0ed112a78aef1efdc95ea526dfbc5caad33bfd08bcc7b30f282c  publish_documentary.py
9695d8e4010f6564dfe0e661bdf409dceeb2fa0b685e96f0129a75393c2bf5d3  documentary_youtube_core.py
abdb46852f3e38e38437bdfc20f6d7abc827b2cd4c60f68a25c73e747e143891  test_publish_documentary.py
e3731e9a7b53e5696bfc4c1e7dfd9e4405f26fb2b51baaddd9bf9844e7c21ad6  test_documentary_youtube_core.py
b484274be1178ecdf57c77028a3b1c964cb1635537a6706f56326d17215d28c4  test_local_thumbnail.py
8457ea54c6cd441138c1a800a81a68eeeea27d6616f8302973464b7138c67ec6  PUBLISH-SKYLAB.md
64011b446d2a89ec2edc5bb4612c0d559c9d96985e762780bf696a80cb8054ba  thumbnail.jpg
HASHES
)

chown -R videoagent:videoagent "$work"
chmod 700 "$work"
chmod 600 "$work"/*
runuser -u videoagent -- "$python" -B -m unittest discover -s "$work" -p 'test_*.py' -q

args=(--job-id "$job"
    --approval-sha256 049724008ad43e4cf42d8bed9a1ff8ea994213b119d725ea2c7d4fb2eee4742b
    --thumbnail-file "$work/thumbnail.jpg"
    --thumbnail-sha256 64011b446d2a89ec2edc5bb4612c0d559c9d96985e762780bf696a80cb8054ba
    --tag 'Skylab' --tag 'Skylab rescue' --tag 'Skylab 2'
    --tag 'NASA history' --tag 'space history' --tag '1973'
    --tag 'Pete Conrad' --tag 'Joseph Kerwin' --tag 'Paul Weitz'
    --tag 'space station' --tag 'solar array' --tag 'spacewalk'
    --tag 'space documentary' --tag 'Stunning Revelations')

runuser -u videoagent -- "$python" -B "$work/publish_documentary.py" "${args[@]}" --inspect

echo 'Subiendo Skylab a YouTube / Stunning Revelations con la miniatura elegida y SRT ingles.'
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
