"""YouTube Studio CSV autopsy and pilot comparisons (offline, no publishing)."""
import argparse
import csv
import json
import math
from pathlib import Path

from micro_documentary import METRICS, write_json

BASELINE = {"videos": 26, "views": 360, "watch_hours": 8.3256, "impressions": 13517,
            "ctr_percent": 2.0624, "average_percentage_viewed": 35.8361,
            "source": "User-provided brief, 2026-09-08; underlying exports not independently verified"}
ALIASES = {
    'title': ['Video title', 'Título del vídeo', 'Título del video'],
    'youtube_video_id': ['Video', 'Content', 'Contenido'],
    'duration_seconds': ['Duration', 'Duración'],
    'views': ['Views', 'Visualizaciones'],
    'watch_hours': ['Watch time (hours)', 'Tiempo de visualización (horas)'],
    'impressions': ['Impressions', 'Impresiones'],
    'ctr_percent': ['Impressions click-through rate (%)', 'Porcentaje de clics de las impresiones (%)'],
    'average_view_duration_seconds': ['Average view duration', 'Duración media de las visualizaciones'],
    'average_percentage_viewed': ['Average percentage viewed (%)', 'Porcentaje medio visto (%)'],
}


def number(value):
    if value is None or str(value).strip() in ('', '-', '—'):
        return None
    text = str(value).strip().replace('%', '').replace('\u00a0', '').replace(' ', '')
    if ':' in text:
        parts = [float(p) for p in text.split(':')]
        return sum(v * 60 ** i for i, v in enumerate(reversed(parts)))
    if ',' in text and '.' in text:
        text = text.replace(',', '') if text.rfind('.') > text.rfind(',') else text.replace('.', '').replace(',', '.')
    elif ',' in text:
        text = text.replace(',', '.')
    value = float(text)
    if not math.isfinite(value) or value < 0:
        raise ValueError('Metrics must be finite and nonnegative')
    return value


def normalize(row):
    result = {}
    for key in set(ALIASES) | set(METRICS):
        value = next((row[k] for k in [key] + ALIASES.get(key, []) if k in row), None)
        result[key] = value if key in ('title', 'youtube_video_id') else number(value)
        if key.endswith('_percent') or key == 'average_percentage_viewed':
            if result[key] is not None and result[key] > 100:
                raise ValueError(f'{key} must be between 0 and 100')
    return result


def diagnose(row):
    ctr, retention = row.get('ctr_percent'), row.get('average_percentage_viewed')
    impressions, views = row.get('impressions'), row.get('views')
    notes = ['Average percentage viewed cannot locate a first-10-second drop.']
    small = impressions is None or views is None or impressions < 1000 or views < 100
    if small:
        notes.append('Small or missing sample: tentative diagnosis; no binary success/failure conclusion.')
    if ctr is None or retention is None:
        diagnosis = 'insufficient_evidence'
    elif ctr < 4 and retention >= 45:
        diagnosis = 'packaging_candidate'
    elif ctr < 4 and 30 <= retention < 45:
        diagnosis = 'packaging_candidate_retention_intermediate'
        notes.append('Consumption is intermediate; this does not establish a story/opening failure.')
    elif ctr >= 4 and retention < 30:
        diagnosis = 'story_content_candidate'
    elif ctr < 4 and retention < 30:
        diagnosis = 'packaging_and_content_candidates'
    elif retention < 45:
        diagnosis = 'retention_intermediate_needs_more_evidence'
    else:
        diagnosis = 'topic_audience_distribution_candidate' if impressions is not None and impressions < 1000 else 'promising_requires_impression_history'
        notes.append('A single cumulative snapshot cannot prove expanding impressions.')
    return {"diagnosis": diagnosis, "tentative": small, "notes": notes,
            "baseline_delta_percentage_points": {k: row[k] - BASELINE[k] if row.get(k) is not None else None for k in ('ctr_percent', 'average_percentage_viewed')},
            "pilot_heuristics": {"ctr_4_percent": ctr >= 4 if ctr is not None else None,
                                 "retention_30s_65_percent": row['retention_30s_percent'] >= 65 if row.get('retention_30s_percent') is not None else None,
                                 "average_viewed_45_percent": retention >= 45 if retention is not None else None}}


def compare_pilots(manifests):
    comparisons = []
    previous = None
    for manifest in manifests:
        metrics = manifest.get('metrics', {})
        history = manifest.get('metric_history', [])
        impression_delta = None
        if len(history) >= 2:
            latest = history[-1]['metrics'].get('impressions')
            earlier = history[-2]['metrics'].get('impressions')
            if latest is not None and earlier is not None:
                impression_delta = latest - earlier
        comparisons.append({'experiment_id': manifest['experiment_id'], 'diagnostic': diagnose(metrics),
                            'impression_change_since_previous_snapshot': impression_delta,
                            'delta_from_previous_pilot': {k: metrics[k] - previous[k] if previous and previous.get(k) is not None and metrics.get(k) is not None else None for k in ('ctr_percent', 'average_percentage_viewed', 'watch_hours')}})
        previous = metrics
    count = len(manifests)
    recommendation = 'Complete the first batch of three; no automatic scaling.' if count < 3 else 'Review the first three and adjust packaging/opening before the next three.' if count < 6 else 'Review six optimized pilots before deciding whether to scale or park; small samples remain inconclusive.'
    return {'order': 'Manifests in supplied command-line order', 'pilots': comparisons, 'next_step': recommendation}


def report(rows, out, manifests=None):
    results = [{**row, **diagnose(row)} for row in rows]
    data = {"baseline": BASELINE, "heuristics_notice": "Experiment heuristics, not official YouTube thresholds. Aggregate CTR is not Browse/Suggested CTR.", "videos": results}
    if manifests:
        data['pilot_comparison'] = compare_pilots(manifests)
    write_json(Path(out).with_suffix('.json'), data)
    lines = ['# Microdocumentary autopsy', '', data['heuristics_notice'], '', BASELINE['source'], '',
             '| Video | Views | CTR % | Avg viewed % | Diagnosis |', '|---|---:|---:|---:|---|']
    for r in results:
        title = str(r.get('title') or r.get('youtube_video_id') or 'Unknown').replace('|', '\\|')
        lines.append(f"| {title} | {r.get('views')} | {r.get('ctr_percent')} | {r.get('average_percentage_viewed')} | {r['diagnosis']} |")
    lines.extend(['', 'All diagnoses are hypotheses. Small samples limit confidence; average viewed does not reveal where viewers left. Impression expansion requires dated observations.'])
    if manifests:
        lines.extend(['', data['pilot_comparison']['next_step'], '', 'Pilot comparisons (supplied order):', ''])
        for pilot in data['pilot_comparison']['pilots']:
            lines.append(f"- {pilot['experiment_id']}: previous-pilot deltas {pilot['delta_from_previous_pilot']}; impressions since last snapshot {pilot['impression_change_since_previous_snapshot']}")
    Path(out).with_suffix('.md').write_text('\n'.join(lines), encoding='utf-8')
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv_file')
    parser.add_argument('--output', default='microdoc_autopsy')
    parser.add_argument('--all-durations', action='store_true', help='Include new pilots outside the old 181–300s cohort')
    parser.add_argument('--manifest', action='append', default=[], help='Update pilot by exact youtube_video_id; repeat to compare pilots')
    args = parser.parse_args(argv)
    with open(args.csv_file, encoding='utf-8-sig', newline='') as handle:
        sample = handle.read(8192)
        handle.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
        rows = [normalize(r) for r in csv.DictReader(handle, dialect=dialect)]
    rows = [r for r in rows if r.get('title') and r['title'].lower() not in ('total', 'totals')]
    manifests = []
    for filename in args.manifest:
        manifest = json.loads(Path(filename).read_text(encoding='utf-8'))
        video_id = manifest.get('youtube_video_id')
        matches = [r for r in rows if video_id and r.get('youtube_video_id') == video_id]
        if len(matches) != 1:
            raise ValueError(f'{filename}: expected one exact video ID match; record youtube_video_id first')
        row = matches[0]
        manifest.setdefault('metrics', {}).update({k: row[k] for k in METRICS if row.get(k) is not None})
        from datetime import datetime, timezone
        manifest.setdefault('metric_history', []).append({'recorded_at': datetime.now(timezone.utc).isoformat(), 'metrics': dict(manifest['metrics'])})
        manifest['diagnostic'] = diagnose(manifest['metrics'])
        write_json(filename, manifest)
        manifests.append(manifest)
    selected = rows if args.all_durations else [r for r in rows if r.get('duration_seconds') is not None and 181 <= r['duration_seconds'] <= 300]
    report(selected, args.output, manifests)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
