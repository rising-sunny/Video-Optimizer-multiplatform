#!/usr/bin/env python3
"""Continue one observed Chrome Dome job; no install, new job, quota reset or publication."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlsplit

JOB = "d1da2fe6dfb746e09694bb2129ff6f80"
REQUEST = "manual-chrome-dome-documentary-20261106-v1"
TOPIC = "Operation Chrome Dome: how B-52 crews sustained continuous nuclear-armed airborne alert during the Cold War. Ten-minute English documentary for Stunning Revelations. Follow documented stages of a typical mission: takeoff, crew endurance, KC-135 refueling, deterrence, accident risks and the 1968 shutdown. No invented crew, dialogue or launch orders; avoid retelling Goldsboro. Primary evidence: https://nsarchive.gwu.edu/document/21074-doc-1-thesacalertsystem1956-197 . Prioritize genuine moving B-52/KC-135 archival footage, verified photos and route maps; clearly date later context. Horizontal Catarsis: immediate hook, varied short scenes, restrained transitions/SFX, Epidemic documentary suspense and an epic rise under clear narration. Separate English SRT; user supplies thumbnail. Use economical DeepSeek text and one Codex visual review. Generation only."
REPAIR = "chrome-dome-verified-sources-20261106"
AUTH = REPAIR + ".json"
CLAIM = REPAIR + ".claimed"
BEFORE = dict(chat=8, search=2, fetch=2, invocations=1,
              input_tokens=106815, output_tokens=5209)
LIMITS = dict(chat=10, search=4, fetch=14, invocations=4,
              input_tokens=350000, output_tokens=24000)
REQUIRED = ("history-full.json", "history-editorial.json",
            "request-editorial.json", "voice-calibration.json", "media-catalog.json")
SEEDS = (
    "https://nsarchive.gwu.edu/document/21074-doc-1-thesacalertsystem1956-197",
    "https://www.airandspaceforces.com/article/0811dome/",
    "https://prologue.blogs.archives.gov/2021/01/22/brush-with-catastrophe-the-day-the-u-s-almost-nuked-itself/",
    "https://www.afgsc.af.mil/News/Article-Display/Article/454741/sac-during-the-13-days-of-the-cuban-missile-crisis/",
    "https://history.state.gov/historicaldocuments/frus1964-68v10/d108",
)

class Stop(RuntimeError):
    pass

def require(value, code):
    if not value:
        raise Stop(code)

def emit(**value):
    print(json.dumps(value, ensure_ascii=False), flush=True)

def manifest(c, root):
    c.safe_path(root)
    result = {}
    for path in sorted(root.rglob("*")):
        c.safe_path(path)
        if path.is_file():
            result[str(path.relative_to(root))] = c.sha(path)
    return result

def good_history(value):
    return (isinstance(value, dict) and value.get("history_review_complete") is True
            and value.get("duplicate") is False)

def preflight(c, rt, editor, planner):
    state = c.safe_path(c.STATE / JOB)
    folder = c.safe_path(c.JOBS / JOB)
    require(state.is_dir() and folder.is_dir(), "chrome_saved_job_missing")
    task, status = c.read(state / "request.json"), c.read(state / "status.json")
    require(task.get("job_id") == JOB and task.get("request_id") == REQUEST
            and task.get("topic") == TOPIC
            and task.get("channel") == "stunning-revelations"
            and task.get("minutes") == 10
            and task.get("horizontal_style") == "documentary-catarsis-v31"
            and task.get("thumbnail_mode") == "manual"
            and task.get("publication_allowed") is False,
            "chrome_original_request_changed")
    require(status.get("state") == "blocked"
            and status.get("error_code") ==
            "generation_dependency_deepseek_two_verified_sources_required",
            "chrome_requires_observed_source_block")
    require(not (state / "STOP").exists(), "documentary_cancelled")
    require(not (state / CLAIM).exists() and not (state / AUTH).exists(),
            "chrome_recovery_already_claimed")
    require(not any((folder / n).exists() for n in (
        "editorial-plan.json", "video.mp4", "approval.json", "publication.json",
        ".transport.json", "source-repair-binding-v41.json")),
        "chrome_output_or_other_recovery_exists")
    require(all((folder / n).is_file() for n in REQUIRED),
            "chrome_original_evidence_missing")
    require(c.read(folder / "history-full.json").get("complete") is True,
            "chrome_history_incomplete")
    ledger = c.safe_path(rt.RUNTIME / "deepseek-ledger" / "documentary" / JOB)
    require((ledger / "budget.json").is_file(), "chrome_original_budget_missing")
    budget = rt.read(ledger / "budget.json")
    require(budget.get("pending") is None and budget.get("counts") == BEFORE
            and len(budget.get("usage", [])) == 8
            and 0 < budget.get("estimated_usd", 1) < 0.05,
            "chrome_observed_budget_changed")
    require(rt.LIMITS == LIMITS and rt.MAX_ESTIMATE == 0.2,
            "chrome_configured_limits_changed")
    require(good_history(rt.read(ledger / "history-check.json")),
            "chrome_original_history_review_missing")
    # Confirm the exact cache used by the native editor; do not spend on deduplication again.
    dataset = editor.local_data(folder, "history-editorial.json")
    request = editor.local_data(folder, "request-editorial.json")
    ident = hashlib.sha256(editor.encode(dict(history=dataset, request=request)).encode()).hexdigest()
    history_cache = ledger / ("history-" + ident + ".json")
    require(history_cache.is_file() and good_history(rt.read(history_cache)),
            "chrome_exact_history_cache_missing")
    require("prepared_sources" in inspect.signature(planner.plan).parameters,
            "chrome_native_prepared_sources_unavailable")
    return state, folder, ledger, task, budget, history_cache

def prepare_sources(folder, ledger, sources, rt, guard):
    tools_path = ledger / "tools.json"
    tools = rt.read(tools_path) if tools_path.is_file() else {}
    selected = {}
    hosts = set()
    for url in SEEDS:
        guard()
        row = sources.cached(folder, url)
        if row is None:
            row = sources.import_cached_fetch(folder, url, tools)
        if row is None:
            row = sources.fetch_source(
                folder, url, guard,
                focus=("Chrome Dome", "24-Hour Missions", "refueling",
                       "crew", "airborne alert", "1968"))
        if row is None:
            continue
        require(row.get("url") == url and row.get("state") == "available"
                and isinstance(row.get("content"), str) and len(row["content"]) >= 350,
                "chrome_source_receipt_invalid")
        host = urlsplit(url).hostname.removeprefix("www.")
        if host not in hosts:
            selected[url] = row
            hosts.add(host)
        if len(selected) == 2:
            return selected
    raise Stop("chrome_two_independent_sources_unavailable")

def perform(c, rt, editor, planner, worker, sources):
    state, folder, ledger, task, budget, history_cache = preflight(c, rt, editor, planner)
    config = worker.dependencies()  # Local readiness only; no provider calls.
    created = datetime.now(timezone.utc)
    auth = dict(
        job_id=JOB, request_id=REQUEST, repair_id=REPAIR,
        request_sha256=c.sha(state / "request.json"),
        created_at=created.isoformat(),
        expires_at=(created + timedelta(hours=6)).isoformat(),
        code_sha256={n: c.sha(c.ROOT / n) for n in c.MODULES},
        original_files=manifest(c, folder), ledger_files=manifest(c, ledger),
        history_cache_sha256=c.sha(history_cache),
        budget_before=dict(budget["counts"]), paid_limits_increased=False,
        maximum_new_text_calls=2, maximum_visual_reviews=1, publication_allowed=False,
    )
    from publication_service import controls
    auth["controls"] = controls()
    # Never delete or reset the native worker claim or any provider ledger.
    c.save(state / AUTH, auth)
    auth_pin = c.sha(state / AUTH)
    with (state / CLAIM).open("x") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(c.now())
        stream.flush()
        os.fsync(stream.fileno())

    def guard():
        clock = datetime.now(timezone.utc)
        require(created <= clock < datetime.fromisoformat(auth["expires_at"]),
                "chrome_recovery_expired")
        require(not (state / "STOP").exists(), "documentary_cancelled")
        require(c.sha(state / AUTH) == auth_pin
                and c.sha(state / "request.json") == auth["request_sha256"]
                and controls() == auth["controls"]
                and all(c.sha(c.ROOT / n) == digest for n, digest in auth["code_sha256"].items()),
                "chrome_inputs_or_controls_changed")
        require(all(c.sha(folder / n) == auth["original_files"][n] for n in REQUIRED)
                and c.sha(history_cache) == auth["history_cache_sha256"],
                "chrome_preserved_evidence_changed")
        current = rt.read(ledger / "budget.json")["counts"]
        require(all(current[k] >= BEFORE[k] for k in BEFORE)
                and current["chat"] <= BEFORE["chat"] + 2
                and current["invocations"] <= BEFORE["invocations"] + 2
                and current["search"] == BEFORE["search"]
                and current["fetch"] == BEFORE["fetch"],
                "chrome_budget_reset_or_extra_call_rejected")
        require(not any((folder / n).exists() for n in ("publication.json", ".transport.json")),
                "chrome_publication_state_exists")

    def progress(phase, done=None, total=None):
        guard()
        value = c.read(state / "status.json")
        value.update(state="running", phase=phase, repair_id=REPAIR, error_code=None,
                     updated_at=c.now(), progress=dict(completed=done, total=total),
                     ai_usage=c.usage(folder))
        if (folder / "deepseek-usage.json").is_file():
            value["deepseek_budget"] = c.read(folder / "deepseek-usage.json")
        c.save(state / "status.json", value)
        if done is None or done % 10 == 0:
            emit(state="running", phase=phase, completed=done, total=total)

    guard()
    archive = c.safe_path(c.JOBS.parent / "manual-documentary-archive" / JOB / REPAIR)
    archive.mkdir(parents=True, mode=0o700, exist_ok=False)
    for root, name, expected in (
            (folder, "job", auth["original_files"]), (ledger, "ledger", auth["ledger_files"])):
        shutil.copytree(root, archive / name)
        require(manifest(c, archive / name) == expected, "chrome_backup_verification_failed")
    c.save(archive / "request.json", task)
    c.save(archive / "status-before.json", c.read(state / "status.json"))
    progress("preparing_factual_sources")
    prepared = prepare_sources(folder, ledger, sources, rt, guard)
    guard()
    emit(verified_sources=list(prepared), preparation_ai_requests=0)
    c.save(folder / "source-repair-binding-v41.json",
           dict(job_id=JOB, repair_id=REPAIR, request_sha256=auth["request_sha256"],
                text_calls_max=2, disable_extra_text_corrections=True))
    calibration = c.read(folder / "voice-calibration.json")
    config.update(length_scale=calibration["length_scale"], effective_target_wpm=140)
    progress("planning_from_saved_sources")
    plan = c.validate_plan(planner.plan(folder, task, prepared_sources=prepared))
    c.save(folder / "editorial-plan.json", plan)
    guard()
    worker.finish(JOB, task, folder, state, config, plan, guard, progress, auth["code_sha256"])
    require(c.read(state / "status.json").get("state") == "ready",
            "chrome_native_completion_not_ready")
    emit(state="ready", job_id=JOB, publication_allowed=False)

def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    sys.path.insert(0, "/opt/video-agent-mcp")
    import documentary_common as c
    import deepseek_runtime as rt
    import deepseek_editor as editor
    import documentary_ai as planner
    import documentary_worker as worker
    import documentary_sources as sources
    try:
        if args.check:
            preflight(c, rt, editor, planner)
            emit(state="checked", job_id=JOB, read_only=True, ai_requests=0,
                 remaining_text_calls=2, paid_limits_increased=False, publication_allowed=False)
        else:
            perform(c, rt, editor, planner, worker, sources)
    except Exception as exc:
        code = str(exc)
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,100}", code):
            code = "chrome_recovery_failed"
        state = c.STATE / JOB
        if args.resume and (state / CLAIM).is_file() and (state / AUTH).is_file():
            try:
                auth = c.read(state / AUTH)
                value = c.read(state / "status.json")
                if (auth.get("repair_id") == REPAIR
                        and c.sha(state / "request.json") == auth["request_sha256"]
                        and value.get("state") != "ready"):
                    value.update(state="blocked", phase="stopped", repair_id=REPAIR,
                                 error_code=code, updated_at=c.now(), ai_usage=c.usage(c.JOBS / JOB))
                    if (c.JOBS / JOB / "deepseek-usage.json").is_file():
                        value["deepseek_budget"] = c.read(c.JOBS / JOB / "deepseek-usage.json")
                    c.save(state / "status.json", value)
            except Exception:
                pass
        emit(state="blocked", job_id=JOB, error_code=code, publication_allowed=False)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
