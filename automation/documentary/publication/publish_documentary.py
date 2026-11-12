#!/usr/bin/env python3
"""Permanent adapter for the tested documentary YouTube publisher.

Every invocation identifies one job, the approved file fingerprint and the
chosen thumbnail. Inspecting or installing this tool never publishes a video.
"""
import argparse
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

import documentary_youtube_core as core

JOBS = Path("/home/videoagent/video-automation/runtime/manual-documentary")
PUBLICATIONS = Path("/home/videoagent/video-automation/runtime/manual-documentary-publication")
CHANNELS = {
    "stunning-facts-of-history": "UCXQ1_6A-JkBeQsMkiDcunGA",
    "stunning-revelations": "UC66EnGiys6V3gKe-J0XD-_Q",
}
LEGACY_CHROME_DOME = "d1da2fe6dfb746e09694bb2129ff6f80"


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--approval-sha256", required=True)
    parser.add_argument("--thumbnail-url", required=True)
    parser.add_argument("--video-id", help="Exact saved remote ID required when resuming.")
    parser.add_argument("--tag", action="append", default=[])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--inspect", action="store_true")
    action.add_argument("--publish", action="store_true")
    action.add_argument("--resume-existing", action="store_true")
    return parser.parse_args(argv)


def duplicate_check(youtube, playlist):
    """The generation pipeline checks topic history; this prevents repeat uploads."""
    expected = " ".join(core.TITLE.casefold().split())
    token = None
    for _ in range(100):
        params = dict(part="snippet", playlistId=playlist, maxResults=50)
        if token:
            params["pageToken"] = token
        result = youtube.playlistItems().list(**params).execute()
        for row in result.get("items", []):
            actual = " ".join(row.get("snippet", {}).get("title", "").casefold().split())
            core.require(actual != expected, "documentary_upload_already_exists_check_youtube")
        token = result.get("nextPageToken")
        if not token:
            return
    raise core.Blocked("youtube_upload_history_incomplete")


def configure(args):
    core.require(re.fullmatch(r"[a-f0-9]{32}", args.job_id) is not None, "invalid_documentary_job_id")
    core.require(re.fullmatch(r"[a-f0-9]{64}", args.approval_sha256) is not None,
                 "invalid_documentary_approval_sha256")
    url = urlsplit(args.thumbnail_url)
    core.require(url.scheme == "https" and bool(url.hostname) and not url.username
                 and not url.password and not url.fragment, "thumbnail_https_url_required")
    folder = core.safe(JOBS / args.job_id)
    core.require(core.sha(folder / "approval.json") == args.approval_sha256,
                 "approved_documentary_file_changed")
    approval = core.read(folder / "approval.json")
    channel = approval.get("channel")
    core.require(approval.get("quality_approved") is True and approval.get("job_id") == args.job_id
                 and channel in CHANNELS, "documentary_approval_invalid")
    core.require(core.sha(folder / "metadata.json") == approval.get("metadata_sha256"),
                 "approved_metadata_changed")
    metadata = core.read(folder / "metadata.json")
    core.require(metadata.get("channel") == channel and metadata.get("language") == "en"
                 and metadata.get("is_short") is False, "documentary_target_metadata_changed")
    title = metadata.get("title")
    core.require(isinstance(title, str) and 0 < len(title) <= 100, "documentary_title_invalid")
    files = approval.get("files", {})
    pins = {"approval.json": args.approval_sha256}
    for kind, name in (("video", "video.mp4"), ("subtitles", "subtitles.srt")):
        value = files.get(kind, {}).get("sha256", "")
        core.require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None,
                     "approved_media_fingerprint_missing")
        pins[name] = value
    output = core.safe(PUBLICATIONS / args.job_id)
    receipt_path = output / "youtube-receipt.json"
    saved = core.read(receipt_path) if receipt_path.is_file() else {}
    if args.resume_existing:
        core.require(isinstance(args.video_id, str)
                     and re.fullmatch(r"[A-Za-z0-9_-]{11}", args.video_id) is not None
                     and saved.get("video_id") == args.video_id,
                     "saved_video_id_required_no_new_upload")
    tags = args.tag or metadata.get("tags", [])
    core.require(isinstance(tags, list) and all(isinstance(t, str) and 0 < len(t) <= 100 for t in tags)
                 and sum(len(t) + 3 for t in tags) <= 500, "youtube_tags_invalid")
    core.JOB, core.BASE, core.OUT = args.job_id, folder, output
    core.CHANNEL, core.CHANNEL_ID = channel, CHANNELS[channel]
    core.TITLE, core.PINS, core.TAGS = title, pins, list(tags)
    core.THUMBNAIL_URL, core.RESUME_VIDEO_ID = args.thumbnail_url, args.video_id
    # Retain the exact name of Chrome Dome's already-published caption track.
    core.CAPTION_NAME = ("English - Chrome Dome" if args.job_id == LEGACY_CHROME_DOME else "English")
    core.no_duplicate = duplicate_check
    return core.preflight()


def main(argv=None):
    args = arguments(argv)
    snippet = configure(args)
    if args.inspect:
        core.emit(state="checked", job_id=args.job_id, channel=core.CHANNEL, title=snippet["title"],
                  ai_requests=0, video_uploads=0, publication="not_requested")
        return
    original = sys.argv
    try:
        sys.argv = [original[0], "--resume-existing" if args.resume_existing else "--publish"]
        core.main()
    finally:
        sys.argv = original


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        code = str(exc) if isinstance(exc, core.Blocked) else "youtube_publication_" + type(exc).__name__
        core.emit(state="blocked", error_code=code)
        raise SystemExit(2)
