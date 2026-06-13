"""
youtube_uploader.py — Upload videos to YouTube via the Data API v3.

Uses OAuth2 credentials from client_secrets.json / token.json.
Supports resumable uploads for large files.
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

PROJECT_DIR = Path(__file__).resolve().parent
CLIENT_SECRETS_FILE = PROJECT_DIR / "client_secrets.json"
TOKEN_FILE = PROJECT_DIR / "token.json"
YOUTUBE_METADATA_FILES = ("youtube_metadata.json", "metadata.json")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

# YouTube category IDs
CATEGORY_IDS = {
    "education": "27",
    "science": "28",
    "entertainment": "24",
    "people": "22",
    "news": "25",
    "howto": "26",
}

# Retry config for resumable uploads
MAX_RETRIES = 5
RETRY_STATUSES = [500, 502, 503, 504]


def _write_json(path: Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _archive_upload_result(result_file: Path, payload: dict) -> Path:
    result_file = Path(result_file)
    uploaded_at = str(payload.get("uploaded_at") or time.strftime("%Y-%m-%dT%H:%M:%S"))
    stamp = uploaded_at.replace("-", "").replace(":", "")
    archive_path = result_file.with_name(f"{result_file.stem}_{stamp}{result_file.suffix}")
    counter = 2
    while archive_path.exists():
        archive_path = result_file.with_name(f"{result_file.stem}_{stamp}_{counter}{result_file.suffix}")
        counter += 1
    _write_json(archive_path, payload)
    return archive_path


def _load_upload_metadata(output_dir: Path) -> dict:
    for filename in YOUTUBE_METADATA_FILES:
        meta_path = output_dir / filename
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(
        f"No se encontró metadata de YouTube en {output_dir}. "
        f"Archivos esperados: {', '.join(YOUTUBE_METADATA_FILES)}"
    )


def _get_credentials(interactive: bool = True) -> Credentials:
    """Load or refresh OAuth2 credentials."""
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if not interactive:
            raise RuntimeError("YouTube authentication is not available for background sync.")
        if not CLIENT_SECRETS_FILE.exists():
            raise FileNotFoundError(
                f"No se encontró {CLIENT_SECRETS_FILE}. "
                "Descarga las credenciales OAuth desde Google Cloud Console."
            )
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CLIENT_SECRETS_FILE), SCOPES
        )
        creds = flow.run_local_server(port=0, open_browser=True)
        _save_token(creds)

    return creds


def _save_token(creds: Credentials):
    """Save credentials to token.json."""
    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())


def get_youtube_service(interactive: bool = True):
    """Build and return an authenticated YouTube API service."""
    creds = _get_credentials(interactive=interactive)
    return build("youtube", "v3", credentials=creds)


def upload_video(
    video_path: str,
    title: str,
    description: str = "",
    tags: list = None,
    category_id: str = "27",
    privacy_status: str = "private",
    publish_at: str = None,
    thumbnail_path: str = None,
    made_for_kids: bool = False,
    is_short: bool = True,
    on_progress=None,
) -> dict:
    """
    Upload a video to YouTube.

    Args:
        video_path: Path to the video file.
        title: Video title (max 100 chars).
        description: Video description (max 5000 chars).
        tags: List of tags.
        category_id: YouTube category ID (default: "27" Education).
        privacy_status: "private", "unlisted", or "public".
        publish_at: ISO 8601 datetime for scheduled publishing (e.g. "2026-04-10T18:00:00Z").
                    When set, video is uploaded as private and auto-publishes at that time.
        thumbnail_path: Path to custom thumbnail image.
        made_for_kids: Whether the video is made for kids.
        is_short: Whether this is a YouTube Short (adds #shorts to tags).
        on_progress: Callback(bytes_sent, total_bytes) for progress tracking.

    Returns:
        dict with video_id, url, status, and full API response.

    Raises:
        FileNotFoundError: If video file doesn't exist.
        HttpError: If YouTube API returns an error.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video no encontrado: {video_path}")

    # Ensure #Shorts tag for Shorts
    tags = list(tags or [])
    if is_short and "Shorts" not in tags and "shorts" not in tags:
        tags.insert(0, "Shorts")

    # Truncate title/description to YouTube limits
    title = title[:100]
    description = description[:5000]

    # When scheduling, video must be private until publish_at
    if publish_at:
        effective_privacy = "private"
    else:
        effective_privacy = privacy_status

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags[:500],  # YouTube limit
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": effective_privacy,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }

    if publish_at:
        body["status"]["publishAt"] = publish_at

    youtube = get_youtube_service()

    # Resumable upload
    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024,  # 10 MB chunks
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = _resumable_upload(request, on_progress)

    video_id = response["id"]
    result = {
        "video_id": video_id,
        "url": f"https://youtube.com/shorts/{video_id}" if is_short else f"https://youtu.be/{video_id}",
        "status": response["status"]["uploadStatus"],
        "scheduled": bool(publish_at),
        "publish_at": publish_at,
        "response": response,
    }

    # Set custom thumbnail
    if thumbnail_path and Path(thumbnail_path).exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/png"),
            ).execute()
            result["thumbnail_set"] = True
        except HttpError as e:
            # Thumbnail upload may fail if channel isn't verified
            result["thumbnail_set"] = False
            result["thumbnail_error"] = str(e)

    return result


def _resumable_upload(request, on_progress=None) -> dict:
    """Execute a resumable upload with retries."""
    response = None
    retry = 0

    while response is None:
        try:
            status, response = request.next_chunk()
            if status and on_progress:
                on_progress(status.resumable_progress, status.total_size)
        except HttpError as e:
            if e.resp.status in RETRY_STATUSES and retry < MAX_RETRIES:
                retry += 1
                wait = 2 ** retry
                time.sleep(wait)
            else:
                raise
        except Exception as e:
            if retry < MAX_RETRIES:
                retry += 1
                wait = 2 ** retry
                time.sleep(wait)
            else:
                raise

    return response


def upload_from_metadata(
    output_dir: str,
    privacy_status: str = "private",
    publish_at: str = None,
    on_progress=None,
) -> dict:
    """
    Upload a video using the metadata.json generated by the pipeline.

    Args:
        output_dir: Path to the short's output directory (contains video, metadata.json, thumbnail).
        privacy_status: "private", "unlisted", or "public".
        publish_at: ISO 8601 datetime for scheduled publishing.
        on_progress: Progress callback.

    Returns:
        dict with upload result.
    """
    output_dir = Path(output_dir)

    metadata = _load_upload_metadata(output_dir)

    # Find video file
    video_path = None
    for ext in ["*.mp4", "*.webm", "*.mkv"]:
        videos = list(output_dir.glob(ext))
        if videos:
            video_path = videos[0]
            break

    if not video_path:
        raise FileNotFoundError(f"No se encontró video en {output_dir}")

    # Find thumbnail
    thumbnail_path = None
    for ext in ["*.png", "*.jpg", "*.jpeg"]:
        thumbs = list(output_dir.glob(f"thumbnail{ext}")) or list(output_dir.glob(f"thumb{ext}"))
        if thumbs:
            thumbnail_path = thumbs[0]
            break
    # Also check for any image that looks like a thumbnail
    if not thumbnail_path:
        for img in output_dir.glob("*.png"):
            if "thumbnail" in img.stem.lower() or "thumb" in img.stem.lower():
                thumbnail_path = img
                break

    result = upload_video(
        video_path=str(video_path),
        title=metadata.get("title", "Stunning Revelations"),
        description=metadata.get("description", ""),
        tags=metadata.get("tags", []),
        category_id="27",  # Education
        privacy_status=privacy_status,
        publish_at=publish_at,
        thumbnail_path=str(thumbnail_path) if thumbnail_path else None,
        is_short=True,
        on_progress=on_progress,
    )

    # Save upload result
    upload_result_path = output_dir / "upload_result.json"
    save_data = {
        "video_id": result["video_id"],
        "url": result["url"],
        "status": result["status"],
        "privacy": privacy_status,
        "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "thumbnail_set": result.get("thumbnail_set", False),
        "scheduled": bool(publish_at),
        "publish_at": publish_at,
    }
    _write_json(upload_result_path, save_data)
    _archive_upload_result(upload_result_path, save_data)

    return result


def fetch_video_states(video_ids: list[str]) -> dict[str, dict]:
    """
    Fetch the latest scheduling/privacy state for uploaded YouTube videos.

    Args:
        video_ids: List of YouTube video IDs.

    Returns:
        Mapping of video_id -> state dict with privacy/publish_at/scheduled.
    """
    clean_ids = []
    seen = set()
    for video_id in video_ids or []:
        video_id = str(video_id or "").strip()
        if not video_id or video_id in seen:
            continue
        clean_ids.append(video_id)
        seen.add(video_id)

    if not clean_ids:
        return {}

    youtube = get_youtube_service(interactive=False)
    states = {}

    for start in range(0, len(clean_ids), 50):
        batch_ids = clean_ids[start:start + 50]
        response = youtube.videos().list(
            part="status,snippet",
            id=",".join(batch_ids),
        ).execute()

        for item in response.get("items", []):
            video_id = item.get("id")
            status = item.get("status", {}) or {}
            snippet = item.get("snippet", {}) or {}
            privacy = status.get("privacyStatus")
            publish_at = status.get("publishAt")
            states[video_id] = {
                "video_id": video_id,
                "privacy": privacy,
                "publish_at": publish_at,
                "scheduled": bool(publish_at and privacy == "private"),
                "title": snippet.get("title"),
            }

    return states


def sync_upload_result_files(output_dirs: list[str]) -> dict[str, dict]:
    """
    Refresh local upload_result.json files with the current schedule from YouTube.

    Args:
        output_dirs: Short output directories that may contain upload_result.json.

    Returns:
        Mapping of output_dir -> refreshed upload_result payload.
    """
    records = []
    video_ids = []

    for output_dir in output_dirs or []:
        short_dir = Path(output_dir)
        upload_result_path = short_dir / "upload_result.json"
        if not upload_result_path.exists():
            continue

        try:
            with open(upload_result_path, "r", encoding="utf-8") as f:
                upload_data = json.load(f)
        except Exception:
            continue

        video_id = str(upload_data.get("video_id") or "").strip()
        if not video_id:
            continue

        records.append((short_dir, upload_result_path, upload_data, video_id))
        video_ids.append(video_id)

    if not records:
        return {}

    remote_states = fetch_video_states(video_ids)
    synced = {}

    for short_dir, upload_result_path, upload_data, video_id in records:
        remote_state = remote_states.get(video_id)
        if not remote_state:
            synced[str(short_dir)] = upload_data
            continue

        refreshed = dict(upload_data)
        privacy = remote_state.get("privacy") or refreshed.get("privacy")
        publish_at = remote_state.get("publish_at")
        refreshed["privacy"] = privacy
        refreshed["publish_at"] = publish_at
        refreshed["scheduled"] = bool(publish_at and privacy == "private")

        if refreshed != upload_data:
            with open(upload_result_path, "w", encoding="utf-8") as f:
                json.dump(refreshed, f, indent=2, ensure_ascii=False)

        synced[str(short_dir)] = refreshed

    return synced


def get_next_optimal_publish_time(slot_index: int = 0, start_date: str = None) -> str:
    """
    Calculate the next optimal publish time for Stunning Revelations.

    Uses 2 daily slots at peak hours (12 PM and 6 PM ET), skipping Sundays.
    When generating a batch, each short gets the next available slot.

    Slot distribution:
        slot 0  next available 12 PM ET
        slot 1  same day 6 PM ET
        slot 2  next day 12 PM ET
        slot 3  next day 6 PM ET
        ... and so on, skipping Sundays.

    Args:
        slot_index: Which slot in the batch (0-based).
        start_date: Optional YYYY-MM-DD date to begin filling slots from.

    Returns:
        ISO 8601 datetime string in UTC.
    """
    from datetime import datetime, timedelta, date, time
    import zoneinfo

    et = zoneinfo.ZoneInfo("America/New_York")
    now = datetime.now(et)

    if start_date:
        if isinstance(start_date, datetime):
            base_date = start_date.astimezone(et).date() if start_date.tzinfo else start_date.date()
        elif isinstance(start_date, date):
            base_date = start_date
        else:
            base_date = date.fromisoformat(str(start_date))
        if base_date < now.date():
            base_date = now.date()
        candidate_day = datetime.combine(base_date, time.min, tzinfo=et)
    else:
        candidate_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Two daily slots: 12 PM ET (lunch peak) and 6 PM ET (evening peak)
    DAILY_SLOTS = [12, 18]

    slots_found = 0
    while True:
        # Skip Sundays
        if candidate_day.weekday() == 6:
            candidate_day += timedelta(days=1)
            continue

        for hour in DAILY_SLOTS:
            candidate = candidate_day.replace(hour=hour, minute=0)
            # Must be in the future (at least 30 min from now)
            if candidate <= now + timedelta(minutes=30):
                continue

            if slots_found == slot_index:
                utc_time = candidate.astimezone(zoneinfo.ZoneInfo("UTC"))
                return utc_time.strftime("%Y-%m-%dT%H:%M:%SZ")

            slots_found += 1

        candidate_day += timedelta(days=1)


def check_auth() -> dict:
    """
    Check if YouTube authentication is valid.

    Returns:
        dict with 'authenticated' (bool), 'channel' (str), 'error' (str).
    """
    try:
        youtube = get_youtube_service()
        resp = youtube.channels().list(part="snippet", mine=True).execute()
        items = resp.get("items", [])
        if items:
            channel = items[0]["snippet"]["title"]
            return {"authenticated": True, "channel": channel, "error": None}
        return {"authenticated": False, "channel": None, "error": "No channel found"}
    except Exception as e:
        return {"authenticated": False, "channel": None, "error": str(e)}
