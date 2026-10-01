"""
vps_publish_scheduler.py - Queue and runner for scheduled social publishing on a VPS.

Primary use case:
- Instagram scheduled publishing, because the Graph API publish flow is not natively scheduled.

The queue is stored inside the project so it can be synced/deployed to the VPS together
with the generated Daily Shorts assets.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Optional

from infra.env_loader import load_project_env

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_project_env(PROJECT_DIR)

QUEUE_DIRNAME = "scheduler_queue"
QUEUE_FILENAME = "scheduled_publish_jobs.json"
DEFAULT_POLL_SECONDS = 60
DEFAULT_RETRY_DELAY_SECONDS = 300
MAX_RETRIES = 5
SSH_CONNECT_TIMEOUT_SECONDS = 15
SSH_SERVER_ALIVE_INTERVAL_SECONDS = 15
SSH_SERVER_ALIVE_COUNT_MAX = 3
SSH_RETRY_COUNT = 2
SSH_RETRY_BACKOFF_SECONDS = 3.0
RETRYABLE_SSH_SNIPPETS = (
    "broken pipe",
    "connection closed by remote host",
    "connection reset",
    "connection reset by peer",
    "connection timed out",
    "kex_exchange_identification",
    "operation timed out",
    "ssh_dispatch_run_fatal",
    "timed out",
)


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name, default)
    if value is None:
        return None
    text = str(value).strip()
    return text or default


def _queue_path() -> Path:
    custom = _env("VPS_PUBLISH_QUEUE_FILE")
    if custom:
        return Path(custom)
    return PROJECT_DIR / QUEUE_DIRNAME / QUEUE_FILENAME


def _poll_seconds() -> int:
    raw = _env("VPS_SCHEDULER_POLL_SECONDS", str(DEFAULT_POLL_SECONDS))
    try:
        return max(15, int(raw))
    except Exception:
        return DEFAULT_POLL_SECONDS


def _ssh_host() -> Optional[str]:
    return _env("VPS_SSH_HOST")


def _vps_deploy_dir() -> PurePosixPath:
    # Always treat the remote path as POSIX — never as a Windows Path.
    raw = _env("VPS_DEPLOY_DIR", "/opt/video-optimizer-publisher") or "/opt/video-optimizer-publisher"
    return PurePosixPath(raw.replace("\\", "/"))


def _vps_python_bin() -> str:
    return str(_env("VPS_PYTHON_BIN", "python3") or "python3").strip()


def _read_json(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def _write_json(path: Path, payload) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_utc_iso() -> str:
    return _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso_utc(value: Optional[str]) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _normalize_folder(folder: str | Path) -> Path:
    return Path(folder).expanduser().resolve()


def _folder_relative_to_project(folder: Path) -> Optional[str]:
    try:
        return str(folder.relative_to(PROJECT_DIR))
    except Exception:
        return None


def _resolve_job_folder(job: dict) -> Path:
    relative_folder = str(job.get("relative_folder") or "").strip()
    if relative_folder:
        candidate = (PROJECT_DIR / relative_folder).resolve()
        if candidate.exists():
            return candidate
    folder = str(job.get("folder") or "").strip()
    if folder:
        return Path(folder).expanduser().resolve()
    raise FileNotFoundError(f"Scheduled job has no valid folder: {job}")


def _run_local_command(args: list[str], cwd: Optional[str] = None, *,
                       retries: int = 0,
                       retry_delay_seconds: float = 1.0,
                       retryable: Optional[Callable[[str], bool]] = None) -> str:
    max_attempts = max(1, int(retries) + 1)
    for attempt in range(1, max_attempts + 1):
        completed = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode == 0:
            return (completed.stdout or "").strip()

        message = (completed.stderr or completed.stdout or "").strip()
        if attempt >= max_attempts or not retryable or not retryable(message):
            raise RuntimeError(message or f"Command failed: {' '.join(args)}")
        time.sleep(max(0.0, float(retry_delay_seconds)) * attempt)

    raise RuntimeError(f"Command failed after retries: {' '.join(args)}")


def _ssh_transport_args() -> list[str]:
    return [
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT_SECONDS}",
        "-o", "ConnectionAttempts=2",
        "-o", f"ServerAliveInterval={SSH_SERVER_ALIVE_INTERVAL_SECONDS}",
        "-o", f"ServerAliveCountMax={SSH_SERVER_ALIVE_COUNT_MAX}",
        "-o", "TCPKeepAlive=yes",
        "-o", "Compression=yes",
        "-o", "PreferredAuthentications=publickey",
    ]


def _is_retryable_ssh_error(message: str) -> bool:
    text = str(message or "").strip().lower()
    if not text:
        return False
    return any(snippet in text for snippet in RETRYABLE_SSH_SNIPPETS)


def _remote_shell(command: str) -> str:
    host = _ssh_host()
    if not host:
        raise RuntimeError("VPS_SSH_HOST is not configured.")
    return _run_local_command(
        ["ssh", *_ssh_transport_args(), host, command],
        retries=SSH_RETRY_COUNT,
        retry_delay_seconds=SSH_RETRY_BACKOFF_SECONDS,
        retryable=_is_retryable_ssh_error,
    )


def _sync_folder_to_vps(local_folder: Path, relative_folder: str) -> PurePosixPath:
    host = _ssh_host()
    if not host:
        raise RuntimeError("VPS_SSH_HOST is not configured.")

    relative_path = PurePosixPath(relative_folder.replace("\\", "/"))
    remote_root = _vps_deploy_dir()
    remote_parent = (remote_root / relative_path.parent).as_posix()
    local_folder = Path(local_folder).resolve()
    _remote_shell(f"mkdir -p {shlex.quote(remote_parent)}")
    _run_local_command(
        ["scp", *_ssh_transport_args(), "-r", local_folder.name, f"{host}:{remote_parent}/"],
        cwd=str(local_folder.parent),
        retries=SSH_RETRY_COUNT,
        retry_delay_seconds=SSH_RETRY_BACKOFF_SECONDS,
        retryable=_is_retryable_ssh_error,
    )
    return remote_root / relative_path


def _enqueue_job_on_vps(remote_folder: Path, title: str, publish_at: str, *,
                        youtube: bool, facebook: bool, instagram: bool, privacy: str,
                        origin: str) -> dict:
    deploy_dir = _vps_deploy_dir().as_posix()
    python_bin = _vps_python_bin()
    payload = {
        "folder": remote_folder.as_posix(),
        "title": title,
        "publish_at": publish_at,
        "youtube": bool(youtube),
        "facebook": bool(facebook),
        "instagram": bool(instagram),
        "privacy": privacy,
        "origin": f"{origin}:remote",
    }
    script = (
        "import json\n"
        "from publish.vps_publish_scheduler import enqueue_job\n"
        f"payload = json.loads({json.dumps(json.dumps(payload, ensure_ascii=False))!r})\n"
        "job = enqueue_job(\n"
        "    folder=payload['folder'],\n"
        "    title=payload['title'],\n"
        "    publish_at=payload['publish_at'],\n"
        "    youtube=payload['youtube'],\n"
        "    facebook=payload['facebook'],\n"
        "    instagram=payload['instagram'],\n"
        "    privacy=payload['privacy'],\n"
        "    origin=payload['origin'],\n"
        "    auto_sync=False,\n"
        ")\n"
        "print(json.dumps(job, ensure_ascii=False))\n"
    )
    remote_cmd = (
        f"cd {shlex.quote(deploy_dir)} && "
        f"{shlex.quote(python_bin)} - <<'PY'\n{script}PY"
    )
    output = _remote_shell(remote_cmd)
    return json.loads(output) if output else {}


def _sync_job_to_vps(payload: dict, local_folder: Path) -> dict:
    host = _ssh_host()
    if not host:
        return {}

    relative_folder = str(payload.get("relative_folder") or "").strip()
    if not relative_folder:
        raise RuntimeError(
            "The scheduled short folder is outside the project root. "
            "VPS sync requires the short to live inside the project directory."
        )

    remote_folder = _sync_folder_to_vps(local_folder, relative_folder)
    remote_job = _enqueue_job_on_vps(
        remote_folder=remote_folder,
        title=str(payload.get("title") or local_folder.name),
        publish_at=str(payload.get("publish_at") or ""),
        youtube=bool(payload.get("youtube")),
        facebook=bool(payload.get("facebook")),
        instagram=bool(payload.get("instagram")),
        privacy=str(payload.get("privacy") or "private"),
        origin=str(payload.get("origin") or "app"),
    )
    return {
        "synced": True,
        "host": host,
        "remote_folder": remote_folder.as_posix(),
        "remote_job_id": remote_job.get("id"),
    }


def _load_queue() -> list[dict]:
    queue_path = _queue_path()
    payload = _read_json(queue_path, [])
    return payload if isinstance(payload, list) else []


def _save_queue(jobs: list[dict]) -> Path:
    queue_path = _queue_path()
    _write_json(queue_path, jobs)
    return queue_path


def _create_instagram_placeholder_record(folder: Path, publish_at: str, title: str, job_id: str) -> dict:
    now_text = _now_utc_iso()
    return {
        "job_id": job_id,
        "url": None,
        "permalink_url": None,
        "status": "queued_on_vps",
        "scheduled": True,
        "publish_at": publish_at,
        "uploaded_at": now_text,
        "title": str(title or folder.name).strip(),
        "description": "",
        "scheduler": "vps",
    }


def _append_instagram_placeholder(folder: Path, publish_at: str, title: str, job_id: str) -> None:
    folder = Path(folder)
    payload = _create_instagram_placeholder_record(folder, publish_at, title, job_id)
    base_file = folder / "instagram_upload_result.json"
    if not base_file.exists():
        _write_json(base_file, payload)

    stamp = payload["uploaded_at"].replace("-", "").replace(":", "")
    archive_file = folder / f"instagram_upload_result_{stamp}.json"
    counter = 2
    while archive_file.exists():
        archive_file = folder / f"instagram_upload_result_{stamp}_{counter}.json"
        counter += 1
    _write_json(archive_file, payload)


def _job_matches(existing: dict, folder: Path, publish_at: str,
                 youtube: bool, facebook: bool, instagram: bool, privacy: str) -> bool:
    if str(existing.get("publish_at") or "").strip() != publish_at:
        return False
    if str(existing.get("privacy") or "private") != privacy:
        return False
    if bool(existing.get("youtube")) != bool(youtube):
        return False
    if bool(existing.get("facebook")) != bool(facebook):
        return False
    if bool(existing.get("instagram")) != bool(instagram):
        return False
    existing_folder = str(existing.get("relative_folder") or existing.get("folder") or "").strip()
    relative_folder = _folder_relative_to_project(folder)
    return existing_folder in {str(folder), str(relative_folder or "")}


def enqueue_job(folder: str | Path, title: str, publish_at: str, *,
                youtube: bool = False, facebook: bool = False, instagram: bool = False,
                privacy: str = "private", origin: str = "app",
                auto_sync: bool = True) -> dict:
    resolved_folder = _normalize_folder(folder)
    if not resolved_folder.exists():
        raise FileNotFoundError(f"Scheduled publish folder not found: {resolved_folder}")

    publish_dt = _parse_iso_utc(publish_at)
    if not publish_dt:
        raise RuntimeError(f"Invalid publish_at for VPS scheduler: {publish_at}")
    if publish_dt <= _now_utc():
        raise RuntimeError("Scheduled publish time must be in the future.")

    if not any([youtube, facebook, instagram]):
        raise RuntimeError("At least one platform must be enabled for the scheduled job.")

    jobs = _load_queue()
    for job in jobs:
        if str(job.get("status") or "").lower() in {"queued", "retrying", "running"} and _job_matches(
            job, resolved_folder, publish_at, youtube, facebook, instagram, privacy
        ):
            return job

    job_id = uuid.uuid4().hex[:12]
    relative_folder = _folder_relative_to_project(resolved_folder)
    payload = {
        "id": job_id,
        "created_at": _now_utc_iso(),
        "origin": str(origin or "app"),
        "folder": str(resolved_folder),
        "relative_folder": relative_folder,
        "title": str(title or resolved_folder.name).strip() or resolved_folder.name,
        "youtube": bool(youtube),
        "facebook": bool(facebook),
        "instagram": bool(instagram),
        "privacy": str(privacy or "private"),
        "publish_at": publish_at,
        "status": "queued",
        "attempt_count": 0,
        "next_attempt_at": publish_at,
        "last_error": None,
        "platform_results": {},
    }

    if auto_sync and _ssh_host():
        payload["vps_sync"] = _sync_job_to_vps(payload, resolved_folder)

    jobs.append(payload)
    _save_queue(jobs)

    if instagram:
        _append_instagram_placeholder(resolved_folder, publish_at, payload["title"], job_id)

    return payload


def _should_run(job: dict, now: datetime) -> bool:
    status = str(job.get("status") or "").lower()
    if status not in {"queued", "retrying", "running"}:
        return False
    publish_dt = _parse_iso_utc(job.get("publish_at"))
    if not publish_dt or publish_dt > now:
        return False
    next_attempt = _parse_iso_utc(job.get("next_attempt_at"))
    if next_attempt and next_attempt > now:
        return False
    return True


def _mark_retry(job: dict, error_text: str) -> None:
    attempts = int(job.get("attempt_count") or 0)
    retry_at = _now_utc() + timedelta(seconds=DEFAULT_RETRY_DELAY_SECONDS)
    job["status"] = "retrying" if attempts < MAX_RETRIES else "failed"
    job["last_error"] = str(error_text or "").strip()[:1000]
    job["next_attempt_at"] = retry_at.strftime("%Y-%m-%dT%H:%M:%SZ") if attempts < MAX_RETRIES else None
    job["updated_at"] = _now_utc_iso()


def _run_job_platforms(job: dict, on_log=None) -> dict:
    folder = _resolve_job_folder(job)
    platform_results = dict(job.get("platform_results") or {})

    def _log(message: str):
        if callable(on_log):
            on_log(message)

    if job.get("youtube") and not platform_results.get("youtube"):
        _log(f"[VPS scheduler] Uploading to YouTube: {folder}")
        from publish.youtube_uploader import upload_from_metadata as upload_youtube_from_metadata

        platform_results["youtube"] = upload_youtube_from_metadata(
            str(folder),
            privacy_status=str(job.get("privacy") or "private"),
            publish_at=None,
        )

    if job.get("facebook") and not platform_results.get("facebook"):
        _log(f"[VPS scheduler] Publishing to Facebook: {folder}")
        from publish.facebook_uploader import upload_from_metadata as upload_facebook_from_metadata

        platform_results["facebook"] = upload_facebook_from_metadata(
            str(folder),
            video_state="PUBLISHED",
            scheduled_publish_time=None,
        )

    if job.get("instagram") and not platform_results.get("instagram"):
        _log(f"[VPS scheduler] Publishing to Instagram: {folder}")
        from publish.instagram_uploader import upload_from_metadata as upload_instagram_from_metadata

        platform_results["instagram"] = upload_instagram_from_metadata(
            str(folder),
            share_to_feed=True,
        )

    return platform_results


def process_due_jobs(limit: Optional[int] = None, on_log=None) -> dict:
    jobs = _load_queue()
    now = _now_utc()
    due_jobs = [job for job in jobs if _should_run(job, now)]
    due_jobs.sort(key=lambda job: str(job.get("publish_at") or ""))
    if limit is not None:
        due_jobs = due_jobs[:max(0, int(limit))]

    processed = 0
    succeeded = 0
    failed = 0

    for due_job in due_jobs:
        processed += 1
        due_job["status"] = "running"
        due_job["attempt_count"] = int(due_job.get("attempt_count") or 0) + 1
        due_job["last_error"] = None
        due_job["updated_at"] = _now_utc_iso()
        _save_queue(jobs)

        try:
            platform_results = _run_job_platforms(due_job, on_log=on_log)
            due_job["platform_results"] = platform_results
            due_job["status"] = "completed"
            due_job["completed_at"] = _now_utc_iso()
            due_job["next_attempt_at"] = None
            due_job["updated_at"] = due_job["completed_at"]
            succeeded += 1
        except Exception as e:
            _mark_retry(due_job, str(e))
            failed += 1
            if callable(on_log):
                on_log(f"[VPS scheduler] Job {due_job.get('id')} failed: {e}")

        _save_queue(jobs)

    return {
        "processed": processed,
        "succeeded": succeeded,
        "failed": failed,
        "queue_path": str(_queue_path()),
    }


def list_jobs(status: Optional[str] = None) -> list[dict]:
    jobs = _load_queue()
    if not status:
        return jobs
    wanted = str(status).strip().lower()
    return [job for job in jobs if str(job.get("status") or "").lower() == wanted]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Video Optimizer VPS publish scheduler.")
    parser.add_argument("--once", action="store_true", help="Process due jobs once and exit.")
    parser.add_argument("--loop", action="store_true", help="Keep polling for due jobs.")
    parser.add_argument("--poll-seconds", type=int, default=_poll_seconds(), help="Polling interval for --loop.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of due jobs to process per pass.")
    parser.add_argument("--show", action="store_true", help="Print the current queue and exit.")
    args = parser.parse_args(argv)

    if args.show:
        print(json.dumps(list_jobs(), indent=2, ensure_ascii=False))
        return 0

    if args.once or not args.loop:
        result = process_due_jobs(limit=args.limit, on_log=print)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    poll_seconds = max(15, int(args.poll_seconds or _poll_seconds()))
    print(f"VPS publish scheduler running. Poll every {poll_seconds}s")
    while True:
        result = process_due_jobs(limit=args.limit, on_log=print)
        if result.get("processed"):
            print(json.dumps(result, indent=2, ensure_ascii=False))
        time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
