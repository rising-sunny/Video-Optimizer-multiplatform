# -*- coding: utf-8 -*-
"""Prueba EN SECO la ingesta de video de Instagram: sube un mp4 y mira si Meta lo procesa.

No publica nada: crea un contenedor resumable, manda el binario en trozos y
espera el estado. Un contenedor sin publicar expira solo a las 24 h.

    .venv\\Scripts\\python.exe check_instagram_ingest.py                 # el ultimo short de auto_videos/output
    .venv\\Scripts\\python.exe check_instagram_ingest.py ruta\\video.mp4

Por que existe (2026-09-16): Instagram rechazo TODOS los videos durante al menos
dos dias ("Media upload has failed with error code 2207076" por URL; "Video
Transcoding Error: both HD and SD progressive failed to transcode" por rupload),
incluidos dos que ya habia publicado antes y desde dos cuentas distintas,
mientras Facebook publicaba los mismos mp4. Con esto se sabe en un minuto si
Meta ya se recupero, sin gastar una publicacion.
"""

from __future__ import annotations

import glob
import os
import sys
import time


def main() -> int:
    import instagram_uploader as ig

    if len(sys.argv) > 1:
        video = sys.argv[1]
    else:
        candidatos = sorted(glob.glob(os.path.join("auto_videos", "output", "youtube_short_*.mp4")), key=os.path.getmtime)
        if not candidatos:
            print("No hay shorts en auto_videos/output; pasa la ruta de un mp4.")
            return 2
        video = candidatos[-1]
    if not os.path.isfile(video):
        print(f"No existe: {video}")
        return 2

    identidad = ig._resolve_instagram_identity()
    token = identidad["access_token"]
    ig_user_id = identidad["ig_user_id"]
    print(f"Cuenta: @{identidad.get('instagram_username')} ({ig_user_id})")
    print(f"Video:  {video} ({os.path.getsize(video) / 1e6:.1f} MB)")

    inicio = time.time()
    try:
        container_id, estado = ig._publish_via_resumable(
            ig_user_id, token, video, "DRY RUN - no se publica", True,
            on_status=lambda m: print("   " + m),
        )
    except Exception as exc:
        print(f"\nRESULTADO: Meta NO proceso el video ({time.time() - inicio:.0f} s)")
        print(f"   {exc}")
        print("   Si el mismo mp4 se publica bien en Facebook, el problema es de Meta/Instagram, no del video.")
        return 1

    print(f"\nRESULTADO: contenedor {container_id} -> {estado.get('status_code')} ({time.time() - inicio:.0f} s)")
    print("   Instagram procesa videos otra vez. (No se publico nada; el contenedor expira solo.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
