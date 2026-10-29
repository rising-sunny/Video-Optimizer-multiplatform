"""Read-only export of saved quality reports and contact sheets; no AI/network."""
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

sys.dont_write_bytecode = True
BATCH = "fa402b8286c149e698875a48b471977c"
RUNTIME = Path("/home/videoagent/video-automation/runtime")
STATE = Path("/var/lib/video-agent-prepare/catarsis") / BATCH
CHANNELS = ("stunning-facts-of-history", "stunning-revelations")
NAMES = (
    "editorial-plan.json", "project.json", "metadata.json", "qa.json",
    "deepseek-text-review.json", "visual-review.json", "clip-motion.json",
    "media-mode.json", "black-media-check.json", "catarsis-style-evidence.json",
    "platform-preflight.json", "asset-credits.json", "sources.json", "blocked.json",
    "thumbnail-layout.json"
)

def safe(path):
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise RuntimeError("diagnostic_symlink_rejected")
    return path

def load(path):
    raw = safe(path).read_bytes()
    if len(raw) > 4 * 1024 * 1024:
        raise RuntimeError("diagnostic_json_too_large")
    return json.loads(raw)

def redact(value):
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[oculto]", value)
        value = re.sub(r"(?i)Bearer\s+[^\s\"<>]+", "Bearer [oculto]", value)
        return re.sub(r"(?i)([?&](?:token|api_key|secret|signature|x-amz-signature)=)[^\s&\"<>]+", r"\1[oculto]", value)
    return value

status = load(STATE / "status.json")
if status.get("state") not in ("ready", "partial", "blocked", "interrupted"):
    raise SystemExit("El lote sigue activo; espera a que termine antes de exportar.")
report = dict(batch_id=BATCH, read_only=True, ai_requests=0, network_requests=0,
              state=status, channels={})
images = []
for channel in CHANNELS:
    folder = RUNTIME / "manual-catarsis" / BATCH / channel
    ledger = RUNTIME / "deepseek-ledger" / "catarsis" / BATCH / channel
    result = dict(files={}, sha256={})
    report["channels"][channel] = result
    for name in NAMES:
        path = folder / name
        if path.is_file():
            result["files"][name] = load(path)
            result["sha256"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(folder.glob("license-*.json")):
        if re.fullmatch(r"license-[0-9]+\.json", path.name):
            result["files"][path.name] = load(path)
    result["provider_reviews"] = {}
    for path in sorted(ledger.glob("vision-*.json")):
        if re.fullmatch(r"vision-[a-f0-9]{64}\.json", path.name):
            result["provider_reviews"][path.name] = load(path)
    for path in sorted(ledger.glob("handoff-*.json")):
        value = load(path)
        if isinstance(value, dict) and isinstance(value.get("checks"), dict):
            result["provider_reviews"][path.name] = value
    if (ledger / "budget.json").is_file():
        budget = load(ledger / "budget.json")
        result["budget"] = {key: budget.get(key) for key in ("counts", "estimated_usd", "pending")}
    video = folder / "video.mp4"
    if video.is_file():
        digest = hashlib.sha256()
        with safe(video).open("rb") as stream:
            while data := stream.read(1024 * 1024):
                digest.update(data)
        result["video"] = dict(bytes=video.stat().st_size, sha256=digest.hexdigest())
    for path in sorted(folder.glob("review-sheet-*.jpg")):
        images.append((safe(path), channel + "/" + path.name))
    for name in ("style-transitions.jpg", "thumbnail.jpg"):
        path = folder / name
        if path.is_file():
            images.append((safe(path), channel + "/" + name))

if sum(path.stat().st_size for path, _ in images) > 24 * 1024 * 1024:
    raise SystemExit("Las hojas superan el límite de exportación.")
with zipfile.ZipFile(sys.stdout.buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    archive.writestr("diagnostico.json", json.dumps(redact(report), ensure_ascii=False, indent=2))
    for path, name in images:
        archive.write(path, name)
