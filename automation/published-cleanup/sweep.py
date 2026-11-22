#!/usr/bin/env python3
"""Borra de la VPS los videos que YA estan publicados en alguno de los canales, para no ocupar disco.

    sweep.py                       simula: escribe el manifiesto y muestra que borraria (NO borra nada)
    sweep.py --apply               borra los archivos de video/audio que pasan TODAS las pruebas
    sweep.py --min-age-hours 6     (defecto) ignora archivos modificados hace menos de N horas

Un video cuenta como PUBLICADO solo si YouTube confirma ahora mismo que esta `public` o `unlisted` y `processed`, consultado con el token
del canal dueño (un Short programado que sigue privado NO cuenta). En los jobs del sistema paralelo (video-automation) ademas deben estar
`published` TODAS sus plataformas (youtube/facebook/instagram), porque ese sistema verifica el sha256 del video antes de publicar.

Solo se borran archivos de video/audio (.mp4 .mov .mkv .webm .avi .m4v .wav): nunca JSON, miniaturas ni material crudo (footage, clips, music, img,
blender_cache). No toca los videos *_ig/_fb (el estado de Instagram/Facebook de un proyecto no se puede comprobar), ni lo que no tenga registro.
Cada borrado queda en ~/published_cleanup/deleted.log y el manifiesto de cada corrida en ~/published_cleanup/manifest-<fecha>.json.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HOME = Path.home()
REPO = HOME / "Video-Optimizer-multiplatform"
sys.path.insert(0, str(REPO))
OUT = HOME / "published_cleanup"
OUT.mkdir(exist_ok=True)
EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".wav"}
ARTIFACT = re.compile(r"(?i)(?:^|[_-])(final|preview|upload)\.mp4$")
CHANNEL_VARIANT = re.compile(r"(?i)(?:^|[_-])(ig|fb|facebook|instagram|reel|tiktok)(?:[_.-]|$)")
LIVE_OK = ("public", "unlisted")


def media_files(directory, recursive=True):
    out = []
    for root, _dirs, files in os.walk(directory):
        for f in files:
            p = Path(root) / f
            if p.suffix.lower() in EXT and p.is_file() and not p.is_symlink():
                out.append(p)
        if not recursive:
            break
    return out


def jload(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


# ------------------------------------------------------------------ candidatos (cada uno trae SU prueba)
def collect():
    cands = []

    def add(system, label, files, ids_all=(), ids_any=(), other_ok=True, note=""):
        files = [f for f in files if f.exists()]
        if files:
            cands.append(dict(system=system, label=label, files=files, ids_all=[i for i in ids_all if i], ids_any=[i for i in ids_any if i], other_ok=other_ok, note=note))

    # 1) sistema paralelo (video-automation/runtime): publication.json con TODAS las plataformas publicadas
    for p in (HOME / "video-automation/runtime").rglob("publication.json"):
        d = jload(p)
        plats = (d or {}).get("platforms") or {}
        yt = plats.get("youtube") or {}
        ok = bool(plats) and all((v or {}).get("state") == "published" for v in plats.values())
        add("runtime", str(p.parent.relative_to(HOME)), media_files(p.parent), ids_all=[yt.get("video_id")], other_ok=ok,
            note="" if ok else "alguna plataforma NO esta 'published': " + str({k: (v or {}).get("state") for k, v in plats.items()}))

    # 2) automatizaciones diarias con recibo por dia (nm-daily, tla-daily, foh-daily)
    for root in ("nm-daily", "tla-daily", "foh-daily"):
        for r in sorted((HOME / root / "days").glob("*/receipt.json")):
            d = jload(r) or {}
            plats = d.get("platforms") if isinstance(d.get("platforms"), dict) and d.get("platforms") else None
            if plats is not None:                                   # foh: youtube + facebook + instagram
                yt = plats.get("youtube") or {}
                ok = bool(yt.get("ok")) and all((v or {}).get("ok") for v in plats.values())
                add(root, str(r.parent.relative_to(HOME)), media_files(r.parent), ids_all=[yt.get("video_id")], other_ok=ok,
                    note="" if ok else "no todas las plataformas ok")
            elif (d.get("youtube") or {}).get("ok"):                # nm / tla: solo YouTube
                add(root, str(r.parent.relative_to(HOME)), media_files(r.parent), ids_all=[d["youtube"].get("video_id")])
            # sin 'youtube.ok' = dia preparado o saltado: NO es candidato

    # 3) carpetas del repo con upload_result*.json (auto_videos)
    for r in (REPO / "auto_videos").rglob("upload_result*.json"):
        d = jload(r)
        if isinstance(d, dict) and d.get("video_id") and d.get("status") == "uploaded":
            add("repo/auto_videos", str(r.parent.relative_to(HOME)), media_files(r.parent), ids_all=[d["video_id"]])

    # 4) proyectos de documental: SOLO los renders publicados (final/preview/upload) y sus Shorts con id propio
    for proj in sorted((HOME / "video-projects").glob("*")):
        if not proj.is_dir():
            continue
        main_ids = []
        for r in proj.glob("upload_result*.json"):
            d = jload(r)
            if isinstance(d, dict) and d.get("video_id"):
                main_ids.append(d["video_id"])
        arts = [f for f in proj.glob("*.mp4") if ARTIFACT.search(f.name) and not CHANNEL_VARIANT.search(f.name)]
        if main_ids and arts:
            add("video-projects", f"{proj.name} (video principal)", arts, ids_any=main_ids)
        sr = jload(proj / "shorts" / "upload_results.json")
        if isinstance(sr, dict):
            for name, rec in sr.items():
                vid = (rec or {}).get("id") or (rec or {}).get("video_id")
                files = [f for f in (proj / "shorts").glob(f"{name}_*.mp4") if ARTIFACT.search(f.name) and not CHANNEL_VARIANT.search(f.name)]
                if vid and files:
                    add("video-projects", f"{proj.name}/shorts/{name}", files, ids_all=[vid])
    seen, uniq = set(), []                                           # un archivo solo puede pertenecer a un candidato (auto_videos repite upload_result)
    for c in cands:
        c["files"] = [f for f in c["files"] if f not in seen]
        seen.update(c["files"])
        if c["files"]:
            uniq.append(c)
    return uniq


HISTORICAL = re.compile(r"(?i)(?:attempts|archive|recovery-|shorts-resume-|workflow-attempts)")
JOB_ID = re.compile(r"[0-9a-f]{32}")


def _ignorable(video, referencing_json):
    """Un registro historico (intentos, archivo, recuperaciones puntuales) o del MISMO job no es un consumidor del video:
    el demonio de recuperacion omite todo job que ya tenga publication.json (caption_cleanup.py / autonomous_generation.py)."""
    rj = str(referencing_json)
    if HISTORICAL.search(rj):
        return True
    a, b = JOB_ID.findall(str(video)), JOB_ID.findall(rj)
    return bool(a) and bool(b) and a[0] == b[0]


def external_refs(files):
    """Archivos que algun JSON AJENO nombra por su ruta completa (p. ej. un job no publicado que los usa como material fuente): no se tocan."""
    names = {str(f): f for f in files}
    roots = [HOME / "video-automation", HOME / "video-projects", HOME / "nm-daily", HOME / "foh-daily", HOME / "tla-daily", REPO / "auto_videos", REPO / "long_form"]
    held = {}
    for root in roots:
        for dirpath, _d, fs in os.walk(root):
            for fn in fs:
                if not fn.endswith(".json"):
                    continue
                jp = Path(dirpath) / fn
                try:
                    if jp.stat().st_size > 6_000_000:
                        continue
                    text = jp.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                for path, f in names.items():
                    if path in text and str(f.parent) not in str(jp.parent) and not _ignorable(f, jp):
                        held.setdefault(path, str(jp))
    return held


# ------------------------------------------------------------------ prueba en vivo con YouTube
def live_status(ids):
    from googleapiclient.discovery import build
    from channel.channel_profiles import CHANNELS
    from publish.youtube_uploader import _get_credentials
    res, ids = {}, sorted(set(ids))
    for key in CHANNELS:
        try:
            svc = build("youtube", "v3", credentials=_get_credentials(interactive=False, channel_profile=key), cache_discovery=False)
        except Exception as e:                                       # canal sin token: se sigue con los demas
            print(f"   (sin token para {key}: {str(e)[:60]})")
            continue
        todo = [i for i in ids if i not in res]
        for k in range(0, len(todo), 50):
            for it in svc.videos().list(part="status", id=",".join(todo[k:k + 50])).execute().get("items", []):
                res[it["id"]] = dict(channel=key, privacy=it["status"].get("privacyStatus"), upload=it["status"].get("uploadStatus"), publish_at=it["status"].get("publishAt"))
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--min-age-hours", type=float, default=6.0)
    a = ap.parse_args()
    if a.apply and (OUT / "STOP").exists():                          # interruptor: touch ~/published_cleanup/STOP
        print("interruptor STOP activo: no se borra nada")
        return
    cands = collect()
    all_ids = [i for c in cands for i in c["ids_all"] + c["ids_any"]]
    live = live_status(all_ids) if all_ids else {}
    now = time.time()
    held = external_refs([f for c in cands for f in c["files"]])
    plan, kept = [], []
    for c in cands:
        def ok(i):
            s = live.get(i)
            return bool(s) and s["privacy"] in LIVE_OK and s["upload"] == "processed"
        reasons = []
        if not c["other_ok"]:
            reasons.append(c["note"])
        if c["ids_all"] and not all(ok(i) for i in c["ids_all"]):
            reasons.append("YouTube no lo confirma publicado: " + str({i: (live.get(i) or {}).get("privacy", "no existe") for i in c["ids_all"]}))
        if c["ids_any"] and not any(ok(i) for i in c["ids_any"]):
            reasons.append("ningun id confirmado publicado en YouTube: " + str({i: (live.get(i) or {}).get("privacy", "no existe") for i in c["ids_any"]}))
        if not c["ids_all"] and not c["ids_any"]:
            reasons.append("sin id de YouTube")
        fresh = [f for f in c["files"] if now - f.stat().st_mtime < a.min_age_hours * 3600]
        referenced = [f for f in c["files"] if str(f) in held]
        if referenced and not reasons:
            reasons.append(f"{len(referenced)} archivo(s) referenciados por otro JSON: {held[str(referenced[0])].replace(str(HOME) + '/', '')}")
        files = [f for f in c["files"] if f not in fresh and f not in referenced]
        if fresh and not reasons:
            reasons.append(f"{len(fresh)} archivo(s) modificados hace < {a.min_age_hours:g} h")
        size = sum(f.stat().st_size for f in c["files"])
        if reasons or not files:
            kept.append((c, reasons, size))
        else:
            plan.append((c, files, sum(f.stat().st_size for f in files)))

    by_sys = {}
    for c, files, size in plan:
        by_sys.setdefault(c["system"], [0, 0])
        by_sys[c["system"]][0] += len(files)
        by_sys[c["system"]][1] += size
    stamp = time.strftime("%Y%m%d-%H%M%S")
    manifest = dict(created=stamp, apply=a.apply, to_delete=[dict(system=c["system"], label=c["label"], ids=c["ids_all"] + c["ids_any"],
                    files=[dict(path=str(f), bytes=f.stat().st_size) for f in files]) for c, files, _ in plan],
                    kept=[dict(system=c["system"], label=c["label"], bytes=s, reasons=r) for c, r, s in kept])
    (OUT / f"manifest-{stamp}.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))

    print(f"\n{'APLICANDO' if a.apply else 'SIMULACION (no se borra nada)'} - {time.strftime('%F %T')}")
    print("\n== A BORRAR (videos confirmados como publicados) ==")
    for sysname, (n, b) in sorted(by_sys.items()):
        print(f"  {sysname:18s} {n:4d} archivos {b / 1e6:9.0f} MB")
    for c, files, size in sorted(plan, key=lambda x: -x[2])[:40]:
        print(f"    {size / 1e6:7.0f} MB  {c['label']}  ids={c['ids_all'] + c['ids_any']}")
    tot = sum(b for _, b in by_sys.values())
    print(f"  TOTAL: {tot / 1e9:.2f} GB")
    print("\n== SE CONSERVAN (con motivo) ==")
    for c, r, s in sorted(kept, key=lambda x: -x[2])[:25]:
        if s > 1e6:
            print(f"    {s / 1e6:7.0f} MB  {c['label']}: {'; '.join(r)[:170]}")

    if a.apply:
        log = open(OUT / "deleted.log", "a")
        freed = 0
        for c, files, _ in plan:
            for f in files:
                try:
                    if f.is_symlink() or not f.is_file() or f.suffix.lower() not in EXT:
                        continue
                    sz = f.stat().st_size
                    f.unlink()
                    freed += sz
                    log.write(f"{time.strftime('%F %T')}\t{sz}\t{f}\t{c['system']}\t{','.join(c['ids_all'] + c['ids_any'])}\n")
                except Exception as e:
                    print(f"   no se pudo borrar {f}: {e}")
        log.close()
        print(f"\nLiberados {freed / 1e9:.2f} GB. Registro: {OUT / 'deleted.log'}")
        os.system("df -h /home | tail -1")


if __name__ == "__main__":
    main()
