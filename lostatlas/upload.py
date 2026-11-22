"""Sube un Short ya empaquetado a The Lost Atlas con el mismo uploader de los otros canales.

    python -m lostatlas.upload auto_videos/lostatlas/<carpeta> [--privacy unlisted] [--publish-at 2026-12-01T15:00:00Z]

Guardas (politica del repo): por defecto sube como NO LISTADO; y se niega si alguna pregunta no esta verificada
(fact_check != verified) salvo --allow-unverified. La subida automatica a este canal NO esta autorizada: este comando
se corre a mano, o con permiso explicito del usuario.
"""
import argparse
import json
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder")
    ap.add_argument("--privacy", choices=["private", "unlisted", "public"], default="unlisted")
    ap.add_argument("--publish-at")
    ap.add_argument("--allow-unverified", action="store_true")
    a = ap.parse_args()
    folder = Path(a.folder)
    meta = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    if meta.get("upload_channel") != "the-lost-atlas":
        sys.exit("Esta carpeta no es de the-lost-atlas.")
    if meta.get("fact_check") != "verified" and not a.allow_unverified:
        sys.exit("Preguntas SIN verificar (fact_check=pending): verificalas y marca verified=True, o usa --allow-unverified para una prueba privada/no listada.")
    from publish.youtube_uploader import upload_from_metadata
    res = upload_from_metadata(str(folder), privacy_status=a.privacy, publish_at=a.publish_at)
    print(json.dumps({k: res.get(k) for k in ("video_id", "url", "status")}, indent=1))


if __name__ == "__main__":
    main()
