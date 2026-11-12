"""Explorador de temas para largos: demanda (YouTube Data API), competencia pequena exitosa (views/subs) y disponibilidad de METRAJE de dominio publico.
Sustituto parcial de vidIQ outliers cuando no hay creditos. Cuota: ~102 unidades por tema (search.list 100 + videos.list + channels.list).
Uso: python -m documentary_kit.topic_scout "Castle Bravo 1954" "USS Forrestal fire 1967" [--json out.json] [--no-footage]"""
from __future__ import annotations
import argparse, json, statistics, sys, re
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/home/videoagent/Video-Optimizer-multiplatform')


STOP = {'fire', 'test', 'nuclear', 'documentary', 'disaster', 'bombs', 'hydrogen', 'explosion', 'accident', 'crash'}


def dur_min(d):
    m = re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', d or ''); h, mi, s = (int(x or 0) for x in m.groups()); return h * 60 + mi + s / 60


def scout_topic(yt, topic, own_ids=frozenset(), footage=True, n=10):
    after = (datetime.now(timezone.utc) - timedelta(days=365)).strftime('%Y-%m-%dT%H:%M:%SZ')
    r = yt.search().list(part='id', q=topic + ' documentary', type='video', videoDuration='long', order='viewCount', publishedAfter=after, maxResults=n, relevanceLanguage='en').execute()
    ids = [i['id']['videoId'] for i in r.get('items', [])]
    if not ids: return dict(topic=topic, videos=0)
    vs = yt.videos().list(part='snippet,statistics,contentDetails', id=','.join(ids)).execute()['items']
    chs = yt.channels().list(part='statistics', id=','.join({v['snippet']['channelId'] for v in vs})).execute()['items']
    subs = {c['id']: int(c['statistics'].get('subscriberCount', 0) or 0) for c in chs}
    rows = []
    for v in vs:
        views = int(v['statistics'].get('viewCount', 0)); sb = subs.get(v['snippet']['channelId'], 0)
        rows.append(dict(title=v['snippet']['title'][:70], channel=v['snippet']['channelTitle'][:26], views=views, subs=sb, ratio=round(views / max(sb, 1), 1), mins=round(dur_min(v['contentDetails']['duration']), 1), id=v['id']))
    small_wins = [x for x in rows if x['subs'] and x['subs'] < 100_000 and x['views'] >= 50_000]
    out = dict(topic=topic, videos=len(rows), median_views=int(statistics.median(x['views'] for x in rows)), top_views=max(x['views'] for x in rows),
               small_channel_wins=len(small_wins), best_small=sorted(small_wins, key=lambda x: -x['ratio'])[:2], saturated=sum(1 for x in rows if x['views'] >= 500_000),
               median_minutes=round(statistics.median(x['mins'] for x in rows), 1), already_ours=[x['title'] for x in rows if x['id'] in own_ids])
    if footage:
        from documentary_kit.footage_finder import ia_search
        try:
            toks = [w for w in re.findall(r'[a-z0-9]+', topic.lower()) if len(w) >= 4 and w not in STOP]
            c = [x for x in ia_search(topic, 8) if any(w in (x['title'] or '').lower() for w in toks)]       # relevancia: el titulo menciona el tema
            out['footage_pd'] = sum(1 for x in c if x['rights'] in ('pd_gov', 'pd_claim')); out['footage_check'] = sum(1 for x in c if x['rights'] == 'check')
            out['footage_examples'] = [f"{x['title'][:45]} [{x['rights']}]" for x in c if x['rights'] in ('pd_gov', 'pd_claim')][:3]
        except Exception as e:
            out['footage_error'] = str(e)[:60]
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('topics', nargs='+'); ap.add_argument('--json'); ap.add_argument('--no-footage', action='store_true'); a = ap.parse_args()
    from dotenv import load_dotenv; load_dotenv('/home/videoagent/Video-Optimizer-multiplatform/.env')
    from publish.youtube_uploader import get_youtube_service
    yt = get_youtube_service(interactive=False, channel_profile='stunning-revelations')
    up = yt.channels().list(part='contentDetails', mine=True).execute()['items'][0]['contentDetails']['relatedPlaylists']['uploads']
    own = {i['snippet']['resourceId']['videoId'] for i in yt.playlistItems().list(part='snippet', playlistId=up, maxResults=50).execute()['items']}
    res = []
    for t in a.topics:
        try: r = scout_topic(yt, t, own, not a.no_footage)
        except Exception as e: r = dict(topic=t, error=str(e)[:100])
        res.append(r); print(json.dumps({k: v for k, v in r.items() if k != 'best_small'}, ensure_ascii=False)); 
        for b in r.get('best_small', []): print(f"     ganador pequeno: {b['title']} | {b['channel']} ({b['subs']:,} subs) {b['views']:,} vistas, {b['mins']} min")
    if a.json: json.dump(res, open(a.json, 'w'), indent=1, ensure_ascii=False)


if __name__ == '__main__':
    main()
