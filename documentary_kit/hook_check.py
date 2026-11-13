"""Comprobacion del arranque y del empaquetado de un largo, ANTES de grabar la voz.

Basado en el laboratorio de ganchos del 2026-11-12 (~/video-projects/hooklab/FINDINGS.md):
- 83 videos "outlier" de canales pequenos del nicho (<=100k subs, >=30k vistas) frente a 328 del resto:
  mas cifras en el titulo (47 % vs 37 %), menos titulos tipo enciclopedia con ':' o '|' (39 % vs 51 %),
  miniaturas con 2-4 palabras fuertes.
- Transcripciones de 3 outliers (Buran, Isandlwana, Karluk): fecha + lugar + escala en la primera frase,
  la consecuencia o el contraste antes de los 30 s y la pregunta del titulo repetida hacia los 35 s.
- Retencion propia (5 documentales): todos pierden 40-50 % en el primer 5-10 %; los arranques poeticos o
  de contexto tecnico (Damascus, Skylab) se hunden entre el 10 % y el 30 %.
Son indicios con muestras chicas: los avisos son WARN, no bloquean. Solo es FAIL la muletilla de
presentacion en la primera frase (regla ya existente del Channel Bible).

Uso:
  python -m documentary_kit.hook_check --script ~/video-projects/X/script_data.py --title "..." [--thumb "589 DAYS"]
  python -m documentary_kit.hook_check --timings ~/video-projects/X/timings.json --title "..."
Desde codigo: report_opening(sentences, title, thumb_text=None) -> (texto, hallazgos)
  sentences = lista de (inicio_en_segundos, texto); si no hay tiempos, usar sentences_from_text(texto).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path

WORDS_PER_SECOND = 2.4          # narracion documental (~145 palabras/min); solo para estimar sin timings.json
STOP = set("""a an the of in on at to for from by with and or but is was were are be been it its this that these those
his her their they them he she we you i as into than then so not no do did does how why what who when where which
there here over under after before about just only all any some more most can could would will""".split())
NUMBER_WORDS = set("""two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen
eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred hundreds thousand thousands million millions
billion dozens dozen half""".split())
MONTHS = set('january february march april may june july august september october november december'.split())
STAKES = re.compile(r"\b(die[sd]?|dead|death|deaths|killed|kill|lost|crushed|sank|sunk|vanish(?:ed)?|disappear(?:ed)?|never|missing|"
                    r"trapped|burn(?:ed|t)?|explod(?:ed|es)|collaps(?:ed|e)|surviv(?:ed|e|ors?)|forgot(?:ten)?|secret|alive|"
                    r"crash(?:ed)?|destroy(?:ed)?|wreck(?:age|ed)?|fell|fall(?:s|ing|en)?|fire\w*|collid(?:ed|e)|only|last|warning|ignored|wrong|abandon(?:ed)?|not come home|never came home|never returned|did not return)\b", re.I)
META = re.compile(r"^\s*(this is the story of|in this video|welcome|today,? we|hey|hi everyone|let'?s talk about|"
                  r"have you ever wondered)", re.I)
WEAK_TITLE_WORDS = {'disaster', 'history', 'story', 'explained', 'documentary'}


def sentences_from_text(text: str) -> list[tuple[float, str]]:
    """Corta en frases y estima su inicio por palabras (sin timings.json)."""
    out, t = [], 0.0
    for s in re.split(r'(?<=[.!?])\s+', re.sub(r'\s+', ' ', text).strip()):
        if s:
            out.append((t, s))
            t += len(s.split()) / WORDS_PER_SECOND
    return out


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z'\-]{2,}", text.lower()) if w not in STOP and not w.isdigit()}


def _has_number(text: str) -> bool:
    return bool(re.search(r'\d', text)) or bool(set(re.findall(r'[a-z]+', text.lower())) & NUMBER_WORDS)


def _has_date(text: str) -> bool:
    return bool(re.search(r'\b(1[0-9]{3}|20[0-4][0-9])\b', text)) or bool(set(re.findall(r'[a-z]+', text.lower())) & MONTHS) \
        or bool(re.search(r'\b(\d{3,4}\s?(BC|BCE|AD))\b', text))


def _proper_nouns(sentence: str) -> int:
    words = re.findall(r"[A-Za-z][A-Za-z'\-]+", sentence)
    return sum(1 for w in words[1:] if w[0].isupper() and w.lower() not in STOP)


def check_opening(sentences: list[tuple[float, str]], title: str) -> list[tuple[str, str]]:
    f = []
    within = lambda sec: ' '.join(t for s, t in sentences if s < sec)
    first = sentences[0][1] if sentences else ''
    # 1. muletilla de presentacion en la primera frase (regla del Bible)
    if META.search(first):
        f.append(('FAIL', f'La primera frase es una presentacion ("{first[:60]}..."): abrir con la escena, no con el anuncio.'))
    # 2. ancla concreta en la primera frase: fecha, cifra o nombres propios
    anchor = _has_date(first) or _has_number(first) or _proper_nouns(first) >= 2
    f.append(('OK', 'Primera frase con ancla concreta (fecha, cifra o nombres).') if anchor else
             ('WARN', f'Primera frase sin fecha, cifra ni nombres propios ("{first[:70]}"): suena abstracta. Los outliers abren con fecha + lugar + escala.'))
    # 3. escala/cifra en los primeros 40 s
    f.append(('OK', 'Hay una cifra o escala en los primeros 40 s.') if _has_number(within(40)) else
             ('WARN', 'Ninguna cifra en los primeros 40 s (cuantas personas, cuanto tiempo, cuanto pesaba...).'))
    # 4. consecuencia/riesgo antes de los 30 s
    m = STAKES.search(within(30))
    f.append(('OK', f'Consecuencia o riesgo antes de los 30 s ("{m.group(0)}").') if m else
             ('WARN', 'No aparece la consecuencia ni lo que esta en juego antes de los 30 s (muertos, perdido, nunca, solo una vez...).'))
    # 5. la pregunta del titulo vuelve a sonar antes de ~60 s
    tw = _content_words(title)
    hit = tw & _content_words(within(60))
    share = len(hit) / max(1, len(tw))
    f.append(('OK', f'El arranque retoma el titulo ({", ".join(sorted(hit))}).') if share >= 0.5 else
             ('WARN', f'El primer minuto apenas retoma la promesa del titulo ({len(hit)}/{len(tw)} palabras clave: {", ".join(sorted(tw - hit)) or "-"}). Repetir la pregunta del titulo hacia los 35 s.'))
    return f


def check_title(title: str) -> list[tuple[str, str]]:
    f = []
    n = len(title)
    f.append(('OK', f'Titulo de {n} caracteres.') if n <= 60 else ('WARN', f'Titulo de {n} caracteres (> 60): se corta en movil.'))
    f.append(('OK', 'El titulo tiene una cifra concreta.') if re.search(r'\d', title) else
             ('WARN', 'Sin cifra en el titulo (47 % de los outliers la tiene; 37 % del resto).'))
    m = re.search(r'\s*([:|])\s*', title)
    if m and len(title[:m.start()].split()) <= 3:
        f.append(('WARN', f'Formato enciclopedia "{title[:m.start()]}{m.group(1)} ..." (39 % de los outliers usa ":" o "|"; 51 % del resto). Mejor una frase con tension.'))
    weak = WEAK_TITLE_WORDS & set(re.findall(r'[a-z]+', title.lower()))
    if weak:
        f.append(('WARN', f'Palabras genericas en el titulo ({", ".join(sorted(weak))}): aparecen menos en los outliers.'))
    return f


def check_thumbnail(text: str, title: str) -> list[tuple[str, str]]:
    words = text.split()
    f = [('OK', f'Texto de miniatura de {len(words)} palabras.') if 1 <= len(words) <= 4 else
         ('WARN', f'Texto de miniatura de {len(words)} palabras; los outliers usan 2-4.')]
    if len(_content_words(text) & _content_words(title)) >= max(2, len(_content_words(text))):
        f.append(('WARN', 'La miniatura repite el titulo: debe sumar otra idea (cifra, consecuencia), no copiarlo.'))
    return f


def report_opening(sentences, title, thumb_text=None):
    f = check_opening(sentences, title) + check_title(title) + (check_thumbnail(thumb_text, title) if thumb_text else [])
    lines = [f'== Arranque y empaquetado: "{title}" ==']
    lines += [f'[{lvl:4}] {msg}' for lvl, msg in f]
    lines.append(f"Puntaje: {sum(1 for l, _ in f if l == 'OK')}/{len(f)}" + (' — HAY FALLOS' if any(l == 'FAIL' for l, _ in f) else ''))
    return '\n'.join(lines), f


def _load_script(path: str) -> str:
    spec = importlib.util.spec_from_file_location('script_data', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    paras = [p for _, ps in mod.CHAPTERS for p in ps]
    return re.sub(r'[«»]|~~', '', ' '.join(paras))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--script'); ap.add_argument('--timings'); ap.add_argument('--text')
    ap.add_argument('--title', required=True); ap.add_argument('--thumb')
    a = ap.parse_args(argv)
    if a.timings:
        sents = [(s['start'], s['text']) for s in json.loads(Path(a.timings).read_text())['sentences']]
    elif a.script:
        sents = sentences_from_text(_load_script(a.script))
    elif a.text:
        sents = sentences_from_text(a.text)
    else:
        ap.error('falta --script, --timings o --text')
    text, f = report_opening(sents, a.title, a.thumb)
    print(text)
    return 1 if any(l == 'FAIL' for l, _ in f) else 0


if __name__ == '__main__':
    raise SystemExit(main())
