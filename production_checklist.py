"""Production checklists for @Stunning-Revelations Shorts pipeline.

Two checkpoints:
  - pre-generation: validates the idea before spending API credits
  - pre-publish: validates the finished Short before upload
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any


def _load_strategy():
    try:
        from channel_strategy import get_channel_strategy
        return get_channel_strategy()
    except ImportError:
        return {}


def _load_recent_titles(daily_shorts_dir: str | Path | None = None) -> set[str]:
    titles: set[str] = set()
    base = Path(daily_shorts_dir) if daily_shorts_dir else Path(__file__).resolve().parent / "daily_shorts"
    if not base.exists():
        return titles
    for folder in base.iterdir():
        if not folder.is_dir():
            continue
        meta = folder / "youtube_metadata.json"
        if meta.exists():
            try:
                with open(meta, "r", encoding="utf-8") as f:
                    data = json.load(f)
                t = (data.get("title") or "").strip().lower()
                if t:
                    titles.add(t)
            except Exception:
                pass
    return titles


def run_pre_generation_checklist(
    idea: dict[str, Any],
    daily_shorts_dir: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Validate an idea before committing to full generation.

    Returns a list of check results:
        [{"check": str, "passed": bool, "message": str}, ...]
    """
    results: list[dict[str, Any]] = []
    strategy = _load_strategy()

    category = (idea.get("category") or "").strip()
    all_cats = [c.get("name", "") for c in strategy.get("categories", [])]

    if all_cats:
        cat_lower = category.lower()
        passed = any(
            cat_lower == c.lower() or cat_lower in c.lower() or c.lower() in cat_lower
            for c in all_cats
        )
        results.append({
            "check": "category_valid",
            "passed": passed,
            "message": f"Category '{category}' {'matches' if passed else 'does NOT match any'} channel profile categories.",
        })
    else:
        results.append({"check": "category_valid", "passed": True, "message": "No categories configured — skipped."})

    title = (idea.get("title") or "").strip()
    if title:
        used = _load_recent_titles(daily_shorts_dir)
        duplicate = title.lower() in used
        results.append({
            "check": "title_not_duplicate",
            "passed": not duplicate,
            "message": f"Title '{ title[:50] }...' {'is a DUPLICATE' if duplicate else 'is unique'}.",
        })

    topic = (idea.get("title") or idea.get("topic") or "").strip()
    if len(topic) < 10:
        results.append({"check": "topic_length", "passed": False, "message": f"Topic too short ({len(topic)} chars)."})
    else:
        results.append({"check": "topic_length", "passed": True, "message": "Topic length OK."})

    return results


def run_pre_publish_checklist(
    storyboard: dict[str, Any],
    video_path: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Validate a finished Short before publishing.

    Returns a list of check results:
        [{"check": str, "passed": bool, "message": str}, ...]
    """
    results: list[dict[str, Any]] = []
    strategy = _load_strategy()
    shorts_rules = strategy.get("shorts_rules", {})
    hard_limit = float(shorts_rules.get("hard_limit", 60))

    if video_path and os.path.exists(video_path):
        results.append({"check": "video_exists", "passed": True, "message": "Video file exists."})
        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        results.append({
            "check": "video_size",
            "passed": size_mb > 0.1,
            "message": f"Video size: {size_mb:.1f} MB.",
        })
    else:
        results.append({"check": "video_exists", "passed": False, "message": f"Video NOT found: {video_path}"})

    audio_path = storyboard.get("audio_path")
    if audio_path and os.path.exists(str(audio_path)):
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(str(audio_path))
            duration_s = len(audio) / 1000.0
            ok = duration_s <= hard_limit
            results.append({
                "check": "duration_under_limit",
                "passed": ok,
                "message": f"Audio duration: {duration_s:.1f}s (limit: {hard_limit}s){'.' if ok else ' — EXCEEDS LIMIT!'}",
            })
        except Exception as e:
            results.append({"check": "duration_under_limit", "passed": True, "message": f"Could not measure duration: {e}"})
    else:
        results.append({"check": "duration_under_limit", "passed": True, "message": "Audio not found — skipped duration check."})

    segments = storyboard.get("segments", [])
    images_ok = True
    missing = 0
    for seg in segments:
        img = seg.get("image_path")
        if img and not os.path.exists(str(img)):
            images_ok = False
            missing += 1
    results.append({
        "check": "all_images_exist",
        "passed": images_ok,
        "message": f"All segment images present." if images_ok else f"{missing} segment image(s) missing.",
    })

    script = storyboard.get("script", "")
    if script:
        try:
            from channel_strategy import validate_hook
            first_sentence = script.split(".")[0].strip() if "." in script else script[:100]
            ok, msg = validate_hook(first_sentence)
            results.append({"check": "hook_valid", "passed": ok, "message": msg})
        except ImportError:
            results.append({"check": "hook_valid", "passed": True, "message": "Hook validation skipped (channel_strategy not available)."})
    else:
        results.append({"check": "hook_valid", "passed": False, "message": "No script found in storyboard."})

    cf = storyboard.get("cover_frame")
    has_cf = cf is not None and cf.get("cover_text")
    results.append({
        "check": "cover_frame_present",
        "passed": has_cf,
        "message": f"Cover frame: '{cf.get('cover_text', '')}'" if has_cf else "No cover frame in storyboard.",
    })

    meta = metadata or {}
    title = (meta.get("title") or "").strip()
    if title:
        ok = len(title) <= 70
        results.append({
            "check": "title_length",
            "passed": ok,
            "message": f"Title length: {len(title)} chars{' (over 70!)' if not ok else '.'}",
        })
    else:
        results.append({"check": "title_length", "passed": True, "message": "No metadata title to check."})

    script_meta = storyboard.get("script_metadata") or {}
    has_meta = bool(script_meta.get("hook_pattern") or script_meta.get("category"))
    results.append({
        "check": "script_metadata",
        "passed": has_meta,
        "message": f"Script metadata: {', '.join(f'{k}={v}' for k,v in script_meta.items())}" if has_meta else "No structured script metadata.",
    })

    return results


def format_checklist(results: list[dict[str, Any]], header: str = "Checklist") -> str:
    lines = [f"--- {header} ---"]
    all_pass = True
    for r in results:
        icon = "PASS" if r["passed"] else "FAIL"
        if not r["passed"]:
            all_pass = False
        lines.append(f"  [{icon}] {r['check']}: {r['message']}")
    verdict = "ALL CHECKS PASSED" if all_pass else "SOME CHECKS FAILED"
    lines.append(f"  => {verdict}")
    return "\n".join(lines)


__all__ = [
    "run_pre_generation_checklist",
    "run_pre_publish_checklist",
    "format_checklist",
]
