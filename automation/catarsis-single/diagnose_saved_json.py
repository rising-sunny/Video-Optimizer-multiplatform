#!/usr/bin/env python3
"""Inspect saved malformed model output without invoking providers or writing files."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re

RUNTIME = Path('/home/videoagent/video-automation/runtime')
ROOT = Path('/opt/video-agent-mcp')
CHANNEL = 'stunning-facts-of-history'


def safe(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('symlink_rejected')
    return path


def clean(text, limit=700):
    value = re.sub(r'\bsk-[A-Za-z0-9_-]+', '[hidden]', str(text))
    value = re.sub(r'(?i)Bearer\s+\S+', 'Bearer [hidden]', value)
    value = re.sub(r'https?://[^\s"<>]+', '[URL]', value)
    return value[:limit]


def bounded_parser():
    # Load only the two pure parsing functions from the installed source.
    source = safe(ROOT / 'shorts_handoff.py').read_bytes()
    tree = ast.parse(source)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('_pairs', 'parse')]
    if len(nodes) != 2:
        raise ValueError('installed_parser_shape_changed')
    space = dict(json=json, re=re)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<installed-json-parser>', 'exec'), space)
    return space


def inspect(batch):
    if not re.fullmatch(r'[a-f0-9]{32}', batch):
        raise ValueError('invalid_batch')
    folder = safe(RUNTIME / 'manual-catarsis' / batch / CHANNEL)
    ledger = safe(RUNTIME / 'deepseek-ledger/catarsis' / batch / CHANNEL)
    if not folder.is_dir() or not ledger.is_dir():
        raise ValueError('saved_batch_not_found')
    space = bounded_parser()
    rows = []
    for path in sorted(ledger.glob('invalid-handoff-*.json'))[-6:]:
        safe(path)
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError('saved_handoff_too_large')
        data = json.loads(path.read_text())
        text = data.get('provider_content', '')
        if not isinstance(text, str):
            continue
        value = text.strip()
        fence = re.fullmatch(r'```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n?```', value, re.I)
        if fence:
            value = fence[1]
        entry = dict(file=path.name, output=data.get('output'), characters=len(text),
            saved_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        try:
            json.loads(value)
            entry['strict_json'] = 'valid'
        except json.JSONDecodeError as exc:
            entry.update(strict_json='invalid', error=exc.msg, line=exc.lineno, column=exc.colno,
                context=clean(value[max(0, exc.pos-240):exc.pos+240]), ending=clean(value[-280:]))
        try:
            result, changes = space['parse'](text)
            entry.update(installed_parser='valid', syntax_repairs=changes,
                fields=list(result) if isinstance(result, dict) else type(result).__name__)
        except Exception as exc:
            entry.update(installed_parser='invalid', parser_error=clean(str(exc), 150),
                         ending=clean(value[-400:]))
            if 'duplicate_json_key' in str(exc):
                duplicates = []
                def pairs(items):
                    found = {}
                    for key, item in items:
                        if key in found:
                            duplicates.append(dict(key=clean(key, 80), identical=found[key] == item,
                                first=clean(json.dumps(found[key]), 240), second=clean(json.dumps(item), 240)))
                        found[key] = item
                    return found
                original = space['_pairs']
                try:
                    space['_pairs'] = pairs
                    space['parse'](text)
                    entry['duplicates'] = duplicates[:12]
                except Exception:
                    pass
                finally:
                    space['_pairs'] = original
        rows.append(entry)
    budget = json.loads(safe(ledger / 'budget.json').read_text())
    return dict(batch_id=batch, channel=CHANNEL, read_only=True, ai_requests=0,
        network_requests=0, files_modified=False, counts=budget.get('counts'),
        request_pending=budget.get('pending') is not None, invalid_outputs=rows,
        files_present={name:(folder/name).is_file() for name in
            ('editorial-plan.json','editorial-plan-autonomy-1.json','video.mp4','approval.json')})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch-id', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(inspect(args.batch_id), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps(dict(state='diagnostic_unavailable', error_type=type(exc).__name__,
            read_only=True, ai_requests=0, files_modified=False)))
        raise SystemExit(2)
