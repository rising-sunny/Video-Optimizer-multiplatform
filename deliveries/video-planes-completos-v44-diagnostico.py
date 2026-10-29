"""Export the three existing plans and read-only validation errors; no AI or writes."""
import copy
import hashlib
import json
from pathlib import Path
import re
import socket
import sys
import traceback
from datetime import datetime, timezone

sys.dont_write_bytecode = True
sys.path[:0] = ["/tmp/video-recuperacion-shorts-v44-v2", "/opt/video-agent-mcp"]

def forbidden(*args, **kwargs):
    raise RuntimeError("diagnostic_network_or_ai_forbidden")

socket.socket.connect = forbidden
socket.create_connection = forbidden
socket.getaddrinfo = forbidden

import deepseek_runtime as runtime
runtime.Client.request = forbidden
runtime.Budget.reserve = forbidden
import shorts_handoff as syntax
import shorts_handoff_resume as recovery

BATCH = "fa402b8286c149e698875a48b471977c"
RUNTIME = Path("/home/videoagent/video-automation/runtime")
report = dict(batch_id=BATCH, checked_at=datetime.now(timezone.utc).isoformat(),
              read_only=True, ai_requests=0, network_requests=0, channels={})

def load(path):
    if path.is_symlink():
        raise RuntimeError("diagnostic_symlink_rejected")
    content = path.read_bytes()
    if len(content) > 2 * 1024 * 1024:
        raise RuntimeError("diagnostic_file_too_large")
    return json.loads(content)

def error(exc):
    return dict(type=type(exc).__name__, message=str(exc)[:1500],
                details=getattr(exc, "details", []),
                traceback=[dict(file=Path(frame.filename).name, line=frame.lineno,
                                function=frame.name)
                           for frame in traceback.extract_tb(exc.__traceback__)[-10:]])

def validation(job, value):
    try:
        recovered, receipt = recovery.validate_saved(job, copy.deepcopy(value))
        return dict(state="passed", duration_repair=receipt)
    except Exception as exc:
        return dict(state="blocked", **error(exc))

def attempt(function):
    try:
        return function()
    except Exception as exc:
        return dict(diagnostic_error=error(exc))

for channel in ("stunning-facts-of-history", "stunning-revelations"):
    job = RUNTIME / "manual-catarsis" / BATCH / channel
    ledger = RUNTIME / "deepseek-ledger" / "catarsis" / BATCH / channel
    data = dict(plans=[], job=attempt(lambda: load(job / "job.json")),
                style=attempt(lambda: load(job / "style-profile.json")),
                catalog=attempt(lambda: load(job / "shorts-media-v34.json")))
    report["channels"][channel] = data
    budget = attempt(lambda: load(ledger / "budget.json"))
    data["budget"] = {key: budget.get(key) for key in (
        "counts", "limits", "estimated_usd", "pending")}
    music = attempt(lambda: load(job / "music-input.json"))
    data["music"] = {"tracks": [{key: track.get(key) for key in (
        "title", "recording_id", "isrc", "artist", "provider")}
        for track in music.get("tracks", [])]}
    tools = attempt(lambda: load(ledger / "tools.json"))
    data["cached_factual_reads"] = [dict(
        url=row.get("request", {}).get("url"),
        result={key: row.get("result", {}).get(key) for key in ("state", "title", "content")},
        retrieved_at=row.get("retrieved_at"))
        for row in tools.values() if isinstance(row, dict) and row.get("kind") == "fetch"]
    if (job / "factual-sources-v41.json").is_file():
        data["factual_index"] = attempt(lambda: load(job / "factual-sources-v41.json"))
    for name in ("editorial-plan-autonomy-1.json", "editorial-plan.json"):
        path = job / name
        if not path.is_file() or path.is_symlink():
            continue
        try:
            saved = load(path)
            candidate = saved.get("plan", saved) if saved.get("action") == "rebuild" else saved
            data["plans"].append(dict(file=name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                      original=saved, validation=validation(job, candidate)))
        except Exception as exc:
            data["plans"].append(dict(file=name, error=error(exc)))
    if channel == "stunning-revelations":
        for path in sorted(ledger.glob("invalid-handoff-*.json")):
            if path.is_symlink():
                continue
            saved = load(path)
            if saved.get("output") != "editorial-plan.json":
                continue
            try:
                value, repairs = syntax.parse(saved["provider_content"])
                native = copy.deepcopy(value)
                nested = native.get("music", {})
                if isinstance(nested, dict):
                    for key, alias in (("music_title", "title"), ("music_recording_id", "recording_id")):
                        if key not in native and alias in nested:
                            native[key] = nested[alias]
                data["plans"].append(dict(file=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    original=value, syntax_repairs=repairs, validation=validation(job, native)))
            except Exception as exc:
                data["plans"].append(dict(file=path.name, error=error(exc)))

def redact(value):
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[oculto]", value)
        value = re.sub(r"(?i)Bearer\s+[^\s\"<>]+", "Bearer [oculto]", value)
        return re.sub(r"(?i)([?&](?:token|api_key|key|secret|signature|x-amz-signature)=)[^\s&\"<>]+", r"\1[oculto]", value)
    return value

print(json.dumps(redact(report), ensure_ascii=False, indent=2))
