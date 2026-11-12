"""Registro de derechos por video: CADA clip de metraje usado queda anotado con fuente, nivel, evidencia y quien lo aprobo.
Niveles: A (federal, dominio publico) | A- (declarado dominio publico: mirar el item) | B (licencia abierta, con credito) |
         C (sin derechos claros: SOLO con evidencia nueva o aprobacion expresa del usuario por clip, bajo uso justo) | D (restrictivo: no usar).
Uso justo (nivel C): defensa legal que se juzga caso por caso, NO un permiso previo; no evita reclamos de Content ID ni avisos DMCA. Reglas de control:
clips cortos (<= ~12 s), contexto critico/narrado que los transforme, sin reemplazar el original, con credito, sin 'ripear' de YouTube (violaria sus condiciones).
Archivo: <proyecto>/rights_ledger.json. Un video NO se sube si tiene clips C/D sin 'approved_by'."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path


def _load(project):
    f = Path(project) / 'rights_ledger.json'
    return f, (json.loads(f.read_text()) if f.exists() else {'clips': []})


def add_clip(project, clip_id, title, source_url, tier, evidence, seconds_used=None, used_at=None, approved_by=None, note=''):
    f, d = _load(project)
    d['clips'] = [c for c in d['clips'] if c['id'] != clip_id]
    d['clips'].append(dict(id=clip_id, title=title, source_url=source_url, tier=tier, evidence=evidence, seconds_used=seconds_used, used_at=used_at, note=note,
                           approved_by=approved_by, recorded=datetime.now(timezone.utc).isoformat(timespec='seconds')))
    f.write_text(json.dumps(d, indent=1, ensure_ascii=False)); return d


def check(project):
    """Devuelve (ok, problemas). C/D sin aprobacion expresa bloquean la subida; fair use con clip > 12 s se avisa."""
    _, d = _load(project); bad = []
    for c in d['clips']:
        if c['tier'] == 'D': bad.append(f"{c['id']}: nivel D (no usar)")
        if c['tier'] == 'C' and not c.get('approved_by'): bad.append(f"{c['id']}: nivel C sin aprobacion expresa del usuario")
        if c['tier'] == 'C' and (c.get('seconds_used') or 0) > 12: bad.append(f"{c['id']}: uso justo con {c['seconds_used']} s (> 12 s): reducir o buscar licencia")
    return (not bad), bad
