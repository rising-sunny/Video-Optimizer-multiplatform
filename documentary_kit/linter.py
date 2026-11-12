"""Linter de documental: mide el plan de tomas ANTES de renderizar.

Cada toma = dict(kind, dur, asset=None, chapter=None). kinds:
  footage  metraje real en movimiento      photo  foto real con movimiento      doc  pagina de documento
  text     tarjeta de texto/dato/cita      anim   animacion/diagrama/3D         other  cualquier otro
Umbrales (objetivo de calidad, ajustables): ver TARGETS. Devuelve (metricas, hallazgos); cada hallazgo es (nivel, mensaje).
"""
from __future__ import annotations
from collections import Counter, defaultdict

TARGETS = {
    'real_visual_min': 0.50,      # footage + photo (+anim con material real no cuenta): >= 50 % del tiempo
    'footage_min': 0.15,          # al menos 15 % metraje en movimiento
    'text_max': 0.25,             # tarjetas de texto/citas <= 25 %
    'doc_max': 0.20,              # paginas de documento <= 20 %
    'gap_without_real_max_s': 45, # sin foto ni metraje real mas de 45 s seguidos = aburrido
    'photo_reuse_max': 3,         # una misma foto no mas de 3 veces
    'same_kind_run_max_s': 40,    # el mismo tipo de toma seguido mas de 40 s
    'avg_shot_max_s': 7.0,        # duracion media por toma
    'static_shot_max_s': 12.0,    # ninguna toma fija mas larga que esto
}
REAL = ('footage', 'photo')


def lint(shots, targets=None):
    t = dict(TARGETS, **(targets or {}))
    total = sum(s['dur'] for s in shots) or 1.0
    share = defaultdict(float)
    for s in shots:
        share[s['kind']] += s['dur']
    share = {k: v / total for k, v in share.items()}
    real = sum(share.get(k, 0) for k in REAL)
    # huecos sin material real
    gap = worst_gap = 0.0; gap_at = 0.0; clock = 0.0; gap_start = 0.0
    for s in shots:
        if s['kind'] in REAL:
            gap = 0.0
        else:
            if gap == 0.0: gap_start = clock
            gap += s['dur']
            if gap > worst_gap: worst_gap, gap_at = gap, gap_start
        clock += s['dur']
    # corridas del mismo tipo
    run = best_run = 0.0; run_kind = best_kind = None; run_start = best_start = clock = 0.0
    for s in shots:
        if s['kind'] == run_kind: run += s['dur']
        else: run_kind, run, run_start = s['kind'], s['dur'], clock
        if run > best_run: best_run, best_kind, best_start = run, run_kind, run_start
        clock += s['dur']
    reuse = Counter(s['asset'] for s in shots if s['kind'] == 'photo' and s.get('asset'))
    longest_static = max((s['dur'] for s in shots if s['kind'] in ('photo', 'doc', 'text')), default=0)
    avg = total / max(1, len(shots))
    m = dict(total_s=total, shots=len(shots), avg_shot_s=avg, share=share, real_visual=real, worst_gap_without_real_s=worst_gap, worst_gap_at_s=gap_at,
             longest_same_kind_s=best_run, longest_same_kind=best_kind, longest_same_kind_at_s=best_start, photo_reuse=dict(reuse.most_common(5)),
             longest_static_s=longest_static, distinct_photos=len(reuse))
    f = []
    def chk(ok, warn_msg, ok_msg, level='WARN'):
        f.append(('OK' if ok else level, ok_msg if ok else warn_msg))
    chk(real >= t['real_visual_min'], f"Material real (foto+metraje) = {real:.0%} del tiempo; objetivo >= {t['real_visual_min']:.0%}", f"Material real {real:.0%}")
    chk(share.get('footage', 0) >= t['footage_min'], f"Metraje en movimiento = {share.get('footage', 0):.0%}; objetivo >= {t['footage_min']:.0%}", f"Metraje {share.get('footage', 0):.0%}", 'FAIL' if share.get('footage', 0) == 0 else 'WARN')
    chk(share.get('text', 0) <= t['text_max'], f"Tarjetas de texto/citas = {share.get('text', 0):.0%}; maximo {t['text_max']:.0%}", f"Texto {share.get('text', 0):.0%}")
    chk(share.get('doc', 0) <= t['doc_max'], f"Paginas de documento = {share.get('doc', 0):.0%}; maximo {t['doc_max']:.0%}", f"Documentos {share.get('doc', 0):.0%}")
    chk(worst_gap <= t['gap_without_real_max_s'], f"Hueco sin foto ni metraje real de {worst_gap:.0f} s (desde {gap_at/60:.0f}:{gap_at%60:02.0f}); maximo {t['gap_without_real_max_s']} s", f"Peor hueco sin material real: {worst_gap:.0f} s")
    chk(best_run <= t['same_kind_run_max_s'], f"{best_kind} seguido {best_run:.0f} s (desde {best_start/60:.0f}:{best_start%60:02.0f}); maximo {t['same_kind_run_max_s']} s", f"Racha mas larga del mismo tipo: {best_run:.0f} s")
    over = {a: n for a, n in reuse.items() if n > t['photo_reuse_max']}
    chk(not over, f"Fotos repetidas mas de {t['photo_reuse_max']} veces: {over}", f"Reuso de fotos <= {t['photo_reuse_max']}")
    chk(avg <= t['avg_shot_max_s'], f"Duracion media por toma {avg:.1f} s; maximo {t['avg_shot_max_s']} s", f"Duracion media por toma {avg:.1f} s")
    chk(longest_static <= t['static_shot_max_s'], f"Toma fija de {longest_static:.0f} s; maximo {t['static_shot_max_s']} s", f"Toma fija mas larga {longest_static:.0f} s")
    return m, f


def report(shots, targets=None, title='Linter documental'):
    m, f = lint(shots, targets)
    out = [f"== {title}: {m['total_s']/60:.1f} min, {m['shots']} tomas ==",
           'Reparto por tiempo: ' + ', '.join(f"{k} {v:.0%}" for k, v in sorted(m['share'].items(), key=lambda kv: -kv[1])),
           f"Fotos distintas: {m['distinct_photos']} | mas repetidas: {m['photo_reuse']}"]
    out += [f"[{lvl:4}] {msg}" for lvl, msg in f]
    score = sum(1 for lvl, _ in f if lvl == 'OK')
    out.append(f"Puntaje: {score}/{len(f)}")
    return '\n'.join(out), m, f
