"""Import the non-secret production context; never installs services or publishes."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import zipfile

REPO = 'rising-sunny/Video-Optimizer-multiplatform'
PACKAGE_PATH = 'vps-bootstrap/CATARSIS_VPS_CONTEXTO.zip'
PACKAGE_SHA256 = '12297cbef70dc75f11bc3c0a2a8dd3dd560c41e032b792634e8e60c1441e9548'


def verify(body):
    if hashlib.sha256(body).hexdigest() != PACKAGE_SHA256:
        raise RuntimeError('El SHA-256 del paquete no coincide; importación detenida.')
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        infos = archive.infolist()
        names = archive.namelist()
        if len(infos) != 13 or len(names) != len(set(names)):
            raise RuntimeError('Inventario de archivos inesperado.')
        if sum(i.file_size for i in infos) > 10 * 1024 * 1024:
            raise RuntimeError('Tamaño descomprimido inesperado.')
        for item in infos:
            path = Path(item.filename)
            kind = stat.S_IFMT(item.external_attr >> 16)
            if (path.is_absolute() or '..' in path.parts or '\\' in item.filename
                    or path.suffix not in {'.md', '.json', '.jpg'}
                    or kind not in {0, stat.S_IFREG}):
                raise RuntimeError('Tipo o ruta de archivo inesperado.')
        checksums = json.loads(archive.read('SHA256SUMS.json'))
        if set(checksums) != set(names) - {'SHA256SUMS.json'}:
            raise RuntimeError('Manifiesto incompleto.')
        contents = {name: archive.read(name) for name in names}
        for name, digest in checksums.items():
            if hashlib.sha256(contents[name]).hexdigest() != digest:
                raise RuntimeError('Comprobación individual fallida.')
    return contents


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ref', help='SHA completo del commit de GitHub')
    parser.add_argument('--archive', type=Path, help='Paquete local para validación sin red')
    parser.add_argument('--dest', type=Path,
                        default=Path.home() / 'video-automation' / 'context-20261016')
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise RuntimeError('Ejecuta este importador como videoagent, no como root.')
    if args.archive:
        body = args.archive.read_bytes()
    else:
        if not args.ref or not re.fullmatch(r'[a-fA-F0-9]{40}', args.ref):
            raise RuntimeError('Se requiere el SHA completo con --ref.')
        result = subprocess.run([
            'gh', 'api', f'repos/{REPO}/contents/{PACKAGE_PATH}?ref={args.ref}',
            '-H', 'Accept: application/vnd.github.raw',
        ], capture_output=True, timeout=90)
        if result.returncode:
            raise RuntimeError(f'La descarga con gh falló (código {result.returncode}).')
        body = result.stdout
    contents = verify(body)
    destination = args.dest.absolute()
    if destination.is_symlink():
        raise RuntimeError('El destino es un enlace; no se modificó.')
    if destination.exists():
        for name, content in contents.items():
            p = destination / name
            if p.is_symlink() or not p.is_file() or p.read_bytes() != content:
                raise RuntimeError('Ya existe un contexto diferente; no se sobrescribió.')
        print('CONTEXTO_YA_IMPORTADO', destination)
        return
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='.context-import-', dir=destination.parent) as tmp:
        stage = Path(tmp) / 'context'
        stage.mkdir(mode=0o700)
        for name, content in contents.items():
            p = stage / name
            p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with p.open('xb') as handle:
                handle.write(content)
            p.chmod(0o600)
        stage.rename(destination)
    print('CONTEXTO_IMPORTADO_OK', destination)
    print('30 días, 6 pistas y registro del día 1. Ningún servicio activado; sin publicaciones.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Avoid raw gh/network exception output, which may contain auth details.
        if isinstance(error, RuntimeError):
            print('IMPORTACION_DETENIDA:', error)
        else:
            print('IMPORTACION_DETENIDA:', type(error).__name__)
        raise SystemExit(1)
