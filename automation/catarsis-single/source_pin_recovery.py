#!/usr/bin/env python3
"""Bind the four observed stale pins to the already approved source snapshot.

This is an exact migration, not an automatic trust/refresh mechanism. Neither
the approved readiness record nor any automation source is modified.
"""
import ast
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess

import install as single

OBSERVED_WORKER = '24cdd6e83fc8e58a4ff8315eef5c10f003c21e3cba88c5e9c64d8bddcb3d23c3'
OBSERVED_READINESS = 'a84e0b75dca2d174c05faaa6235c2fe5d57c9395cd06484b09cbb76ab469cc56'
UPDATES = {
    'runner.py': ('d4974f7dccc1d000b487c23536c9c28f1a52ca0d6d08cc9e6a2cdd4229c01fb9',
                  '3746cb10296bdff378d1ab026be1102795052c6ab450187bd71c039bdf73d9e2'),
    'daily_core.py': ('5bcce24ba8286ead02da624bbc787006d013426e05915846e2ecb4ef6c0fc8db',
                      '896a24a21c67966f3cb889c776b6a238a7b3be3eb2fd7719f4565d7c56d5907b'),
    'daily_remote.py': ('ac648361e637df05ab2855fb332b0edf372c648942046a56bfafb8eb8b68d2be',
                        'd0edd530d9929d516f3f2c96079daf4245cacbc144e3c39eebaa9eea5e196a51'),
    'editorial.py': ('265250416c916fd4bc513185a1fbcda000ad1a4b15049144bc2f8b0cd0a4350e',
                     'f09de5bf5817611dbb802f02e65af7f4a733a4a2c5ce58039a905e0309b012ec'),
}
EXPECTED_FILES = {name: pair[1] for name, pair in UPDATES.items()}
EXPECTED_FILES.update({
    'render_adapter.py': '3f88cff95be05f808796d1361b78fcc22c7a3b20b9f6d6ee8a8cb1b31c9d41bf',
    'music_provider.py': '8f7cf5719f0494186ac27eea5bc81eb60077159c4346246a7c323bd01a53ce13',
    'epidemic_mcp.py': 'd0e28e4bd91a0d10e8dab9f77c7c1fd10a2dc587ae6128c23400a814c7c2f699',
})
BACKUPS = Path('/var/backups/video-agent-mcp')
READINESS = Path('/home/videoagent/video-automation/runtime/production/readiness.json')
LOCK = Path('/run/lock/video-generation-install.lock')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def repin(source):
    if digest(source) != OBSERVED_WORKER:
        raise RuntimeError('source_pin_worker_not_observed')
    text = source.decode()
    tree = ast.parse(text)
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == 'SOURCE_HASHES' for t in n.targets))
    pins = ast.literal_eval(node.value)
    if set(pins) != set(EXPECTED_FILES):
        raise RuntimeError('source_pin_set_changed')
    for name, (old, new) in UPDATES.items():
        if pins.get(name) != old or text.count(old) != 1:
            raise RuntimeError('source_pin_old_value_changed')
        text = text.replace(old, new, 1)
    result = text.encode()
    ast.parse(result)
    return result


def known_sources():
    original = single.safe(single.BUNDLE / 'baseline/generation_worker.py').read_bytes()
    corrected = repin(original)
    final = single.patch_sources.generation_worker(corrected.decode()).encode()
    return original, corrected, final


def verify_files():
    readiness = single.safe(READINESS)
    raw = readiness.read_bytes()
    if digest(raw) != OBSERVED_READINESS:
        raise RuntimeError('source_pin_readiness_not_observed')
    ready = json.loads(raw)
    checks = ready.get('checks')
    if not isinstance(checks, dict) or len(checks) != 36 or not all(v is True for v in checks.values()):
        raise RuntimeError('source_pin_readiness_checks_failed')
    hashes = ready.get('code_sha256')
    if not isinstance(hashes, dict):
        raise RuntimeError('source_pin_readiness_hashes_missing')
    automation = readiness.parents[2]
    for name, expected in EXPECTED_FILES.items():
        path = single.safe(automation / name)
        if hashes.get(name) != expected or digest(path.read_bytes()) != expected:
            raise RuntimeError('source_pin_approved_source_changed')
    return digest(raw)


def native_check():
    # New process, actual installed module, original native preflight. No model calls.
    code = "import sys;sys.path.insert(0,'/opt/video-agent-mcp');from generation_worker import preflight;preflight()"
    result = subprocess.run(['runuser', '-u', 'videoagent', '--', single.PYTHON,
        '-B', '-c', code], capture_output=True, text=True, timeout=45)
    if result.returncode:
        raise RuntimeError('source_pin_native_preflight_failed')


def repair():
    if os.geteuid() != 0:
        raise RuntimeError('source_pin_root_required')
    original, corrected, final = known_sources()
    path = single.safe(single.ROOT / 'generation_worker.py')
    with single.safe(LOCK).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        single.idle()
        before_controls = single.controls()
        verify_files()
        current = path.read_bytes()
        if current not in (original, corrected, final):
            raise RuntimeError('source_pin_worker_not_observed')
        changed = current == original
        backup = None
        if changed:
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup = single.safe(BACKUPS / ('source-pins-v48-1-' + stamp))
            backup.mkdir(mode=0o700)
            single.atomic(backup / 'generation_worker.py', current, 0o600)
            # Recheck the approved snapshot immediately before the only code write.
            verify_files()
            single.idle()
            mode = path.stat().st_mode & 0o777
            try:
                single.atomic(path, corrected, mode)
                native_check()
                verify_files()
                if single.controls() != before_controls:
                    raise RuntimeError('source_pin_daily_controls_changed')
            except Exception:
                single.atomic(path, current, mode)
                raise
        else:
            native_check()
            verify_files()
            if single.controls() != before_controls:
                raise RuntimeError('source_pin_daily_controls_changed')
        receipt_path = single.safe(single.ROOT / 'source-pins-v48-1-installed.json')
        previous = json.loads(receipt_path.read_text()) if receipt_path.is_file() else {}
        receipt = dict(release='approved-native-source-pins-v48.1',
            state='installed' if changed else 'already_installed',
            before_sha256=OBSERVED_WORKER, corrected_worker_sha256=digest(corrected),
            corrected_single_worker_sha256=digest(final), readiness_sha256=OBSERVED_READINESS,
            source_hashes=EXPECTED_FILES, changed_pins=list(UPDATES),
            backup=str(backup) if backup else previous.get('backup'),
            install_ai_requests=0, automation_sources_modified=False,
            readiness_modified=False, paid_limits_increased=False, publication='not_requested')
        single.atomic(receipt_path, json.dumps(receipt, indent=2).encode())
        return receipt


def main():
    # Verify the complete delivery and test the migration before any live code write.
    payload = json.loads((single.BUNDLE / 'payload-sha256.json').read_text())
    for name, expected in payload.items():
        if digest(single.safe(single.BUNDLE / name).read_bytes()) != expected:
            raise RuntimeError('source_pin_delivery_changed')
    single.command(['runuser', '-u', 'videoagent', '--', single.PYTHON, '-B', '-m',
        'unittest', 'discover', '-s', str(single.BUNDLE), '-p', 'test_source_pin_recovery.py', '-q'],
        timeout=90, cwd=single.BUNDLE)
    print(json.dumps(dict(source_pin_recovery_tests='passed', ai_requests=0)), flush=True)
    receipt = repair()
    print(json.dumps(receipt), flush=True)
    who = pwd.getpwnam('videoagent')
    folder = single.REPO / 'automation/catarsis-single'
    for name in ('source_pin_recovery.py', 'test_source_pin_recovery.py', 'SOURCE-PINS-v48.1.md',
                 'source-pin-observation.json'):
        single.atomic(folder / name, (single.BUNDLE / name).read_bytes(), owner=(who.pw_uid, who.pw_gid))
    single.atomic(folder / 'source-pins-v48-1-installed.json', json.dumps(receipt, indent=2).encode(),
                  owner=(who.pw_uid, who.pw_gid))
    # Unchanged v48 installer checks native preflight, account availability, 35
    # tests, idle/paused controls, then submits the same stable single request.
    single.main()


if __name__ == '__main__':
    try:
        os.umask(0o077)
        main()
    except Exception as exc:
        value = str(exc)
        code = value if value.replace('_', '').isalnum() else type(exc).__name__
        print(json.dumps(dict(state='blocked', error_code=code, publication_allowed=False)), flush=True)
        raise SystemExit(2)
