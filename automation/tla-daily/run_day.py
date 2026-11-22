"""Ejecutor de The Lost Atlas. Uso: run_day.py [--date AAAA-MM-DD] [--dry-run] [--template geo|year|empire]
 - STOP (archivo) = interruptor.  - Sin recuperar atrasos: solo la fecha de HOY.
 - Idempotente: si el dia ya esta publicado no hace nada (por eso el cron corre 3 veces: son reintentos).
 - Politica del repo: se SALTA el dia si fallan la verificacion de hechos (Wikipedia + DeepSeek) o el QA del video.
 - Plantilla del dia: rota geo -> year -> empire por ordinal de fecha. Musica: una pista distinta cada dia (lostatlas/music_pool.py)."""
import argparse, json, os, re, shutil, subprocess, sys, traceback
import datetime as dt
from pathlib import Path
from common import *

date = today(); ROUNDS = 3


def qa(mp4):
    p = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration,size:stream=width,height,r_frame_rate,codec_type', '-of', 'json', str(mp4)], capture_output=True, text=True)
    j = json.loads(p.stdout); dur = float(j['format']['duration']); size = int(j['format']['size']) / 1e6
    v = next(s for s in j['streams'] if s['codec_type'] == 'video'); num, den = (int(x) for x in v['r_frame_rate'].split('/'))
    has_audio = any(s['codec_type'] == 'audio' for s in j['streams'])
    e = subprocess.run(['ffmpeg', '-v', 'info', '-i', str(mp4), '-vf', 'blackdetect=d=0.5:pix_th=0.05', '-af', 'ebur128=peak=true', '-f', 'null', '-'], capture_output=True, text=True).stderr
    black = len(re.findall(r'black_start', e)); m = re.findall(r'I:\s+(-?[\d.]+) LUFS', e); lufs = float(m[-1]) if m else None
    m = re.findall(r'Peak:\s+(-?[\d.]+) dBFS', e); peak = float(m[-1]) if m else None
    r = dict(duration=round(dur, 2), size_mb=round(size, 1), res=f"{v['width']}x{v['height']}", fps=round(num / den, 1), audio=has_audio, black_segments=black, lufs=lufs, peak=peak)
    bad = []
    if not 38 <= dur <= 58: bad.append(f'duracion {dur}')
    if r['res'] != '1080x1920': bad.append('resolucion')
    if size > 80: bad.append(f'peso {size} MB')
    if black: bad.append('cuadros negros')
    if not has_audio: bad.append('sin audio')
    if lufs is None or not -20 <= lufs <= -10: bad.append(f'volumen {lufs}')
    if peak is not None and peak > -0.9: bad.append(f'pico {peak}')
    r['problems'] = bad
    return r


def questions_for(ddir, receipt, template, ordinal):
    """Preguntas VERIFICADAS del dia (se reutilizan en los reintentos del mismo dia: no se vuelve a gastar API)."""
    qf = ddir / 'questions.json'
    if qf.exists():
        qs = json.loads(qf.read_text())
        if qs and all(q.get('verified') is True for q in qs): return qs
    from lostatlas import daily_gen
    log(f'{date}: generando y verificando preguntas ({template})...')
    try:
        qs = daily_gen.build_day(template, STATE, ordinal, seed=ordinal * 31 + len(template), log=log)
    except daily_gen.NotEnough as e:
        raise Skip(f'verificacion de hechos: {e}')
    if not all(q.get('verified') is True for q in qs): raise Skip('preguntas sin verificar')
    atomic(qf, qs); receipt['template'] = template; atomic(ddir / 'receipt.json', receipt)
    return qs


def make(qs, template, ddir, n, ordinal, episode):
    from lostatlas import music_pool, music_lib
    from lostatlas.make_short import render
    from lostatlas.publish_pack import write_package
    from lostatlas.hist import ATTRIBUTION
    track = music_pool.pick(ordinal, n)
    mp3, attribution, _ = music_lib.fetch(track)
    log(f'{date}: ronda {n + 1}: {template} + musica "{track}"')
    folder = ddir / f'run{n}'; shutil.rmtree(folder, ignore_errors=True)
    mp4 = render(qs, folder, episode=episode, with_audio=True, bgm=mp3)
    extra = ('Maps:\n' + ATTRIBUTION) if template == 'empire' else None
    write_package(folder, mp4, template, qs, 'Music:\n' + attribution, extra, day_index=ordinal)
    return track, folder, mp4


def ensure_tags(receipt, ddir):
    """YouTube a veces muestra 0 tags justo tras subir (visto el 2026-11-22). Las pasadas posteriores del cron los verifican y reponen."""
    if receipt.get('tags_ok'): return
    try:
        folder = Path(receipt['folder']); meta = json.loads((folder / 'metadata.json').read_text())
        os.environ['YOUTUBE_TITLE_MODE'] = 'off'
        from publish.youtube_uploader import get_youtube_service
        from publish.youtube_tags import finalize_youtube_tags
        yt = get_youtube_service(interactive=False, channel_profile=CHANNEL)
        vid = receipt['youtube']['video_id']
        sn = yt.videos().list(part='snippet', id=vid).execute()['items'][0]['snippet']
        if not sn.get('tags'):
            sn['tags'] = finalize_youtube_tags(meta['tags'])
            yt.videos().update(part='snippet', body={'id': vid, 'snippet': {k: sn[k] for k in ('title', 'description', 'tags', 'categoryId')}}).execute()
            log(f"{date}: tags repuestos en {vid} ({len(sn['tags'])})")
        receipt['tags_ok'] = True; atomic(ddir / 'receipt.json', receipt)
    except Exception as e:
        log(f"{date}: aviso: no se pudieron verificar los tags ({str(e)[:100]})")


def main():
    if STOP.exists(): raise Skip('interruptor STOP activo')
    if free_gb() < MIN_FREE_GB: raise Skip(f'disco insuficiente ({free_gb():.1f} GB libres)')
    ordinal = dt.date.fromisoformat(date).toordinal()
    template = args.template or TEMPLATES[ordinal % len(TEMPLATES)]
    ddir = ROOT / 'days' / date; ddir.mkdir(parents=True, exist_ok=True)
    receipt = load(ddir / 'receipt.json', {'date': date})
    if receipt.get('youtube', {}).get('ok'): log(f'{date}: ya publicado; nada que hacer'); ensure_tags(receipt, ddir); return
    receipt.pop('skipped', None)
    published = [p for p in (ROOT / 'days').iterdir() if p.is_dir() and load(p / 'receipt.json', {}).get('youtube', {}).get('ok')]
    episode = len(published) + 1
    qs = questions_for(ddir, receipt, template, ordinal)
    folder = Path(receipt['folder']) if receipt.get('folder') and not (receipt.get('qa') or {}).get('problems', ['x']) else None
    if not folder or not (folder / 'metadata.json').exists():
        folder, last = None, None
        for n in range(ROUNDS):
            try:
                track, f, mp4 = make(qs, template, ddir, n, ordinal, episode); q = qa(mp4); log(f'QA {q}')
                if not q['problems']: folder = Path(f); receipt.update(template=template, track=track, folder=str(folder), qa=q); atomic(ddir / 'receipt.json', receipt); break
                last = q['problems']; shutil.rmtree(f, ignore_errors=True)
            except Exception as e:
                last = [str(e)[:200]]; log(f'ronda {n + 1} fallo: {str(e)[:200]}\n{traceback.format_exc()[-600:]}')
        if not folder: receipt['skipped'] = str(last); atomic(ddir / 'receipt.json', receipt); raise Skip(f'QA o render fallido tras los reintentos: {last}')
    meta = json.loads((folder / 'metadata.json').read_text()); mp4 = str(folder / 'short.mp4')
    if meta.get('fact_check') != 'verified': raise Skip('metadata sin verificacion de hechos')
    if args.dry_run: log(f"--dry-run: sin publicar. Titulo: {meta['title']} | pista: {receipt.get('track')}"); return
    os.environ['YOUTUBE_TITLE_MODE'] = 'off'
    from dotenv import load_dotenv; load_dotenv(REPO / '.env')
    from publish.youtube_uploader import upload_video, get_youtube_service
    from publish.youtube_tags import finalize_youtube_tags
    from publish.music_license import with_attribution, DESCRIPTION_LIMITS
    description = with_attribution(meta['description'], meta.get('music_attribution'), DESCRIPTION_LIMITS['youtube'])
    tags = finalize_youtube_tags(meta['tags'])
    yt = get_youtube_service(interactive=False, channel_profile=CHANNEL)
    # Guarda anti-duplicado: si ya hay una subida reciente con el mismo titulo (una ejecucion anterior fallo DESPUES de subir), se adopta.
    try:
        up = yt.channels().list(part='contentDetails', mine=True).execute()['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        ids = [i['contentDetails']['videoId'] for i in yt.playlistItems().list(part='contentDetails', playlistId=up, maxResults=10).execute().get('items', [])]
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=20)
        for v in (yt.videos().list(part='snippet', id=','.join(ids)).execute().get('items', []) if ids else []):
            if v['snippet']['title'] == meta['title'] and dt.datetime.fromisoformat(v['snippet']['publishedAt'].replace('Z', '+00:00')) > cutoff:
                receipt['youtube'] = dict(ok=True, video_id=v['id'], url=f"https://youtube.com/shorts/{v['id']}", title=meta['title'], adopted=True)
                atomic(ddir / 'receipt.json', receipt); log(f"{date}: ya existia en el canal ({v['id']}); no se sube de nuevo"); return
    except Exception as e:
        log(f'{date}: no se pudo comprobar duplicados ({str(e)[:120]}); se continua')
    try:
        r = upload_video(mp4, meta['title'], description=description, tags=tags, category_id=str(meta.get('category_id') or '27'), privacy_status='public', publish_at=None,
                         made_for_kids=False, is_short=True, thumbnail_path=None, channel_profile=CHANNEL, tag_research=False, title_mode='off')
        receipt['youtube'] = dict(ok=True, video_id=r.get('video_id'), url=r.get('url'), title=meta['title'])
        atomic(ddir / 'receipt.json', receipt)                        # se registra YA: nada de lo que siga puede provocar una segunda subida
    except Exception as e:
        receipt['youtube'] = dict(ok=False, error=str(e)[:300])
    if receipt['youtube'].get('ok'):
        from lostatlas import daily_gen
        daily_gen.mark_used(STATE, template, qs, ordinal)             # cooldown de entidades: solo cuando YA se publico
        try:                                                              # los tags son accesorios: si fallan, no cambia el resultado
            v = yt.videos().list(part='snippet', id=receipt['youtube']['video_id']).execute()['items'][0]
            if not v['snippet'].get('tags'):
                sn = v['snippet']; sn['tags'] = tags
                yt.videos().update(part='snippet', body={'id': receipt['youtube']['video_id'], 'snippet': {k: sn[k] for k in ('title', 'description', 'tags', 'categoryId')}}).execute()
        except Exception as e:
            log(f"{date}: aviso: no se pudieron reponer los tags ({str(e)[:100]}); YouTube suele aplicarlos despues")
    atomic(ddir / 'receipt.json', receipt)
    log(f"{date}: publicacion -> {json.dumps(receipt['youtube'], ensure_ascii=False)}")
    pub = sorted(p for p in (ROOT / 'days').iterdir() if p.is_dir() and load(p / 'receipt.json', {}).get('youtube', {}).get('ok'))   # limpieza: solo dias YA publicados
    for p in pub[:-3]:
        for sub in p.glob('run*'): shutil.rmtree(sub, ignore_errors=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--date')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--template', choices=TEMPLATES)
    args = ap.parse_args()
    date = args.date or today()
    try:
        with Lock(): main()
    except Skip as e:
        log(f'{date}: SALTADO — {e}')
        d = ROOT / 'days' / date
        if d.exists(): r = load(d / 'receipt.json', {}); r['skipped'] = str(e); atomic(d / 'receipt.json', r)
    except Exception as e:
        log(f'{date}: ERROR {e}\n{traceback.format_exc()[-1500:]}'); sys.exit(1)
