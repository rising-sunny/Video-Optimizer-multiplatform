"""Buscador de METRAJE de archivo con evidencia de derechos. SOLO descubre y puntua: nunca aprueba ni descarga solo.

Fuentes: Internet Archive (colecciones de gobierno de EE. UU. y Prelinger), Wikimedia Commons (videos). Cada candidato trae `rights`:
  pd_gov   producido por una agencia federal de EE. UU. o en coleccion federal  -> dominio publico (verificar el item igualmente)
  pd_claim declarado dominio publico/CC0 en los metadatos, sin ser federal       -> revisar a mano
  check    sin declaracion de derechos                                           -> NO usar sin verificar
  no       licencia restrictiva (NC/ND/SA/copyright)                              -> descartar
Uso: python -m documentary_kit.footage_finder "texas city explosion" "port fire 1940s" --max 8 [--json out.json]
"""
from __future__ import annotations
import argparse, json, re, time
import requests

UA = {'User-Agent': 'StunningRevelationsResearch/1.0 (estudio documental)'}
IA_ADV = 'https://archive.org/advancedsearch.php'
GOV_COLLECTIONS = {'fedflix', 'nasa', 'usarmy', 'us_army', 'navy', 'us_navy', 'nationalarchives', 'usgovernment', 'universal_newsreels', 'ntis', 'coast_guard', 'uscg'}
GOV_CREATORS = re.compile(r'(u\.?s\.? (army|navy|air force|coast guard|government)|signal corps|national archives|nara|nasa|department of (defense|agriculture|the interior|commerce)|tennessee valley authority|office of war information|war department|usgs|geological survey|noaa|forest service|national park service|library of congress|department of energy|atomic energy commission|johnson space center|jsc|marshall space flight)', re.I)
BAD_LIC = re.compile(r'(-nc|-nd|/by-sa|all rights reserved)', re.I)


TIER = {'pd_gov': 'A', 'pd_claim': 'A-', 'open_license': 'B', 'check': 'C', 'no': 'D'}


def classify(md: dict) -> tuple[str, str]:
    lic = (md.get('licenseurl') or '').lower(); rights = (md.get('rights') or '').lower(); status = (md.get('possible-copyright-status') or '').lower()
    cols = md.get('collection') or []; cols = cols if isinstance(cols, list) else [cols]
    creator = ' '.join(md.get('creator') if isinstance(md.get('creator'), list) else [md.get('creator') or ''])
    if BAD_LIC.search(lic) or 'copyright' in rights and 'public' not in rights: return 'no', f'licencia restrictiva: {lic or rights}'
    if set(map(str.lower, cols)) & GOV_COLLECTIONS or GOV_CREATORS.search(creator): return 'pd_gov', f'coleccion/productor federal: {creator or cols}'
    if 'publicdomain' in lic or 'public domain' in rights or status.startswith('not_in_copyright') or 'cc0' in lic: return 'pd_claim', f'declarado: {lic or rights or status}'
    if re.search(r'creativecommons.org/licenses/by/', lic): return 'open_license', f'CC BY (requiere credito): {lic}'
    yr = re.search(r'(19\d\d)', str(md.get('date') or md.get('year') or ''))
    if yr and 1928 <= int(yr.group(1)) <= 1963: return 'check', 'sin declaracion; obra de EE. UU. 1928-1963: puede ser dominio publico por falta de renovacion o donacion al gobierno (verificar: Catalog of Copyright Entries / base de renovaciones de Stanford / catalogo NARA)'
    return 'check', 'sin declaracion de derechos'


def ia_search(query, max_results=8):
    q = f'({query}) AND mediatype:movies'
    d = requests.get(IA_ADV, params={'q': q, 'fl[]': ['identifier', 'title', 'date', 'downloads'], 'rows': max_results * 3, 'sort[]': 'downloads desc', 'output': 'json'}, headers=UA, timeout=60).json()['response']['docs']
    out = []
    for x in d[:max_results * 2]:
        try:
            m = requests.get(f"https://archive.org/metadata/{x['identifier']}", headers=UA, timeout=60).json()
        except Exception:
            continue
        md = m.get('metadata', {}); verdict, why = classify(md)
        files = [f for f in m.get('files', []) if f.get('format') in ('h.264', 'MPEG4', '512Kb MPEG4', 'h.264 IA')]
        out.append(dict(source='internet_archive', id=x['identifier'], title=md.get('title', ''), year=str(md.get('date', ''))[:4], creator=str(md.get('creator', ''))[:60],
                        collections=md.get('collection'), runtime=md.get('runtime'), rights=verdict, tier=TIER[verdict], rights_note=why, url=f"https://archive.org/details/{x['identifier']}",
                        file=(files[0]['name'] if files else None), size_mb=round(int(files[0].get('size', 0)) / 1e6, 1) if files else None))
        time.sleep(0.5)
        if len(out) >= max_results: break
    return out


def commons_search(query, max_results=6):
    p = dict(action='query', generator='search', gsrsearch=f'{query} filetype:video', gsrnamespace=6, gsrlimit=max_results, prop='imageinfo', iiprop='url|size|mime|extmetadata', format='json')
    r = requests.get('https://commons.wikimedia.org/w/api.php', params=p, headers=UA, timeout=60)
    if not r.text.startswith('{'): return []
    out = []
    for pg in (r.json().get('query', {}).get('pages', {}) or {}).values():
        ii = (pg.get('imageinfo') or [{}])[0]; lic = (ii.get('extmetadata', {}).get('LicenseShortName', {}).get('value') or '')
        v = 'pd_claim' if re.match(r'(public domain|pd|cc0)', lic, re.I) else ('check' if not lic else 'no')
        out.append(dict(source='commons', id=pg['title'], title=pg['title'][5:], rights=v, rights_note=lic, url='https://commons.wikimedia.org/wiki/' + pg['title'].replace(' ', '_'), file=ii.get('url')))
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('queries', nargs='+'); ap.add_argument('--max', type=int, default=6); ap.add_argument('--json'); a = ap.parse_args()
    allr = []
    for q in a.queries:
        print(f'\n## {q}')
        for fn in (ia_search, commons_search):
            try: res = fn(q, a.max)
            except Exception as e: print('  error', fn.__name__, str(e)[:80]); continue
            for r in res:
                allr.append(dict(r, query=q)); print(f"  [{r['rights']:8}] {r['source'][:6]:6} {r['title'][:62]:62} {r.get('year', ''):4} {r['url']}")
    if a.json: json.dump(allr, open(a.json, 'w'), indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
