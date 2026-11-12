"""One explicit same-input visual retry after a recorded pre-output quota rejection.

Retains both original claim files, the first successful review cache, all usage
and the failed logs. No text requests, research, narration, rendering or uploads.
"""
import os
import re
from datetime import datetime, timezone, timedelta
from documentary_common import *

JOB = '25aadbf87f68457582ea54e435dbd89b'
REQUEST = 'manual-documentary-goldsboro-deepseek-v19-20261027'
REPAIR = 'quota-visual-resume-v27'
AUTH = 'visual-quota-v27.json'
CLAIM = 'visual-quota-v27.claimed'
RETRY_CLAIM = 'vision-quota-v27.claimed'
MUTABLE = {'review.json', 'review-events.jsonl', 'review-stderr.log'}


def rejected_before_output(path):
    path = safe_path(path)
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise Failure('documentary_visual_quota_failure_unverified')
    events = []
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            raise Failure('documentary_visual_quota_failure_unverified') from None
        if not isinstance(row, dict) or row.get('type') not in {
            'thread.started', 'turn.started', 'error', 'turn.failed'}:
            raise Failure('documentary_visual_quota_not_pre_output')
        events.append(row)
    errors = [r for r in events if r.get('type') == 'error']
    if not errors or not any(r.get('type') == 'turn.failed' for r in events):
        raise Failure('documentary_visual_quota_failure_unverified')
    for row in errors:
        message = row.get('message', '')
        if not isinstance(message, str) or not re.search(
            r'usage limit|rate.?limit|insufficient_quota|quota.*(?:exceeded|exhausted)|too many requests', message, re.I):
            raise Failure('documentary_visual_quota_failure_unverified')
    return sha(path)


def files(folder):
    return {str(p.relative_to(folder)): sha(p) for p in folder.rglob('*') if p.is_file()}


def authorize(state, jobs, job):
    if job != JOB:
        raise Failure('documentary_visual_quota_job_not_authorized')
    state, jobs = Path(state), Path(jobs)
    target, folder = state / job, jobs / job
    task, status = read(target / 'request.json'), read(target / 'status.json')
    if (task.get('job_id') != JOB or task.get('request_id') != REQUEST or
        task.get('channel') != CHANNELS[1] or task.get('minutes') != 10 or
        task.get('publication_allowed') is not False or
        not task.get('topic', '').startswith('Goldsboro, North Carolina, 24 January 1961:')):
        raise Failure('documentary_visual_quota_request_mismatch')
    if (target / AUTH).exists():
        return None
    if status.get('state') != 'blocked' or status.get('error_code') != 'generation_dependency_codex_visual_unavailable':
        raise Failure('documentary_visual_quota_requires_saved_failure')
    if (target / 'STOP').exists() or any((folder / n).exists() for n in ('approval.json', 'publication.json', '.transport.json')):
        raise Failure('documentary_visual_quota_job_unavailable')
    failure_pin = rejected_before_output(folder / 'review-events.jsonl')
    qa = read(folder / 'qa.json')
    if qa.get('passed') is not True or qa.get('video_sha256') != sha(folder / 'video.mp4'):
        raise Failure('documentary_visual_quota_video_changed')
    from documentary_layout import effective_text
    effective_text(folder)  # Validate the existing factual/rights resolution.
    from deepseek_runtime import workspace
    root = workspace(folder)
    claims = sorted(p.name for p in root.glob('vision-*.claimed'))
    caches = sorted(p.name for p in root.glob('vision-*.json'))
    failed = [n for n in claims if not (root / n.replace('.claimed', '.json')).exists()]
    if len(claims) != 2 or len(caches) != 1 or len(failed) != 1 or not re.fullmatch(r'vision-[a-f0-9]{64}\.claimed', failed[0]):
        raise Failure('documentary_visual_quota_ledger_mismatch')
    if read(root / 'budget.json').get('pending'):
        raise Failure('documentary_visual_quota_budget_uncertain')
    if (root / RETRY_CLAIM).exists():
        raise Failure('documentary_visual_quota_already_attempted')
    from publication_service import controls
    created = datetime.now(timezone.utc)
    value = dict(job_id=job, repair_id=REPAIR, operation='resume_visual_only',
        created_at=created.isoformat(), expires_at=(created + timedelta(hours=2)).isoformat(),
        request_sha256=sha(target / 'request.json'), controls=controls(),
        code_sha256={n: sha(ROOT / n) for n in MODULES}, original_files=files(folder),
        failed_events_sha256=failure_pin, failed_ident=failed[0][7:-8],
        visual_inputs={p.name: sha(p) for p in sorted(folder.glob('review-sheet-*.jpg')) + [folder/'thumbnail.jpg']},
        ledger_pins={n: sha(root / n) for n in claims + caches},
        budget_sha256=sha(root / 'budget.json'),
        tools_sha256=sha(root / 'tools.json') if (root / 'tools.json').is_file() else None,
        explicit_extra_visual_attempts=1, previous_status=status)
    save(target / AUTH, value)
    return value


def claim_visual(folder, ident, pins, auth):
    if (folder == JOBS / 'd1da2fe6dfb746e09694bb2129ff6f80' and
        isinstance(auth, dict) and auth.get('repair_id') == 'chrome-dome-visual-quota-20261106'):
        from chrome_dome_visual_recovery_20261106 import claim_visual as chrome_claim
        return chrome_claim(folder, ident, pins, auth)
    if folder != JOBS / JOB or auth != read(STATE / JOB / AUTH) or not (STATE / JOB / CLAIM).is_file():
        raise Failure('documentary_visual_quota_authorization_invalid')
    if (auth.get('repair_id') != REPAIR or auth.get('operation') != 'resume_visual_only' or
        auth.get('explicit_extra_visual_attempts') != 1 or not re.fullmatch(r'[a-f0-9]{64}', ident) or
        pins != auth.get('visual_inputs') or any(sha(folder/n) != v for n, v in pins.items())):
        raise Failure('documentary_visual_quota_inputs_changed')
    now_utc = datetime.now(timezone.utc)
    if not datetime.fromisoformat(auth['created_at']) <= now_utc < datetime.fromisoformat(auth['expires_at']):
        raise Failure('documentary_visual_quota_authorization_expired')
    if (STATE / JOB / 'STOP').exists():
        raise Failure('documentary_cancelled')
    if rejected_before_output(folder / 'review-events.jsonl') != auth['failed_events_sha256']:
        raise Failure('documentary_visual_quota_failure_changed')
    from deepseek_runtime import workspace
    root = workspace(folder)
    for name, digest in auth['ledger_pins'].items():
        if sha(root / name) != digest:
            raise Failure('documentary_visual_quota_ledger_changed')
    try:
        fd = os.open(safe_path(root / RETRY_CLAIM), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(dict(repair_id=REPAIR, ident=ident, previous_failed_ident=auth['failed_ident'], authorization_sha256=sha(STATE / JOB / AUTH), created_at=now()), stream)
            stream.flush(); os.fsync(stream.fileno())
    except FileExistsError:
        raise Failure('documentary_visual_quota_already_attempted') from None


def start(broker, job):
    if job != JOB:
        raise Failure('documentary_visual_quota_job_not_authorized')
    if (broker.state / job / AUTH).exists():
        return broker.status(job)
    if broker.active or broker.parent.generation.active or broker.parent.publication.active or broker.parent.active:
        raise Failure('another_manual_operation_is_running')
    authorize(broker.state, broker.jobs, job)
    value = read(broker.state / job / 'status.json')
    value.update(state='accepted', phase='queued_visual_review', repair_id=REPAIR, version=VERSION,
                 quality_approved=False, error_code=None, updated_at=now(), publication_allowed=False)
    save(broker.state / job / 'status.json', value)
    broker.active[job] = True
    try:
        broker.launch(lambda: broker.work(job, visual_quota=True))
    except Exception:
        broker.active.pop(job, None)
        value.update(state='blocked', error_code='documentary_visual_quota_launch_failed')
        save(broker.state / job / 'status.json', value)
    return broker.status(job)


def perform(job):
    if job != JOB:
        raise Failure('documentary_visual_quota_job_not_authorized')
    target, folder = STATE / job, JOBS / job
    auth = read(target / AUTH)
    if auth.get('job_id') != job or auth.get('repair_id') != REPAIR or auth.get('operation') != 'resume_visual_only':
        raise Failure('documentary_visual_quota_authorization_invalid')
    auth_pin = sha(target / AUTH)
    immutable = {n: v for n, v in auth['original_files'].items() if n not in MUTABLE}
    stats = {n: ((folder/n).stat().st_size, (folder/n).stat().st_mtime_ns, (folder/n).stat().st_ctime_ns) for n in immutable}
    from deepseek_runtime import workspace
    from publication_service import controls
    root = workspace(folder)
    def guard():
        now_utc = datetime.now(timezone.utc)
        if not datetime.fromisoformat(auth['created_at']) <= now_utc < datetime.fromisoformat(auth['expires_at']):
            raise Failure('documentary_visual_quota_authorization_expired')
        if (target / 'STOP').exists():
            raise Failure('documentary_cancelled')
        if (sha(target / AUTH) != auth_pin or sha(target / 'request.json') != auth['request_sha256'] or
            controls() != auth['controls'] or any(sha(ROOT/n) != v for n, v in auth['code_sha256'].items())):
            raise Failure('documentary_visual_quota_inputs_changed')
        if any(((folder/n).stat().st_size, (folder/n).stat().st_mtime_ns, (folder/n).stat().st_ctime_ns) != v for n, v in stats.items()):
            raise Failure('documentary_visual_quota_preserved_files_changed')
        if sha(root/'budget.json') != auth['budget_sha256'] or (auth['tools_sha256'] is not None and sha(root/'tools.json') != auth['tools_sha256']):
            raise Failure('documentary_visual_quota_deepseek_state_changed')
        if any(sha(root/n) != v for n, v in auth['ledger_pins'].items()):
            raise Failure('documentary_visual_quota_ledger_changed')
        if any((folder/n).exists() for n in ('publication.json', '.transport.json')):
            raise Failure('documentary_visual_quota_publication_state_exists')
    guard()
    with safe_path(target / CLAIM).open('x') as stream:
        stream.write(now()); stream.flush(); os.fsync(stream.fileno())
    if files(folder) != auth['original_files']:
        raise Failure('documentary_visual_quota_original_files_changed')
    archive = target / 'visual-quota-v27-logs'
    archive.mkdir(mode=0o700)
    for name in MUTABLE:
        if (folder/name).is_file():
            data = safe_path(folder/name).read_bytes()
            fd = os.open(archive/name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            if sha(archive/name) != auth['original_files'][name]:
                raise Failure('documentary_visual_quota_archive_changed')
    value = read(target / 'status.json')
    value.update(state='running', phase='reviewing_saved_video', repair_id=REPAIR, error_code=None, updated_at=now())
    save(target / 'status.json', value)
    # Direct visual review: deliberately never call quality()'s render/correction paths.
    from deepseek_review import documentary
    images = sorted(folder.glob('review-sheet-*.jpg')) + [folder/'thumbnail.jpg']
    if len(images) < 2:
        raise Failure('documentary_visual_quota_frame_sheets_missing')
    guard()
    try:
        documentary(folder, images, quota_recovery=auth)
    finally:
        guard()
        if any(sha(folder/n) != v for n, v in immutable.items()):
            raise Failure('documentary_visual_quota_preserved_files_changed')
    from documentary_worker import approve
    approve(job, read(target/'request.json'), folder, target, auth['code_sha256'])
