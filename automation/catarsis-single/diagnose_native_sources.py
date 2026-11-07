#!/usr/bin/env python3
"""Read-only comparison of source pins, live Python files and readiness hashes."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path('/opt/video-agent-mcp')
AUTOMATION = Path('/home/videoagent/video-automation')
ALLOWED = {'runner.py', 'daily_core.py', 'daily_remote.py', 'editorial.py',
           'render_adapter.py', 'music_provider.py', 'epidemic_mcp.py'}


def sha(content):
    return hashlib.sha256(content).hexdigest()


def diagnose(root=ROOT, automation=AUTOMATION):
    path = root / 'generation_worker.py'
    if path.is_symlink():
        raise RuntimeError('diagnostic_worker_symlink_rejected')
    source = path.read_bytes()
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'SOURCE_HASHES' for t in n.targets))
    pins = ast.literal_eval(node.value)
    if not isinstance(pins, dict) or not pins:
        raise RuntimeError('diagnostic_source_pins_unavailable')
    readiness_path = automation / 'runtime/production/readiness.json'
    if readiness_path.is_symlink():
        raise RuntimeError('diagnostic_readiness_symlink_rejected')
    raw = readiness_path.read_bytes()
    ready = json.loads(raw)
    approved = ready.get('code_sha256', {})
    checks = ready.get('checks', {})
    rows = []
    unsupported = len(set(pins) - ALLOWED)
    for name, expected in pins.items():
        if name not in ALLOWED:
            continue
        file = automation / name
        actual, state = None, 'missing'
        if file.is_symlink():
            state = 'symlink_not_read'
        elif file.is_file():
            actual, state = sha(file.read_bytes()), 'read'
        rows.append(dict(file=name, state=state, pinned_sha256=expected, actual_sha256=actual,
            readiness_sha256=approved.get(name), matches_pin=actual == expected,
            matches_readiness=actual is not None and actual == approved.get(name)))
    return dict(read_only=True, ai_requests=0, network_requests=0, files_modified=False,
        worker_sha256=sha(source), readiness_record_sha256=sha(raw),
        readiness_checks_passed=sum(v is True for v in checks.values()),
        readiness_checks_total=len(checks),
        readiness_all_checks_pass=bool(checks) and all(v is True for v in checks.values()),
        checked_source_files=len(rows), unsupported_source_entries=unsupported,
        all_source_files_match_readiness=bool(rows) and not unsupported and all(r['matches_readiness'] for r in rows),
        mismatches=[r for r in rows if not r['matches_pin']],
        source_files=rows)


if __name__ == '__main__':
    try:
        print(json.dumps(diagnose(), indent=2), flush=True)
    except Exception as exc:
        print(json.dumps(dict(state='diagnostic_unavailable', error_type=type(exc).__name__,
                              read_only=True, ai_requests=0, files_modified=False)), flush=True)
        raise SystemExit(2)
