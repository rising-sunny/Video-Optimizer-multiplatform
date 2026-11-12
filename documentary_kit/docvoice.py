"""Voz documental con edge-tts: narrador + lector de citas/documentos, con pausas segun la puntuacion.

Marcado en el guion:  «texto»  = lo lee la voz de LECTOR (cita literal de un documento, fallo, testimonio). Puede ir a mitad de frase.
  Ej.:  He wrote: «This was a man-made disaster; it was in no sense an act of God.»
Roles -> voz/rate/pitch en ROLES. Pausas: PAUSE (tras cada trozo segun su ultimo signo) + extra explicito con '~~' al final ('~~' = +0,6 s de silencio, para un golpe).
API: narrate(chapters, out_dir, roles=ROLES) -> (AudioSegment, timings)  | timings = lista de dicts compatible con compose.py (id, chapter, chapter_index, text, start, end, dur, first_of_chapter)."""
from __future__ import annotations
import asyncio, hashlib, re
from pathlib import Path
import edge_tts
from pydub import AudioSegment

ROLES = {'narration': ('en-US-ChristopherNeural', '-6%', '+0Hz'),
         'reader': ('en-GB-ThomasNeural', '-10%', '-4Hz')}
PAUSE = {'.': 0.22, '?': 0.55, '!': 0.35, ':': 0.40, ';': 0.30, ',': 0.12, '': 0.20}
PAR_GAP, CH_GAP, BEFORE_READER, AFTER_READER = 0.45, 1.0, 0.30, 0.45


def split_roles(text):
    """'a «b» c' -> [('narration','a'), ('reader','b'), ('narration','c')]"""
    out = []
    for i, part in enumerate(re.split(r'[«»]', text)):
        part = part.strip()
        if part: out.append(('reader' if i % 2 else 'narration', part))
    return out


def _sentences(par):
    parts = re.split(r'(?<=[.!?])(?<!\sB\.)(?<!\sJ\.)(?<!\sR\.)\s+(?=[A-Z«])', par.strip()); out = []
    for s in parts:
        if out and len(s.split()) < 6: out[-1] += ' ' + s
        else: out.append(s)
    return out


async def _say(text, voice, rate, pitch, f, tries=8):
    for k in range(tries):
        try:
            await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(str(f))
            if f.stat().st_size > 800: return
        except Exception:
            pass
        await asyncio.sleep(2 + 2 * k)
    raise RuntimeError('TTS fallo: ' + text[:60])


def _chunk(text, role, cache, roles):
    voice, rate, pitch = roles[role]; f = cache / ('v_' + hashlib.md5(f'{voice}{rate}{pitch}{text}'.encode()).hexdigest()[:14] + '.mp3')
    if not (f.exists() and f.stat().st_size > 800): asyncio.run(_say(text.replace('~~', '').strip(), voice, rate, pitch, f))
    return AudioSegment.from_file(str(f))


def narrate(chapters, out_dir, roles=ROLES, lead=0.6):
    out_dir = Path(out_dir); cache = out_dir / 'tts'; cache.mkdir(parents=True, exist_ok=True)
    combined = AudioSegment.silent(duration=int(lead * 1000)); t = lead; rows = []; sid = 0
    for ci, (title, paras) in enumerate(chapters):
        for pi, par in enumerate(paras):
            ss = _sentences(par)
            for si, sent in enumerate(ss):
                sid += 1; start = t; extra = 0.6 if sent.rstrip().endswith('~~') else 0.0
                chunks = split_roles(sent)
                for ki, (role, txt) in enumerate(chunks):
                    if role == 'reader' and ki > 0: combined += AudioSegment.silent(duration=int(BEFORE_READER * 1000)); t += BEFORE_READER
                    a = _chunk(txt, role, cache, roles); combined += a; t += len(a) / 1000
                    if role == 'reader' and ki < len(chunks) - 1: combined += AudioSegment.silent(duration=int(AFTER_READER * 1000)); t += AFTER_READER
                end = t; last = re.sub(r'[«»~\s]+$', '', sent)[-1:] if sent else ''
                gap = (CH_GAP if (pi == len(paras) - 1 and si == len(ss) - 1) else (PAR_GAP if si == len(ss) - 1 else PAUSE.get(last, PAUSE['']))) + extra
                combined += AudioSegment.silent(duration=int(gap * 1000)); t += gap
                rows.append(dict(id=sid, chapter=title, chapter_index=ci, par=pi, text=re.sub(r'[«»]|~~', '', sent).strip(), start=round(start, 3), end=round(end, 3),
                                 dur=round(end - start, 3), first_of_chapter=(pi == 0 and si == 0)))
    combined += AudioSegment.silent(duration=1500)
    return combined, rows
