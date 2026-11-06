#!/usr/bin/env python3
"""Persist corrected workflow sources and tools; never generate or publish."""
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import tempfile

BUNDLE = Path(__file__).resolve().parent
REPO = Path("/home/videoagent/Video-Optimizer-multiplatform")
OPS = Path("/home/videoagent/video-automation/ops/documentary")
ROOT = Path("/opt/video-agent-mcp")
RELEASE = "workflow-consolidated-v47-20261106"
MARKER = "## Video Automation workflow corrections (2026-11-06)"


def safe(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise RuntimeError("workflow_symlink_rejected")
    return path


def digest(content):
    return hashlib.sha256(content).hexdigest()


def atomic(path, content, mode=0o644, owner=None):
    path = safe(path)
    missing = []
    directory = path.parent
    while not directory.exists():
        missing.append(safe(directory))
        directory = directory.parent
    directory_mode = 0o755 if mode & 0o044 else 0o700
    for directory in reversed(missing):
        directory.mkdir(mode=directory_mode)
        directory.chmod(directory_mode)  # Preserve readability under umask 077.
        if owner is not None:
            os.chown(directory, *owner)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".workflow-")
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            if owner is not None:
                os.fchown(stream.fileno(), *owner)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def module_names(root):
    """Inspect the declared source list as data, without importing the runtime."""
    tree = ast.parse(safe(root / "documentary_common.py").read_text())
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "MODULES" for t in node.targets))
    values = ast.literal_eval(assignment.value)
    names = {n for n in values if isinstance(n, str) and re.fullmatch(r"[A-Za-z0-9_]+\.py", n)}
    names.add("documentary_common.py")
    names.update(p.name for p in root.glob("chrome_dome_*.py"))
    return sorted(names)


def snapshot_runtime(root, destination, expected):
    names = set(module_names(root)) | set(expected)
    observed = {}
    missing = []
    for name in sorted(names):
        if not re.fullmatch(r"[A-Za-z0-9_]+\.py", name):
            raise RuntimeError("workflow_snapshot_path_invalid")
        path = safe(root / name)
        if not path.is_file():
            missing.append(name)
            continue
        content = path.read_bytes()
        atomic(destination / name, content, mode=0o600)
        observed[name] = digest(content)
    drift = [name for name, fingerprint in expected.items() if observed.get(name) != fingerprint]
    return dict(files=observed, missing=missing, reference_differences=drift,
                compared_reference_modules=len(expected),
                matched_reference_modules=len(expected) - len(drift))


def agent_instructions(existing):
    if MARKER in existing:
        return existing
    return existing.rstrip() + "\n\n" + MARKER + "\n\n" + (
        "Before generation, recovery, music, rendering, subtitles or publication work, read "
        "`docs/VIDEO_AUTOMATION_CORRECTIONS.md`. Reuse the permanent publisher in "
        "`automation/documentary/publication/` and the installed "
        "`/usr/local/sbin/video-documentary-youtube` entrypoint for authorized uploads. "
        "Preserve budgets, evidence, narration/SRT timing and remote IDs; do not replay "
        "topic-specific recoveries on other jobs. Never commit credentials, signed media "
        "URLs or resumable-session URIs. Installing this archive does not publish or generate.\n")


def repository_path(value):
    relative = Path(value)
    allowed = value in ("AGENTS.md", "docs/VIDEO_AUTOMATION_CORRECTIONS.md") or value.startswith("automation/documentary/")
    if not allowed or relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError("workflow_repository_path_invalid")
    return relative


def targets(payload):
    changes = {}
    for value in payload:
        relative = repository_path(value)
        content = safe(BUNDLE / "repo" / relative).read_bytes()
        target = safe(REPO / relative)
        if value == "AGENTS.md" and target.exists():
            content = agent_instructions(target.read_text()).encode()
        changes[target] = (content, 0o644, "videoagent")
        prefix = Path("automation/documentary")
        if relative.is_relative_to(prefix):
            tail = relative.relative_to(prefix)
            changes[safe(OPS / tail)] = (content, 0o644, "root")
    changes[OPS / "VIDEO_AUTOMATION_CORRECTIONS.md"] = (
        (BUNDLE / "repo/docs/VIDEO_AUTOMATION_CORRECTIONS.md").read_bytes(), 0o644, "root")
    changes[Path("/usr/local/sbin/video-documentary-youtube")] = (
        (BUNDLE / "repo/automation/documentary/publication/video-documentary-youtube").read_bytes(), 0o755, "root")
    return changes


def persist(changes, backup, video_owner):
    originals = {}
    for index, target in enumerate(changes):
        target = safe(target)
        if target.exists():
            info = target.stat()
            content = target.read_bytes()
            originals[target] = (content, info.st_mode & 0o777, (info.st_uid, info.st_gid))
            atomic(backup / "previous" / f"{index:04d}.bin", content, mode=0o600)
        else:
            originals[target] = None
    atomic(backup / "previous-index.json", json.dumps(
        {str(path): {"existed": value is not None, "sha256": digest(value[0]) if value else None}
         for path, value in originals.items()}, indent=2).encode(), mode=0o600)
    touched = []
    try:
        for target, (content, mode, principal) in changes.items():
            before = originals[target]
            if before is not None and before[0] == content and before[1] == mode:
                continue
            touched.append(target)
            owner = video_owner if principal == "videoagent" else (0, 0)
            atomic(target, content, mode=mode, owner=owner)
        for target, (content, mode, _) in changes.items():
            if safe(target).read_bytes() != content or (target.stat().st_mode & 0o777) != mode:
                raise RuntimeError("workflow_installed_file_verification_failed")
    except Exception:
        for target in reversed(touched):
            before = originals[target]
            if before is None:
                target.unlink(missing_ok=True)
            else:
                atomic(target, before[0], before[1], before[2])
        raise
    return {str(path): digest(value[0]) for path, value in changes.items()}


def main():
    if os.geteuid() != 0:
        raise RuntimeError("workflow_install_root_required")
    os.umask(0o077)
    manifest = json.loads(safe(BUNDLE / "manifest.json").read_text())
    for name, expected in manifest["files"].items():
        relative = repository_path(name)
        if digest(safe(BUNDLE / "repo" / relative).read_bytes()) != expected:
            raise RuntimeError("workflow_delivery_hash_changed")
    publication = BUNDLE / "repo/automation/documentary/publication"
    tests = BUNDLE / "repo/automation/documentary/tests"
    result = subprocess.run(["runuser", "-u", "videoagent", "--", "env", "PYTHONDONTWRITEBYTECODE=1",
        "PYTHONPATH=" + str(publication) + ":" + str(BUNDLE / "repo/automation/documentary"),
        str(REPO / ".venv/bin/python"), "-B", "-m", "unittest",
        "discover", "-s", str(tests), "-q"], capture_output=True, text=True, timeout=90)
    if result.returncode:
        print(result.stdout[-2000:])
        print(result.stderr[-4000:])
        raise RuntimeError("workflow_offline_tests_failed")
    print(json.dumps(dict(offline_tests="passed", ai_requests=0)), flush=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = safe(Path("/var/backups/video-agent-mcp") / (RELEASE + "-" + stamp))
    backup.mkdir(parents=True, mode=0o700)
    expected = json.loads((BUNDLE / "repo/automation/documentary/runtime-reference-sha256.json").read_text())
    snapshot = snapshot_runtime(ROOT, backup / "installed-runtime", expected)
    atomic(backup / "runtime-manifest.json", json.dumps(snapshot, indent=2).encode(), mode=0o600)
    who = pwd.getpwnam("videoagent")
    files = persist(targets(manifest["files"]), backup, (who.pw_uid, who.pw_gid))
    receipt = dict(state="saved", release=RELEASE, saved_at=stamp, backup=str(backup),
        permanent_publisher="/usr/local/sbin/video-documentary-youtube",
        repository=str(REPO), persisted_files=files,
        runtime_snapshot_python_files=len(snapshot["files"]),
        runtime_missing_sources=snapshot["missing"],
        runtime_reference_differences=snapshot["reference_differences"],
        runtime_reference_matches=snapshot["matched_reference_modules"],
        runtime_reference_compared=snapshot["compared_reference_modules"],
        ai_requests=0, generation_requests=0, publication_requests=0,
        generation_modules_replaced=0, daily_timers_modified=False)
    atomic(OPS / "installation-receipt.json", json.dumps(receipt, indent=2).encode(), mode=0o644)
    atomic(backup / "installation-receipt.json", json.dumps(receipt, indent=2).encode(), mode=0o600)
    print(json.dumps({k: v for k, v in receipt.items() if k != "persisted_files"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        code = str(exc) if isinstance(exc, RuntimeError) else "workflow_install_" + type(exc).__name__
        print(json.dumps(dict(state="blocked", error_code=code, generation_requests=0, publication_requests=0)), flush=True)
        raise SystemExit(2)
