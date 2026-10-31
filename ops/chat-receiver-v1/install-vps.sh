#!/usr/bin/env bash
set -euo pipefail
umask 077

root=/home/videoagent/video-automation
repo=/home/videoagent/Video-Optimizer-multiplatform
python="$repo/.venv/bin/python"
path_in_repo=ops/chat-receiver-v1
expected=fa7ce7baf3df3c761ad73c6d1b2097599dca0350c29cd8b62bc8902c69008245

if [[ $(id -un) != videoagent ]]; then
    echo 'Ejecuta este instalador como videoagent.' >&2
    exit 2
fi
if [[ ! ${1:-} =~ ^[0-9a-f]{12,40}$ ]]; then
    echo 'Se requiere el commit indicado para esta entrega.' >&2
    exit 2
fi
revision=$(git -C "$repo" rev-parse --verify "$1^{commit}")
destination="$root/runtime/chat-receiver-kit-v1"
if [[ -e "$destination" || -L "$destination" ]]; then
    echo 'El directorio del kit ya existe; no se reemplazará. Comparte esta salida.' >&2
    exit 2
fi

scratch=$(mktemp -d "$root/runtime/.chat-kit.XXXXXX")
trap 'rm -rf -- "$scratch"' EXIT
git -C "$repo" show "$revision:$path_in_repo/chat-receiver-kit-v1.tar.xz" > "$scratch/kit.tar.xz"
printf '%s  %s\n' "$expected" "$scratch/kit.tar.xz" | sha256sum --check --status

"$python" -B - "$scratch/kit.tar.xz" "$destination" <<'PY'
import hashlib,io,json,sys,tarfile
from pathlib import Path
archive,destination=map(Path,sys.argv[1:])
expected='fa7ce7baf3df3c761ad73c6d1b2097599dca0350c29cd8b62bc8902c69008245'
raw=archive.read_bytes()
if hashlib.sha256(raw).hexdigest()!=expected:
    raise SystemExit('Checksum del kit incorrecto; instalación cancelada.')
allowed={'chat_package.py','chat_receiver.py','chat_bridge_patch.py',
         'install_chat_receiver.py','test_chat_smoke.py','README.md',
         'LOCAL-VALIDATION.json','KIT-SHA256.json'}
with tarfile.open(fileobj=io.BytesIO(raw),mode='r:xz') as package:
    members=package.getmembers()
    if len(members)!=len(allowed) or {m.name for m in members}!=allowed:
        raise SystemExit('Lista de archivos inesperada.')
    if any(not m.isfile() or m.size>256*1024 for m in members):
        raise SystemExit('Tipo o tamaño de archivo inesperado.')
    destination.mkdir(mode=0o700)
    package.extractall(destination,filter='data')
checks=json.loads((destination/'KIT-SHA256.json').read_text())
for name,value in checks.items():
    if name not in allowed or hashlib.sha256((destination/name).read_bytes()).hexdigest()!=value:
        raise SystemExit('Checksum de fuente incorrecto; instalación cancelada.')
print('Kit verificado. El instalador ejecutará respaldo y pruebas.',flush=True)
PY

"$python" -B "$destination/install_chat_receiver.py"
