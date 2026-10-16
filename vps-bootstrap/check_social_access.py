"""Verify six social identities using existing project clients. Never upload."""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile

CHANNELS = {
    'stunning-facts-of-history': {
        'youtube': 'UCXQ1_6A-JkBeQsMkiDcunGA',
        'facebook': '1291553907375982',
        'instagram': '17841437696497761',
    },
    'stunning-revelations': {
        'youtube': 'UC66EnGiys6V3gKe-J0XD-_Q',
        'facebook': '533073909895353',
        'instagram': '17841472326324371',
    },
}


def atomic_report(path, report):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.access-', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def check(channel, platform, repo):
    expected = CHANNELS[channel][platform]
    result = {'expected_id': expected}
    try:
        if platform == 'youtube':
            from channel.channel_profiles import token_path
            path = token_path(channel)
            result['oauth_file'] = path.name
            if not path.is_file():
                return {**result, 'state': 'missing_oauth_file'}
            tracked = subprocess.run(
                ['git', '-C', str(repo), 'ls-files', '--error-unmatch', '--', path.name],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ignored = subprocess.run(
                ['git', '-C', str(repo), 'check-ignore', '--quiet', '--', path.name],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if tracked.returncode != 1 or ignored.returncode != 0:
                return {**result, 'state': 'oauth_git_protection_not_verified'}
            if path.stat().st_mode & 0o077:
                return {**result, 'state': 'oauth_permissions_too_open'}
            from publish.youtube_uploader import get_youtube_service
            service = get_youtube_service(interactive=False, channel_profile=channel)
            rows = service.channels().list(part='id', mine=True).execute().get('items', [])
            actual = str(rows[0].get('id', '')) if len(rows) == 1 else ''
        elif platform == 'facebook':
            from publish.facebook_uploader import _page_context
            _token, actual, _info = _page_context(channel=channel)
            actual = str(actual)
        else:
            from publish.instagram_uploader import _resolve_instagram_identity
            identity = _resolve_instagram_identity(channel=channel)
            actual = str(identity.get('ig_user_id', ''))
        # IDs are safe; raw payloads, paging URLs and transport errors are not retained.
        return {**result, 'actual_id': actual,
                'state': 'identity_verified' if actual == expected else 'identity_mismatch'}
    except Exception as exc:
        safe = {**result, 'state': 'unavailable', 'error_type': type(exc).__name__}
        status = getattr(getattr(exc, 'resp', None), 'status', None)
        if isinstance(status, int):
            safe['http_status'] = status
        return safe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path,
                        default=Path('/home/videoagent/Video-Optimizer-multiplatform'))
    parser.add_argument('--output', type=Path,
                        default=Path('/home/videoagent/video-automation/runtime/social-access.json'))
    args = parser.parse_args()
    if os.geteuid() == 0:
        print('Ejecuta como videoagent, no como root.')
        return 2
    repo = args.repo.resolve()
    if not (repo / 'publish' / 'youtube_uploader.py').is_file():
        print('REPOSITORIO_NO_ENCONTRADO')
        return 2
    os.umask(0o077)
    os.chdir(repo)
    sys.path.insert(0, str(repo))
    report = {'checked_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'scope': 'identity_reads_only', 'uploads_tested': False, 'channels': {}}
    # Existing SDKs may renew OAuth files. Do not authorize interactively or log payloads.
    previous_logging = logging.root.manager.disable
    try:
        logging.disable(logging.CRITICAL)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from infra.env_loader import load_project_env
            load_project_env(base_dir=repo, override=False)
            for channel in CHANNELS:
                suffix = channel.upper().replace('-', '_')
                names = [base + '_' + suffix for base in (
                    'FACEBOOK_PAGE_ACCESS_TOKEN', 'FACEBOOK_PAGE_ID',
                    'INSTAGRAM_USER_ACCESS_TOKEN', 'INSTAGRAM_PAGE_ID')]
                report['channels'][channel] = {
                    'variable_presence': {name: bool(os.environ.get(name)) for name in names},
                    'results': {p: check(channel, p, repo) for p in CHANNELS[channel]},
                }
            report['global_variable_presence'] = {name: bool(os.environ.get(name)) for name in (
                'FACEBOOK_PAGE_ACCESS_TOKEN', 'FACEBOOK_USER_ACCESS_TOKEN', 'FACEBOOK_PAGE_ID',
                'INSTAGRAM_USER_ACCESS_TOKEN', 'INSTAGRAM_PAGE_ID')}
    except Exception as exc:
        report['setup_error_type'] = type(exc).__name__
    finally:
        logging.disable(previous_logging)
    atomic_report(args.output, report)
    verified = 0
    for channel, details in report['channels'].items():
        for platform, row in details['results'].items():
            print(f"{channel} | {platform} | {row['state']}" +
                  (f" | {row['error_type']}" if row.get('error_type') else ''))
            verified += row['state'] == 'identity_verified'
    if report.get('setup_error_type'):
        print('SETUP_ERROR ' + report['setup_error_type'])
    print(f'IDENTIDADES_VERIFICADAS {verified}/6')
    print(f'Informe sin secretos: {args.output}')
    print('Sin subidas ni publicaciones. Esta prueba no demuestra permiso o capacidad de subida.')
    return 0 if verified == 6 else 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('COMPROBACION_FALLIDA ' + type(exc).__name__)
        raise SystemExit(2)
