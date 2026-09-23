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
    # Estadisticas avanzadas (retencion, fuentes de trafico, suscriptores por
    # video). Sin este scope la YouTube Analytics API responde 403
    # "Request had insufficient authentication scopes".
    "https://www.googleapis.com/auth/yt-analytics.readonly",
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


def _infer_is_short(video_path) -> bool:
    """Best-effort classification: a Short is vertical (h>=w) AND <=180s.

    Falls back to True on any probe failure to preserve historical behavior.
    Long-form documentaries (16:9, several minutes) resolve to False so the
    uploader does not force a #Shorts tag or a /shorts/ URL on them.
    """
    import subprocess
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height:format=duration",
             "-of", "default=noprint_wrappers=1:nokey=0", str(video_path)],
            capture_output=True, text=True, timeout=30,
        ).stdout
        w = h = 0
        dur = 0.0
        for line in out.splitlines():
            if line.startswith("width="):
                w = int(float(line.split("=", 1)[1]))
            elif line.startswith("height="):
                h = int(float(line.split("=", 1)[1]))
            elif line.startswith("duration="):
                try:
                    dur = float(line.split("=", 1)[1])
                except ValueError:
                    pass
        if w and h and dur:
            return (h >= w) and (dur <= 180.0)
    except Exception:
        pass
    return True


def _get_credentials(interactive: bool = True, channel_profile=None) -> Credentials:
    """Load or refresh OAuth2 credentials."""
    creds = None
    from channel_profiles import token_path
    selected_token = token_path(channel_profile)

    if selected_token.exists():
        creds = Credentials.from_authorized_user_file(str(selected_token), SCOPES)

    # `from_authorized_user_file` NO comprueba que el token cubra SCOPES: solo
    # mira el vencimiento. Si se agrega un scope nuevo (paso lo mismo con
    # yt-analytics), el token viejo se sigue usando y la API responde 403 sin
    # que nada avise. Hay que detectarlo y volver a autorizar.
    if creds:
        otorgados = set(creds.scopes or [])
        faltantes = [s for s in SCOPES if s not in otorgados]
        if faltantes:
            print("[YouTube] El token guardado no cubre estos permisos:")
            for s in faltantes:
                print(f"           - {s}")
            print("[YouTube] Hay que volver a autorizar en el navegador.")
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds, selected_token)
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
        _save_token(creds, selected_token)

    return creds


def _save_token(creds: Credentials, selected_token=None):
    """Save credentials to token.json."""
    from channel_profiles import token_path
    with open(selected_token or token_path(), "w") as f:
        f.write(creds.to_json())


def get_youtube_service(interactive: bool = True, channel_profile=None):
    """Build and return an authenticated YouTube API service."""
    creds = _get_credentials(interactive=interactive, channel_profile=channel_profile)
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
    channel_profile=None,
    tag_research: bool = True,
    research_topic: str = None,
    research_script: str = None,
    on_status=None,
    title_mode: str = None,
    archetype: str = None,
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

    from channel_profiles import active_channel, CHANNELS
    from upload_metadata import metadata_for_channel
    channel_profile = channel_profile or active_channel()
    adapted = metadata_for_channel({'title': title, 'description': description, 'tags': tags}, channel_profile)
    title, description, tags = adapted['title'], adapted['description'], adapted['tags']

    # TAGS (2026-09-22). Antes: 'Shorts' insertado primero (YouTube lo ignora como tag;
    # el #Shorts va en titulo/descripcion) y el recorte era a 500 TAGS (slice de la lista)
    # en vez de 500 caracteres. Ahora: investigacion (autocompletado + competencia, ver
    # youtube_tags.py) y una puerta final que limpia y respeta el presupuesto real.
    from upload_metadata import channel_brand
    from youtube_tags import finalize_youtube_tags, counted_length, research_tags

    def _status(msg):
        print(f"   [Tags] {msg}")
        if on_status:
            try:
                on_status(f"   Tags: {msg}")
            except Exception:
                pass

    tag_report = None
    title_report = None
    original_title = title
    research_on = tag_research and str(os.getenv("YOUTUBE_TAG_RESEARCH", "1")).strip().lower() not in ("0", "false", "no", "off")
    # Titulo: 'optimize' lo cambia si el investigado gana por 5+ puntos; 'suggest' deja el
    # del usuario y reporta la mejor alternativa; 'off' no hace nada. Por defecto 'suggest':
    # el Studio pide 'optimize' solo cuando el titulo lo invento el LLM, no el usuario.
    title_mode = str(os.getenv("YOUTUBE_TITLE_MODE") or title_mode or "suggest").strip().lower()
    research = None
    if research_on or title_mode in ("optimize", "suggest"):
        try:
            from youtube_tags import gather_research
            _status("investigando (autocompletado de YouTube + videos que rankean)...")
            research = gather_research(research_topic or title, title, research_script or description, log=_status)
        except Exception as exc:
            _status(f"investigacion no disponible ({exc})")
    if research is not None and title_mode in ("optimize", "suggest"):
        try:
            from youtube_titles import optimize_title
            title_report = optimize_title(research_topic or title, research_script or description, title,
                                          research=research, is_short=is_short, archetype=archetype or "",
                                          mode=title_mode, log=lambda m: _status(m.strip()))
            if title_report["changed"] and title_report["title"]:
                title = title_report["title"]
            if on_status:
                try:
                    on_status(f"   Titulo: {title_report['summary']}")
                except Exception:
                    pass
            print(f"   [Titulo] {title_report['summary']}")
        except Exception as exc:
            _status(f"optimizacion de titulo no disponible ({exc}); se usa el borrador")
    if research is not None and research_on:
        try:
            tag_report = research_tags(
                research_topic or title, title, research_script or description, draft_tags=tags,
                brand_tag=channel_brand(channel_profile).lower(),
                own_channel_names=[channel_brand(channel_profile), CHANNELS[channel_profile]['name']],
                log=_status, research=research,
            )
            if tag_report["tags"]:
                tags = tag_report["tags"]
            _status(tag_report["summary"])
        except Exception as exc:
            _status(f"investigacion no disponible ({exc}); se usan los tags del borrador")
    tags = finalize_youtube_tags(tags)
    if not tags:
        _status("ATENCION: el video sale sin tags (ni investigacion ni borrador aportaron alguno)")

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
            "tags": tags,  # ya cortados a 500 caracteres contados como YouTube (youtube_tags)
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": effective_privacy,
            "selfDeclaredMadeForKids": made_for_kids,
        },
    }

    if publish_at:
        body["status"]["publishAt"] = publish_at

    youtube = get_youtube_service(channel_profile=channel_profile)
    identities = youtube.channels().list(part="id", mine=True).execute().get("items", [])
    if CHANNELS[channel_profile]['channel_id'] not in {item['id'] for item in identities}:
        raise RuntimeError(f"La cuenta de YouTube autorizada no corresponde a {CHANNELS[channel_profile]['name']}; publicación detenida.")

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
        "title_sent": title,
        "title_original": original_title,
        "title_research": ({"summary": title_report["summary"], "score": title_report["score"],
                            "original_score": title_report["original_score"], "keyword": title_report["keyword"],
                            "candidates": [{"title": c["title"], "score": c["score"], "valid": c["valid"]}
                                           for c in title_report["candidates"][:6]]}
                           if title_report else None),
        "tags_sent": list(tags),
        "tags_counted_chars": counted_length(tags),
        # Facebook reusa esta investigacion (facebook_metadata.research_from_youtube).
        "research_subject": (research or {}).get("subject") or None,
        "tag_research": ({k: tag_report[k] for k in ("main_keyword", "summary", "evidence", "sources_ok")}
                         if tag_report else None),
    }
    # Lo que YouTube GUARDO (no lo que se mando): si difiere, se avisa en vez de
    # descubrirlo semanas despues mirando el video.
    try:
        stored = youtube.videos().list(part="snippet", id=video_id).execute().get("items", [])
        stored_tags = (stored[0]["snippet"].get("tags") or []) if stored else []
        result["tags_stored"] = stored_tags
        if tags and len(stored_tags) < len(tags):
            _status(f"ATENCION: se mandaron {len(tags)} tags y YouTube guardo {len(stored_tags)}")
        elif tags:
            _status(f"verificado: YouTube guardo los {len(stored_tags)} tags")
    except Exception as exc:
        _status(f"no se pudo verificar lo guardado ({exc})")

    # Miniatura (thumbnail_publish): formato real por contenido (WebP -> JPEG), <= 2 MB,
    # reintentos ante errores transitorios, y el resultado al PANEL, no solo a la consola.
    # El video YA esta subido: una falla de la miniatura nunca tumba la publicacion.
    def _thumb_status(msg):
        print(f"   [Miniatura] {msg}")
        if on_status:
            try:
                on_status(f"   Miniatura: {msg}")
            except Exception:
                pass

    if thumbnail_path and Path(thumbnail_path).exists():
        from thumbnail_publish import prepare_for_youtube, set_thumbnail_with_retry
        try:
            prepared = prepare_for_youtube(thumbnail_path, log=lambda m: _thumb_status(m.strip()))
            for w in prepared["warnings"]:
                _thumb_status(f"ATENCION: {w}")
            outcome = set_thumbnail_with_retry(youtube, video_id, prepared, on_status=lambda m: _thumb_status(m))
        except Exception as e:
            outcome = {"ok": False, "attempts": 0, "error": f"{type(e).__name__}: {e}"}
            prepared = {"path": str(thumbnail_path)}
        result["thumbnail_set"] = bool(outcome["ok"])
        result["thumbnail_sent"] = str(thumbnail_path)
        result["thumbnail_uploaded_path"] = prepared.get("path")
        if outcome["ok"]:
            _thumb_status(f"subida ({Path(thumbnail_path).name}"
                          + (f", {outcome['attempts']} intentos" if outcome["attempts"] > 1 else "") + ")"
                          + (" -- en Shorts YouTube la muestra en canal y busqueda, no en el feed" if is_short else ""))
        else:
            result["thumbnail_error"] = outcome["error"]
            _thumb_status(f"NO SE PUSO: {outcome['error']} -- el video quedo publicado: {result['url']}")
    else:
        result["thumbnail_set"] = False
        if thumbnail_path:
            _thumb_status(f"el archivo no existe: {thumbnail_path}")
        else:
            _thumb_status("este video sale sin miniatura personalizada (no hay una seleccionada)")

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
    on_status=None,
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
    from channel_profiles import DEFAULT_CHANNEL
    config = {}
    if (output_dir / 'project.json').exists():
        project_data = json.loads((output_dir / 'project.json').read_text(encoding='utf-8'))
        config = project_data.get('config') or {}
    project_channel = (metadata.get('upload_channel') or config.get('upload_channel')
                       or metadata.get('channel_profile') or config.get('channel_profile'))
    if not project_channel and (output_dir / 'storyboard.json').exists():
        project_channel = json.loads((output_dir / 'storyboard.json').read_text(encoding='utf-8')).get('channel_profile')
    project_channel = project_channel or DEFAULT_CHANNEL

    from upload_metadata import metadata_for_channel
    metadata = metadata_for_channel(metadata, project_channel)

    # El render vive en auto_videos/output; la carpeta solo tiene la ruta registrada.
    from output_video_locator import find_output_video
    video_path = find_output_video(output_dir)
    if not video_path:
        raise FileNotFoundError(f"No se encontró video en {output_dir}")
    video_path = Path(video_path)

    # Miniatura: cualquier formato que acepte el selector (antes .webp quedaba afuera).
    from thumbnail_publish import find_staged_thumbnail
    thumbnail_path = find_staged_thumbnail(output_dir)

    # Respect the metadata's is_short flag (set by the pipeline: True for Shorts,
    # False for long-form documentaries). When absent, infer from the video so a
    # 16:9 / multi-minute documentary is never mislabeled as a Short.
    is_short = metadata.get("is_short")
    if is_short is None:
        is_short = _infer_is_short(video_path)

    result = upload_video(
        video_path=str(video_path),
        title=metadata.get("title") or "Untitled video",
        description=metadata.get("description", ""),
        tags=metadata.get("tags", []),
        category_id=str(metadata.get("category_id") or "27"),  # Education
        privacy_status=privacy_status,
        publish_at=publish_at,
        thumbnail_path=str(thumbnail_path) if thumbnail_path else None,
        is_short=bool(is_short),
        on_progress=on_progress,
        channel_profile=project_channel,
        research_topic=metadata.get("topic"),
        research_script=metadata.get("script_excerpt") or metadata.get("script"),
        on_status=on_status,
        title_mode=metadata.get("title_mode"),
        archetype=metadata.get("format_archetype"),
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
