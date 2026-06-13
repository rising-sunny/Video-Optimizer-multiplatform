"""Short-to-Long expansion tracker for @Stunning-Revelations.

Identifies which Shorts have the highest potential for expansion into
8-12 minute long-form videos, combining local storyboard metadata with
optional YouTube performance metrics.

Usage:
    python short_to_long_tracker.py              # top 5 candidates
    python short_to_long_tracker.py --top 10     # top 10
    python short_to_long_tracker.py --outline 1  # generate outline for #1 candidate
"""

from __future__ import annotations

import json
import os
import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


PROJECT_DIR = Path(__file__).resolve().parent
DAILY_SHORTS_DIR = PROJECT_DIR / "daily_shorts"
EXPANSION_CACHE_PATH = DAILY_SHORTS_DIR / "expansion_candidates.json"


def _load_local_shorts() -> list[dict[str, Any]]:
    shorts: list[dict[str, Any]] = []
    if not DAILY_SHORTS_DIR.exists():
        return shorts
    for folder in sorted(DAILY_SHORTS_DIR.iterdir()):
        if not folder.is_dir():
            continue
        sb_path = folder / "storyboard.json"
        summary_path = folder / "summary.json"
        if not sb_path.exists():
            continue
        try:
            with open(sb_path, "r", encoding="utf-8") as f:
                sb = json.load(f)
            summary = {}
            if summary_path.exists():
                with open(summary_path, "r", encoding="utf-8") as f:
                    summary = json.load(f)
            shorts.append({
                "folder": str(folder),
                "folder_name": folder.name,
                "topic": sb.get("topic") or summary.get("topic", ""),
                "category": sb.get("category") or summary.get("category", ""),
                "script": sb.get("script", ""),
                "script_metadata": sb.get("script_metadata", {}),
                "cover_frame": sb.get("cover_frame"),
                "video_path": summary.get("video_path"),
                "metadata": summary.get("metadata", {}),
                "generated_at": summary.get("generated_at", ""),
            })
        except Exception:
            continue
    return shorts


def _fetch_youtube_metrics(channel_id: str = None) -> dict[str, dict[str, Any]]:
    try:
        from youtube_channel_analyzer import YouTubeChannelAnalyzer
        handle = None
        if not channel_id:
            try:
                from channel_strategy import get_channel_strategy
                identity = get_channel_strategy().get("channel_identity", {})
                channel_id = identity.get("channel_id")
                handle = identity.get("channel_handle")
            except ImportError:
                pass
        analyzer = YouTubeChannelAnalyzer(channel_id=channel_id, channel_handle=handle)
        videos = analyzer.get_channel_videos(max_results=100)
        return {v["title"].strip().lower(): v for v in videos}
    except Exception:
        return {}


def _match_youtube_data(short: dict, yt_lookup: dict) -> dict[str, Any]:
    title = (short.get("metadata", {}).get("title") or short.get("topic") or "").strip().lower()
    for suffix in ["", " #shorts"]:
        clean = title.replace(suffix, "").strip()
        if clean in yt_lookup:
            return yt_lookup[clean]
    for yt_title, data in yt_lookup.items():
        topic_lower = (short.get("topic") or "").lower()
        if topic_lower and (topic_lower in yt_title or yt_title in topic_lower):
            return data
    return {}


def _get_category_weight() -> dict[str, float]:
    try:
        from channel_strategy import get_channel_strategy
        cats = get_channel_strategy().get("categories", [])
        weights = {}
        for c in cats:
            name = c.get("name", "").lower()
            prio = c.get("priority", "MEDIUM").upper()
            weights[name] = 1.5 if prio == "HIGH" else 1.0
        return weights
    except ImportError:
        return {}


def score_short(short: dict, yt_data: dict, category_weights: dict) -> float:
    score = 0.0

    meta = short.get("script_metadata", {})
    if str(meta.get("long_form_potential", "")).upper() == "YES":
        score += 30.0
    if meta.get("long_form_angle"):
        score += 10.0
    if meta.get("hook_pattern"):
        score += 5.0

    cat = (short.get("category") or "").lower()
    cat_w = category_weights.get(cat, 1.0)
    score *= cat_w

    views = int(yt_data.get("views", 0))
    if views > 0:
        import math
        score += min(30.0, math.log10(max(1, views)) * 8)
    engagement = float(yt_data.get("engagement_rate", 0))
    if engagement > 0:
        score += min(15.0, engagement * 2)
    comments = int(yt_data.get("comments", 0))
    if comments >= 5:
        score += min(10.0, comments * 0.5)

    script = short.get("script", "")
    if len(script.split()) >= 100:
        score += 5.0

    return round(score, 2)


def get_expansion_candidates(
    limit: int = 5,
    fetch_youtube: bool = True,
) -> list[dict[str, Any]]:
    shorts = _load_local_shorts()
    if not shorts:
        return []

    yt_lookup = _fetch_youtube_metrics() if fetch_youtube else {}
    category_weights = _get_category_weight()

    scored: list[dict[str, Any]] = []
    for short in shorts:
        yt_data = _match_youtube_data(short, yt_lookup)
        s = score_short(short, yt_data, category_weights)
        scored.append({
            "topic": short["topic"],
            "category": short["category"],
            "folder": short["folder_name"],
            "score": s,
            "long_form_potential": short.get("script_metadata", {}).get("long_form_potential", "?"),
            "long_form_angle": short.get("script_metadata", {}).get("long_form_angle", ""),
            "series_fit": short.get("script_metadata", {}).get("series_fit", ""),
            "views": int(yt_data.get("views", 0)),
            "engagement_rate": round(float(yt_data.get("engagement_rate", 0)), 2),
            "yt_title": yt_data.get("title", ""),
            "script_excerpt": (short.get("script", "")[:200] + "...") if short.get("script") else "",
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    result = scored[:limit]

    try:
        DAILY_SHORTS_DIR.mkdir(parents=True, exist_ok=True)
        with open(EXPANSION_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": datetime.now().isoformat(),
                "candidates": result,
            }, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    return result


def generate_expansion_outline(
    short_data: dict[str, Any],
    target_minutes: int = 10,
) -> Optional[str]:
    script = short_data.get("script", "") or short_data.get("script_excerpt", "")
    topic = short_data.get("topic", "Unknown topic")
    category = short_data.get("category", "")
    angle = short_data.get("long_form_angle", "")

    prompt = f"""Role: Senior Content Strategist for a YouTube documentary channel about history, mysteries, and lost civilizations.

Task: Create a detailed expansion outline for a long-form video (target: {target_minutes} minutes) based on this successful Short.

SHORT TOPIC: {topic}
CATEGORY: {category}
EXPANSION ANGLE: {angle if angle else 'Choose the most compelling angle'}

ORIGINAL SHORT SCRIPT:
{script[:1500]}

OUTLINE REQUIREMENTS:
- Structure in 5-8 chapters with titles and estimated duration
- Each chapter must have: a hook/transition, core content, and a mini-cliffhanger
- Total runtime: approximately {target_minutes} minutes
- Maintain the dark documentary tone of @Stunning-Revelations
- Include specific research angles, historical sources, and lesser-known details to explore
- First 90 seconds must pose an "Unsolvable Mystery" or "Life-or-Death Question"
- End with a question that invites watching another related video

FORMAT:
## Video Title (under 70 characters)

### Chapter 1: [Title] (0:00 - X:XX)
- Hook: ...
- Content: ...
- Transition: ...

### Chapter 2: ...
(continue for all chapters)

### Research Notes
- Key sources to investigate
- Experts or documents to reference
"""

    try:
        from ai_factory import AIFactory
        client = AIFactory.get_instance().get_llm_client()
        if hasattr(client, 'backend'):
            result = client.backend._generate(prompt, max_tokens=4096, task_type="script_quality")
        else:
            result = client._generate(prompt, max_tokens=4096, task_type="script_quality")
        if result and not str(result).startswith("ERROR"):
            return result
    except Exception as e:
        print(f"[!] Outline generation failed: {e}")

    return None


def format_candidates_report(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "No expansion candidates found."
    lines = [
        "=== SHORT-TO-LONG EXPANSION CANDIDATES ===",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]
    for i, c in enumerate(candidates, 1):
        lines.append(f"#{i}  Score: {c['score']:.1f}")
        lines.append(f"    Topic: {c['topic']}")
        lines.append(f"    Category: {c['category']}")
        lines.append(f"    Long-form: {c['long_form_potential']} | Angle: {c.get('long_form_angle', '-')}")
        if c.get("series_fit") and c["series_fit"].upper() != "NONE":
            lines.append(f"    Series: {c['series_fit']}")
        if c.get("views"):
            lines.append(f"    YT Views: {c['views']:,} | Engagement: {c['engagement_rate']:.1f}%")
        lines.append(f"    Folder: {c['folder']}")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Short-to-Long expansion tracker")
    parser.add_argument("--top", type=int, default=5, help="Number of top candidates")
    parser.add_argument("--outline", type=int, default=None,
                        help="Generate outline for candidate #N (1-based)")
    parser.add_argument("--no-youtube", action="store_true",
                        help="Skip YouTube API metrics")
    args = parser.parse_args()

    print("Scanning local Shorts...")
    candidates = get_expansion_candidates(
        limit=max(args.top, args.outline or 0),
        fetch_youtube=not args.no_youtube,
    )

    print(format_candidates_report(candidates))

    if args.outline is not None:
        idx = args.outline - 1
        if 0 <= idx < len(candidates):
            c = candidates[idx]
            print(f"\nGenerating expansion outline for #{args.outline}: {c['topic']}...")
            short_folder = DAILY_SHORTS_DIR / c["folder"]
            sb_path = short_folder / "storyboard.json"
            full_data = dict(c)
            if sb_path.exists():
                with open(sb_path, "r", encoding="utf-8") as f:
                    sb = json.load(f)
                full_data["script"] = sb.get("script", "")
            outline = generate_expansion_outline(full_data)
            if outline:
                print("\n" + outline)
                outline_path = short_folder / "expansion_outline.md"
                with open(outline_path, "w", encoding="utf-8") as f:
                    f.write(outline)
                print(f"\nOutline saved: {outline_path}")
            else:
                print("Failed to generate outline.")
        else:
            print(f"Invalid candidate number: {args.outline} (max: {len(candidates)})")


if __name__ == "__main__":
    main()
