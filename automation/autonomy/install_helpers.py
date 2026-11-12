#!/usr/bin/env python3
"""Install one-channel selection, preserving the native supervised engine."""
import ast
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess
import tempfile
import time

import patch_sources

BUNDLE = Path(__file__).resolve().parent
ROOT = Path('/opt/video-agent-mcp')
REPO = Path('/home/videoagent/Video-Optimizer-multiplatform')
PYTHON = str(REPO / '.venv/bin/python')
RECEIPT = ROOT / 'single-catarsis-v48-installed.json'
TARGETS = ('generation_service.py', 'generation_worker.py', 'documentary_service.py')
EXTRAS = ('catarsis_selection.py', 'single_catarsis_request.py', 'curie-request.json')


def digest(value):
    return hashlib.sha256(value).hexdigest()


def safe(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise RuntimeError('single_install_symlink_rejected')
    return path


def atomic(path, value, mode=0o644, owner=None):
    path = safe(path)
    missing = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for parent in reversed(missing):
        safe(parent).mkdir(mode=0o755)
        parent.chmod(0o755)
        if owner is not None:
            os.chown(parent, *owner)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.single-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            if owner is not None:
                os.fchown(stream.fileno(), *owner)
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def command(args, timeout=90, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, **kwargs)
    if result.returncode:
        print((result.stdout + result.stderr)[-6500:], flush=True)
        raise RuntimeError('single_install_subprocess_failed')
    return result.stdout.strip()


def rpc(operation):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(40)
        connection.connect('/run/video-agent-prepare/control.sock')
        connection.sendall(json.dumps(dict(operation=operation)).encode() + b'\n')
        with connection.makefile('rb') as stream:
            return json.loads(stream.readline(1048577))


def idle():
    if rpc('manual_activity').get('state') != 'idle':
        raise RuntimeError('single_install_manual_work_in_progress')
    if rpc('result_today').get('state') in ('accepted', 'running', 'unavailable'):
        raise RuntimeError('single_install_daily_work_in_progress')


def controls():
    paused = safe(Path('/home/videoagent/video-automation/runtime/production/PAUSED'))
    if not paused.is_file():
        raise RuntimeError('single_install_daily_pause_required')
    timers = command(['systemctl', 'show', 'video-shorts-prepare.timer', 'video-shorts-publish.timer',
                      '-p', 'ActiveState', '-p', 'UnitFileState'])
    return digest(paused.read_bytes()), paused.stat().st_mtime_ns, timers


def candidate_sources(originals, installed):
    result = {}
    for name, content in originals.items():
        if installed and digest(content) == installed.get('after', {}).get(name):
            result[name] = content
        else:
            result[name] = getattr(patch_sources, Path(name).stem)(content.decode()).encode()
        ast.parse(result[name])
    return result


def check_candidate(candidate, originals):
    directory = Path(tempfile.mkdtemp(prefix='single-catarsis-tests-'))
    directory.chmod(0o755)
    for source in BUNDLE.rglob('*'):
        relative = source.relative_to(BUNDLE)
        if '__pycache__' in relative.parts:
            continue
        destination = directory / relative
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            destination.chmod(0o755)
        elif source.is_file():
            atomic(destination, source.read_bytes())
    for name, content in candidate.items():
        atomic(directory / 'native' / name, content)
    # Test preservation against the ACTUAL pre-install worker, not an older copy.
    atomic(directory / 'baseline/generation_worker.py', originals['generation_worker.py'])
    env = dict(os.environ, PYTHONPATH=str(directory) + ':' + str(ROOT), PYTHONDONTWRITEBYTECODE='1')
    result = subprocess.run(['runuser', '-u', 'videoagent', '--', 'env',
        'PYTHONPATH=' + env['PYTHONPATH'], 'PYTHONDONTWRITEBYTECODE=1', PYTHON, '-B', '-m', 'unittest',
        'discover', '-s', str(directory), '-p', 'test_single_catarsis.py', '-q'],
        capture_output=True, text=True, timeout=90, env=env, cwd=directory)
    if result.returncode:
        print((result.stdout + result.stderr)[-6500:], flush=True)
        raise RuntimeError('single_channel_offline_tests_failed')
    print(json.dumps(dict(single_channel_tests='passed', ai_requests=0)), flush=True)


def main():
    if os.geteuid() != 0:
        raise RuntimeError('single_install_root_required')
    os.umask(0o077)
    payload = json.loads((BUNDLE / 'payload-sha256.json').read_text())
    for name, expected in payload.items():
        if digest(safe(BUNDLE / name).read_bytes()) != expected:
            raise RuntimeError('single_delivery_hash_changed')
    originals = {name: safe(ROOT / name).read_bytes() for name in TARGETS}
    installed = json.loads(safe(RECEIPT).read_text()) if RECEIPT.is_file() else {}
    candidate = candidate_sources(originals, installed)
    extras = {name: (BUNDLE / name).read_bytes() for name in EXTRAS}
    for name in extras:
        path = safe(ROOT / name)
        if path.exists() and path.read_bytes() != extras[name]:
            raise RuntimeError('single_existing_helper_changed')
    with Path('/run/lock/video-generation-install.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = controls()
        idle()
        print(command(['runuser', '-u', 'videoagent', '--', PYTHON, '-B',
            str(BUNDLE / 'single_catarsis_request.py'), '--check',
            '--request-file', str(BUNDLE / 'curie-request.json')]), flush=True)
        check_candidate(candidate, originals)
        idle()
        changed = any(candidate[n] != originals[n] for n in TARGETS) or not all((ROOT/n).exists() for n in EXTRAS)
        backup = None
        if changed:
            backup = Path('/var/backups/video-agent-mcp') / ('single-catarsis-v48-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
            backup.mkdir(mode=0o700)
            for name, data in originals.items():
                atomic(backup / name, data, 0o600)
            present = {name: (ROOT/name).exists() for name in EXTRAS}
            try:
                for name, data in extras.items():
                    atomic(ROOT / name, data)
                for name, data in candidate.items():
                    atomic(ROOT / name, data)
                command(['systemctl', 'restart', 'video-agent-prepare.service'])
                for _ in range(80):
                    try:
                        if rpc('manual_activity').get('state') == 'idle':
                            break
                    except (OSError, ValueError):
                        pass
                    time.sleep(.25)
                else:
                    raise RuntimeError('single_prepare_service_not_ready')
                if controls() != before:
                    raise RuntimeError('single_install_daily_controls_changed')
            except Exception:
                for name, data in originals.items():
                    atomic(ROOT / name, data)
                for name, existed in present.items():
                    if not existed:
                        (ROOT/name).unlink(missing_ok=True)
                command(['systemctl', 'restart', 'video-agent-prepare.service'])
                raise
        receipt = dict(release='single-channel-catarsis-v48', after={n:digest(v) for n,v in candidate.items()},
            backup=str(backup) if backup else installed.get('backup'), install_ai_requests=0,
            generation_scope='one_selected_channel', daily_timers_modified=False, publication='not_requested')
        # Persist the installation binding before optional repository mirroring:
        # a later I/O failure must not make a rerun attempt the source patch twice.
        atomic(RECEIPT, json.dumps(receipt, indent=2).encode())
        # Persist readable copies and provenance alongside the repository's other corrections.
        saved = REPO / 'automation/catarsis-single'
        who = pwd.getpwnam('videoagent')
        owner = (who.pw_uid, who.pw_gid)
        for name in ('catarsis_selection.py', 'single_catarsis_request.py', 'patch_sources.py',
                     'curie-request.json', 'README.md', 'test_single_catarsis.py', 'vidiq-research.json'):
            atomic(saved / name, (BUNDLE / name).read_bytes(), owner=owner)
        for name, data in candidate.items():
            atomic(saved / 'native' / name, data, owner=owner)
        atomic(saved / 'installed-source-receipt.json', json.dumps(receipt, indent=2).encode(), owner=owner)
        agents = safe(REPO / 'AGENTS.md')
        marker = '## Single-channel Catarsis (v48)'
        content = agents.read_text() if agents.exists() else '# Video Automation\n'
        if marker not in content:
            content = content.rstrip() + '\n\n' + marker + '\n\n' + (
                'For a request covering only one channel, use `automation/catarsis-single/README.md` '
                'and `/opt/video-agent-mcp/single_catarsis_request.py`. Do not use the pair '
                'generation/publication tools for a one-channel request. The existing generation '
                'status tool can read single batches; the unselected channel is not_requested.\n')
            atomic(agents, content.encode(), owner=owner)
        print(json.dumps(dict(status='installed' if changed else 'already_installed', **receipt)), flush=True)
        # Only now submit the exact, stable, explicitly requested single generation.
        print(command(['runuser', '-u', 'videoagent', '--', PYTHON, '-B',
            str(ROOT / 'single_catarsis_request.py'), '--request-file', str(ROOT / 'curie-request.json'),
            '--start']), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        value = str(exc)
        code = value if value.replace('_', '').isalnum() else type(exc).__name__
        print(json.dumps(dict(status='blocked', reason=code, publication_allowed=False)), flush=True)
        raise SystemExit(2)
