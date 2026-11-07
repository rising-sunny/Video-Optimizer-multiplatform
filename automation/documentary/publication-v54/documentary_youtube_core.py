#!/usr/bin/env python3
"""Publish only the approved Chrome Dome documentary; no generation or AI calls.

An interrupted transfer is reconciled through its saved YouTube resumable session.
An ambiguous/expired session never causes a second videos.insert operation.
"""
import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

JOB = "d1da2fe6dfb746e09694bb2129ff6f80"
CHANNEL = "stunning-revelations"
CHANNEL_ID = "UC66EnGiys6V3gKe-J0XD-_Q"
RESUME_VIDEO_ID = "B8QPUmNCfCY"
TITLE = "Operation Chrome Dome: Inside America's 24-Hour Nuclear Alert"
REPO = Path("/home/videoagent/Video-Optimizer-multiplatform")
BASE = Path("/home/videoagent/video-automation/runtime/manual-documentary") / JOB
OUT = Path("/home/videoagent/video-automation/runtime/manual-documentary-publication") / JOB
THUMBNAIL_URL = "https://ai-thumbnails.s3.amazonaws.com/editor/8ceaa497-9b02-4d29-9287-7c40169fe60a/69fe9998-345c-4d86-ac89-9bcc1946b0f2.png"
PINS = {
    "video.mp4": "2e73bcbf241d999b8c0071c24a1a86e144fbfbf317a214a58f2cf6299ddc8905",
    "subtitles.srt": "adef89ba9cf12bab7fdaef1b618898fea9b4e232beb67949ce0516093d6ea8ec",
    "approval.json": "c3f808778092fcf648752eedaa1e5fcde506161d09c58dec6c0372b57fc03727",
}
TAGS = ["Operation Chrome Dome", "Chrome Dome", "B-52", "Cold War", "Strategic Air Command",
        "nuclear alert", "KC-135", "aerial refueling", "military history", "Cold War documentary"]
CAPTION_NAME = "English - Chrome Dome"
CHUNK = 10 * 1024 * 1024


class Blocked(RuntimeError):
    pass


def require(ok, code):
    if not ok:
        raise Blocked(code)


def emit(**value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def safe(path):
    path = Path(path)
    require(not any(p.is_symlink() for p in (path, *path.parents)), "publication_symlink_rejected")
    return path


def sha(path):
    h = hashlib.sha256()
    with safe(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(safe(path).read_text())


def save(path, value):
    path = safe(path)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".youtube-")
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def preflight():
    for name, expected in PINS.items():
        require(sha(BASE / name) == expected, "approved_documentary_file_changed")
    approval = read(BASE / "approval.json")
    require(approval.get("quality_approved") is True and approval.get("job_id") == JOB
            and approval.get("channel") == CHANNEL, "documentary_approval_invalid")
    require(sha(BASE / "metadata.json") == approval.get("metadata_sha256"), "approved_metadata_changed")
    require(sha(BASE / "review.json") == approval.get("review_sha256")
            and read(BASE / "review.json").get("approved") is True, "approved_review_changed")
    metadata = read(BASE / "metadata.json")
    require(metadata.get("title") == TITLE and metadata.get("channel") == CHANNEL
            and metadata.get("language") == "en" and metadata.get("is_short") is False,
            "documentary_target_metadata_changed")
    description = metadata.get("description")
    require(isinstance(description, str) and 0 < len(description) <= 5000, "description_invalid")
    require("Music:" in description and "Visual credits:" in description, "required_credits_missing")
    return dict(title=TITLE, description=description, tags=TAGS, categoryId="27",
                defaultLanguage="en", defaultAudioLanguage="en")


def service():
    sys.path.insert(0, str(REPO))
    # Use the existing channel's normal credential loader; never open a login flow.
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        if (REPO / "publish" / "youtube_uploader.py").is_file():
            from publish.youtube_uploader import get_youtube_service
        else:
            from youtube_uploader import get_youtube_service
        youtube = get_youtube_service(interactive=False, channel_profile=CHANNEL)
    youtube._http.timeout = 120
    return youtube


def owner(youtube):
    rows = youtube.channels().list(part="id,contentDetails", mine=True).execute().get("items", [])
    require(len(rows) == 1 and rows[0].get("id") == CHANNEL_ID, "youtube_channel_identity_mismatch")
    return rows[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def no_duplicate(youtube, playlist):
    token = None
    for _ in range(100):
        kwargs = dict(part="snippet", playlistId=playlist, maxResults=50)
        if token:
            kwargs["pageToken"] = token
        data = youtube.playlistItems().list(**kwargs).execute()
        for row in data.get("items", []):
            title = row.get("snippet", {}).get("title", "").casefold()
            require("chrome dome" not in title, "chrome_dome_upload_already_exists_check_youtube")
        token = data.get("nextPageToken")
        if not token:
            return
    raise Blocked("youtube_upload_history_incomplete")


def thumbnail():
    path = safe(OUT / "vidiq-thumbnail.png")
    if not path.exists():
        with urlopen(THUMBNAIL_URL, timeout=45) as response:
            require(response.geturl() == THUMBNAIL_URL, "thumbnail_redirect_changed")
            content = response.read(10 * 1024 * 1024 + 1)
        require(0 < len(content) <= 10 * 1024 * 1024, "thumbnail_download_invalid")
        fd, name = tempfile.mkstemp(dir=OUT, prefix=".thumbnail-")
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(content)
            from PIL import Image
            with Image.open(name) as image:
                image.load()
                require(image.format == "PNG" and image.size == (1280, 720), "thumbnail_image_changed")
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
    if (REPO / "publish" / "thumbnail_publish.py").is_file():
        from publish.thumbnail_publish import prepare_for_youtube
    else:
        from thumbnail_publish import prepare_for_youtube
    prepared = prepare_for_youtube(path, out_dir=OUT)
    return prepared


def session_url(value):
    parsed = urlsplit(value)
    require(parsed.scheme == "https" and parsed.hostname in {
        "www.googleapis.com", "youtube.googleapis.com", "upload.youtube.com"
    } and not parsed.username and not parsed.password, "youtube_session_url_invalid")
    return value


def request(youtube, uri, **kwargs):
    response, content = youtube._http.request(uri, **kwargs)
    code = int(response.status)
    require(code in (200, 201, 308), "youtube_transfer_http_" + str(code))
    return response, content


def uploaded(response, content, state, checkpoint, total):
    code = int(response.status)
    if code in (200, 201):
        result = json.loads(content)
        require(re.fullmatch(r"[A-Za-z0-9_-]{11}", result.get("id", "")) is not None,
                "youtube_upload_id_missing")
        state.update(video_id=result["id"], uploaded_bytes=total, state="uploaded_private")
        checkpoint()
        return total
    value = response.get("range", "")
    match = re.fullmatch(r"bytes=0-(\d+)", value) if value else None
    require(not value or match is not None, "youtube_upload_range_invalid")
    offset = int(match[1]) + 1 if match else 0
    require(0 <= offset <= total, "youtube_upload_range_invalid")
    state["uploaded_bytes"] = offset
    checkpoint()
    return offset


def transfer(youtube, snippet, state, checkpoint):
    if state.get("video_id"):
        return
    total = (BASE / "video.mp4").stat().st_size
    if not state.get("session_uri"):
        require(not state.get("insert_intent"), "ambiguous_upload_initiation_check_youtube_no_new_upload")
        state.update(insert_intent=True, state="initiating_private_upload")
        checkpoint()
        body = json.dumps(dict(snippet=snippet, status=dict(
            privacyStatus="private", selfDeclaredMadeForKids=False)))
        response, _ = request(youtube,
            "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
            method="POST", body=body, headers={"Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(total), "X-Upload-Content-Type": "video/mp4"})
        require(int(response.status) in (200, 201) and response.get("location"), "youtube_session_missing")
        state["session_uri"] = session_url(response["location"])
        checkpoint()  # Persist the session BEFORE sending any video bytes.
    uri = session_url(state["session_uri"])
    response, content = request(youtube, uri, method="PUT", body=b"", headers={
        "Content-Length": "0", "Content-Range": "bytes */" + str(total)})
    offset = uploaded(response, content, state, checkpoint, total)
    if state.get("video_id"):
        return
    require(offset < total, "youtube_final_upload_response_pending")
    with (BASE / "video.mp4").open("rb") as stream:
        while offset < total:
            stream.seek(offset)
            data = stream.read(min(CHUNK, total - offset))
            response, content = request(youtube, uri, method="PUT", body=data, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(data)),
                "Content-Range": f"bytes {offset}-{offset + len(data) - 1}/{total}"})
            next_offset = uploaded(response, content, state, checkpoint, total)
            require(next_offset > offset, "youtube_transfer_not_advancing")
            offset = next_offset
            emit(state="uploading", percent=round(offset * 100 / total, 1))
    require(state.get("video_id"), "youtube_final_upload_response_pending")


def video(youtube, state, snippet):
    data = youtube.videos().list(part="snippet,status,processingDetails", id=state["video_id"]).execute()
    rows = data.get("items", [])
    require(len(rows) == 1, "uploaded_video_readback_unavailable")
    row = rows[0]
    require(row.get("snippet", {}).get("channelId") == CHANNEL_ID, "uploaded_video_owner_mismatch")
    require(all(row["snippet"].get(k) == snippet[k] for k in ("title", "description")),
            "uploaded_metadata_readback_changed")
    return row


def caption_tracks(youtube, state):
    """List by video, including YouTube's explicit no-track 404 response.

    A missing caption is not an authorization error. An already-known caption
    may also briefly be absent while YouTube processes a newly inserted track.
    No other HTTP error is interpreted as an empty collection.
    """
    try:
        return youtube.captions().list(part="snippet", videoId=state["video_id"]).execute().get("items", [])
    except Exception as exc:
        status = getattr(getattr(exc, "resp", None), "status", None)
        try:
            reasons = {e.get("reason") for e in json.loads(exc.content).get("error", {}).get("errors", [])}
        except (AttributeError, ValueError, TypeError):
            reasons = set()
        if status == 404 and reasons == {"captionNotFound"}:
            return []
        raise


def wait_for_video(youtube, snippet, state, checkpoint, wait=time.sleep, polls=60):
    state["phase"] = "waiting_for_video_processing"
    checkpoint()
    for _ in range(polls):
        current = video(youtube, state, snippet)
        upload = current["status"].get("uploadStatus")
        processing = current.get("processingDetails", {}).get("processingStatus")
        require(upload not in ("rejected", "failed", "deleted")
                and processing not in ("failed", "terminated"), "youtube_processing_failed")
        if upload == "processed":
            return
        emit(state="waiting_for_youtube_processing", video_status=upload,
             url="https://www.youtube.com/watch?v=" + state["video_id"])
        wait(20)
    raise Blocked("youtube_processing_pending_reuse_same_command")


def assets(youtube, state, checkpoint, prepared, wait=time.sleep, recovery_polls=6):
    from googleapiclient.http import MediaFileUpload
    video_id = state["video_id"]
    if not state.get("thumbnail_set"):
        state["phase"] = "setting_thumbnail"
        checkpoint()
        youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(
            prepared["path"], mimetype=prepared["mimetype"])).execute()
        state["thumbnail_set"] = True
        checkpoint()
    if state.get("caption_id"):
        # Keep the known remote ID. Its temporary absence must never insert again.
        return
    state["phase"] = "inspecting_existing_captions"
    checkpoint()
    for attempt in range(recovery_polls if state.get("caption_intent") else 1):
        tracks = caption_tracks(youtube, state)
        matching = [t for t in tracks if t.get("snippet", {}).get("language") == "en"
                    and t["snippet"].get("name") == CAPTION_NAME]
        require(len(matching) <= 1, "multiple_matching_caption_tracks")
        if matching:
            require(state.get("caption_intent"), "unexpected_existing_caption_track")
            state["caption_id"] = matching[0]["id"]
            checkpoint()
            return
        if state.get("caption_intent"):
            emit(state="waiting_for_saved_caption", attempt=attempt + 1)
            wait(5)
    require(not state.get("caption_intent"), "ambiguous_caption_insert_check_youtube_no_duplicate")
    state.update(caption_intent=True, phase="uploading_english_subtitles")
    checkpoint()
    result = youtube.captions().insert(part="snippet", body={"snippet": {
        "videoId": video_id, "language": "en", "name": CAPTION_NAME, "isDraft": False}},
        media_body=MediaFileUpload(str(BASE / "subtitles.srt"),
                                   mimetype="application/octet-stream")).execute()
    require(isinstance(result.get("id"), str) and bool(result["id"]), "caption_insert_id_missing")
    state["caption_id"] = result["id"]
    checkpoint()


def finalize(youtube, snippet, state, checkpoint, wait=time.sleep, polls=60):
    require(state.get("thumbnail_set") and state.get("caption_id"), "publication_assets_incomplete")
    state["phase"] = "waiting_for_subtitle_processing"
    checkpoint()
    for _ in range(polls):
        current = video(youtube, state, snippet)
        processing = current.get("processingDetails", {}).get("processingStatus")
        upload = current["status"].get("uploadStatus")
        require(upload not in ("rejected", "failed", "deleted")
                and processing not in ("failed", "terminated"), "youtube_processing_failed")
        track = [t for t in caption_tracks(youtube, state) if t.get("id") == state["caption_id"]]
        require(len(track) <= 1, "multiple_matching_caption_tracks")
        if track:
            require(track[0].get("snippet", {}).get("language") == "en"
                    and track[0]["snippet"].get("name") == CAPTION_NAME,
                    "saved_caption_identity_changed")
        caption_status = track[0].get("snippet", {}).get("status") if track else "not_yet_visible"
        require(caption_status != "failed", "youtube_caption_processing_failed")
        if upload == "processed" and caption_status == "serving":
            break
        emit(state="waiting_for_youtube_processing", video_status=upload, caption_status=caption_status)
        wait(20)
    else:
        raise Blocked("youtube_processing_pending_reuse_same_command")
    if current["status"].get("privacyStatus") != "public":
        state["publish_intent"] = True
        state["phase"] = "making_existing_video_public"
        checkpoint()
        youtube.videos().update(part="status", body={"id": state["video_id"], "status": {
            "privacyStatus": "public", "selfDeclaredMadeForKids": False}}).execute()
    current = video(youtube, state, snippet)
    require(current["status"].get("privacyStatus") == "public", "publication_readback_not_public")
    state.update(state="published", phase="published", url="https://www.youtube.com/watch?v=" + state["video_id"],
                 title=snippet["title"], verified_at=time.time())
    checkpoint()
    emit(state="published", channel=CHANNEL, title=snippet["title"], url=state["url"],
         thumbnail_set=True, english_subtitles=True, ai_requests=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--publish", action="store_true")
    action.add_argument("--resume-existing", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    require(os.geteuid() != 0, "run_as_videoagent_not_root")
    snippet = preflight()
    safe(OUT).mkdir(parents=True, exist_ok=True, mode=0o700)
    with safe(OUT / "youtube.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Blocked("same_documentary_upload_already_running")
        path = OUT / "youtube-receipt.json"
        if args.resume_existing:
            require(path.is_file(), "existing_upload_receipt_required_no_new_upload")
        binding = dict(job_id=JOB, channel_id=CHANNEL_ID, video_sha256=PINS["video.mp4"],
                       approval_sha256=PINS["approval.json"], metadata_sha256=sha(BASE / "metadata.json"),
                       subtitles_sha256=PINS["subtitles.srt"], thumbnail_source=THUMBNAIL_URL)
        state = read(path) if path.exists() else dict(binding, state="prepared")
        require(all(state.get(k) == v for k, v in binding.items()), "saved_upload_receipt_binding_changed")
        if args.resume_existing:
            require(state.get("video_id") == RESUME_VIDEO_ID,
                    "saved_video_id_required_no_new_upload")
            emit(state="resuming_existing_video", url="https://www.youtube.com/watch?v=" + state["video_id"],
                 video_uploads=0, ai_requests=0)
        checkpoint = lambda: save(path, state)
        youtube = service()
        playlist = owner(youtube)
        prepared = thumbnail()
        digest = sha(Path(prepared["path"]))
        require(state.get("thumbnail_sha256", digest) == digest, "saved_thumbnail_changed")
        state["thumbnail_sha256"] = digest
        checkpoint()
        if not args.resume_existing:
            if not state.get("insert_intent") and not state.get("video_id"):
                no_duplicate(youtube, playlist)
            transfer(youtube, snippet, state, checkpoint)
        video(youtube, state, snippet)
        wait_for_video(youtube, snippet, state, checkpoint)
        assets(youtube, state, checkpoint, prepared)
        finalize(youtube, snippet, state, checkpoint)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        code = str(exc) if isinstance(exc, Blocked) else "youtube_publication_" + type(exc).__name__
        fields = dict(state="blocked", error_code=code, job_id=JOB,
                      note="Existing session and video ID preserved; never start another upload manually.")
        try:
            receipt = read(OUT / "youtube-receipt.json")
            fields["saved_progress"] = {k: receipt.get(k) for k in (
                "phase", "video_id", "thumbnail_set", "caption_intent", "caption_id")}
        except Exception:
            pass
        if hasattr(exc, "resp"):
            fields["http_status"] = getattr(exc.resp, "status", None)
            try:
                errors = json.loads(exc.content).get("error", {}).get("errors", [])
                fields["api_reasons"] = [e.get("reason") for e in errors if isinstance(e, dict)]
            except (ValueError, TypeError):
                pass
        emit(**fields)
        raise SystemExit(2)
