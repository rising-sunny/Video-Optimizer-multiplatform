"""Weekly intelligence report for @Stunning-Revelations.

Aggregates local production data and optional YouTube metrics into a
structured JSON report. Highlights best/worst Shorts, winning hooks,
category performance, and expansion candidates.

Usage:
    python weekly_intelligence_report.py              # current week
    python weekly_intelligence_report.py --days 14    # last 14 days
"""

from __future__ import annotations

import json
import os
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional


PROJECT_DIR = Path(__file__).resolve().parent
DAILY_SHORTS_DIR = PROJECT_DIR / "daily_shorts"
REPORTS_DIR = DAILY_SHORTS_DIR / "reports"


def _load_local_shorts(since: Optional[datetime] = None) -> list[dict[str, Any]]:
    shorts: list[dict[str, Any]] = []
    if not DAILY_SHORTS_DIR.exists():
        return shorts
    for folder in sorted(DAILY_SHORTS_DIR.iterdir()):
        if not folder.is_dir() or folder.name == "reports":
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

            generated_at = summary.get("generated_at", "")
            if since and generated_at:
                try:
                    dt = datetime.fromisoformat(generated_at)
                    if dt < since:
                        continue
                except (ValueError, TypeError):
                    pass

            shorts.append({
                "folder": folder.name,
                "topic": sb.get("topic") or summary.get("topic", ""),
                "category": sb.get("category") or summary.get("category", ""),
                "script": sb.get("script", ""),
                "script_metadata": sb.get("script_metadata", {}),
                "cover_frame": sb.get("cover_frame"),
                "video_path": summary.get("video_path"),
                "metadata_title": (summary.get("metadata") or {}).get("title", ""),
                "generated_at": generated_at,
                "has_video": bool(summary.get("video_path")),
            })
        except Exception:
            continue
    return shorts


def _fetch_youtube_videos() -> list[dict[str, Any]]:
    try:
        from youtube_channel_analyzer import YouTubeChannelAnalyzer
        channel_id = None
        handle = None
        try:
            from channel_strategy import get_channel_strategy
            identity = get_channel_strategy().get("channel_identity", {})
            channel_id = identity.get("channel_id")
            handle = identity.get("channel_handle")
        except ImportError:
            pass
        analyzer = YouTubeChannelAnalyzer(channel_id=channel_id, channel_handle=handle)
        return analyzer.get_channel_videos(max_results=50)
    except Exception:
        return []


def _analyze_hooks(shorts: list[dict]) -> dict[str, Any]:
    pattern_counts: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0, "?": 0}
    for s in shorts:
        p = (s.get("script_metadata", {}).get("hook_pattern") or "?").upper()
        if p in pattern_counts:
            pattern_counts[p] += 1
        else:
            pattern_counts["?"] += 1
    return pattern_counts


def _analyze_categories(shorts: list[dict], yt_videos: list[dict]) -> list[dict]:
    yt_lookup: dict[str, dict] = {}
    for v in yt_videos:
        yt_lookup[v.get("title", "").strip().lower()] = v

    cat_stats: dict[str, dict] = {}
    for s in shorts:
        cat = s.get("category") or "Unknown"
        if cat not in cat_stats:
            cat_stats[cat] = {"count": 0, "total_views": 0, "total_engagement": 0.0, "titles": []}
        cat_stats[cat]["count"] += 1
        cat_stats[cat]["titles"].append(s.get("topic", ""))

        title = (s.get("metadata_title") or s.get("topic") or "").strip().lower()
        for key in [title, title.replace(" #shorts", "").strip()]:
            if key in yt_lookup:
                cat_stats[cat]["total_views"] += int(yt_lookup[key].get("views", 0))
                cat_stats[cat]["total_engagement"] += float(yt_lookup[key].get("engagement_rate", 0))
                break

    result = []
    for cat, stats in sorted(cat_stats.items(), key=lambda x: x[1]["total_views"], reverse=True):
        avg_engagement = (stats["total_engagement"] / stats["count"]) if stats["count"] else 0
        result.append({
            "category": cat,
            "shorts_produced": stats["count"],
            "total_views": stats["total_views"],
            "avg_engagement": round(avg_engagement, 2),
        })
    return result


def _find_best_worst(shorts: list[dict], yt_videos: list[dict]) -> dict[str, Any]:
    yt_lookup: dict[str, dict] = {}
    for v in yt_videos:
        yt_lookup[v.get("title", "").strip().lower()] = v

    scored = []
    for s in shorts:
        title = (s.get("metadata_title") or s.get("topic") or "").strip().lower()
        yt_data = yt_lookup.get(title) or yt_lookup.get(title.replace(" #shorts", "").strip(), {})
        views = int(yt_data.get("views", 0))
        engagement = float(yt_data.get("engagement_rate", 0))
        scored.append({
            "topic": s["topic"],
            "category": s["category"],
            "folder": s["folder"],
            "views": views,
            "engagement_rate": round(engagement, 2),
            "hook_pattern": s.get("script_metadata", {}).get("hook_pattern", "?"),
        })

    scored.sort(key=lambda x: x["views"], reverse=True)
    best = scored[:3] if scored else []
    worst = list(reversed(scored[-3:])) if len(scored) >= 3 else []
    return {"best": best, "worst": worst}


def _get_topic_suggestions(shorts: list[dict]) -> list[str]:
    try:
        from channel_strategy import get_channel_strategy
        strategy = get_channel_strategy()
        cats = strategy.get("categories", [])
        all_topics = {s.get("topic", "").lower() for s in shorts}

        suggestions = []
        for cat in cats:
            examples = cat.get("example_topics", [])
            for ex in examples:
                if ex.lower() not in all_topics:
                    suggestions.append(f"[{cat['name']}] {ex}")
        return suggestions[:10]
    except ImportError:
        return []


def generate_weekly_report(
    days: int = 7,
    fetch_youtube: bool = True,
) -> dict[str, Any]:
    since = datetime.now() - timedelta(days=days)
    all_shorts = _load_local_shorts()
    period_shorts = _load_local_shorts(since=since)
    yt_videos = _fetch_youtube_videos() if fetch_youtube else []

    hook_analysis = _analyze_hooks(period_shorts)
    category_analysis = _analyze_categories(period_shorts, yt_videos)
    best_worst = _find_best_worst(period_shorts, yt_videos)
    topic_suggestions = _get_topic_suggestions(all_shorts)

    expansion_candidates = []
    try:
        from short_to_long_tracker import get_expansion_candidates
        expansion_candidates = get_expansion_candidates(limit=5, fetch_youtube=fetch_youtube)
    except Exception:
        pass

    report = {
        "report_date": datetime.now().isoformat(),
        "period_days": days,
        "period_start": since.isoformat(),
        "total_shorts_all_time": len(all_shorts),
        "shorts_this_period": len(period_shorts),
        "shorts_with_video": sum(1 for s in period_shorts if s.get("has_video")),
        "youtube_videos_fetched": len(yt_videos),
        "hook_patterns": hook_analysis,
        "category_performance": category_analysis,
        "best_shorts": best_worst.get("best", []),
        "worst_shorts": best_worst.get("worst", []),
        "expansion_candidates": [
            {"topic": c["topic"], "score": c["score"], "angle": c.get("long_form_angle", "")}
            for c in expansion_candidates[:5]
        ],
        "topic_suggestions": topic_suggestions,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"weekly_{datetime.now().strftime('%Y-%m-%d')}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return report


def format_report(report: dict[str, Any]) -> str:
    lines = [
        "=" * 60,
        "  WEEKLY INTELLIGENCE REPORT — @Stunning-Revelations",
        "=" * 60,
        f"  Period: last {report['period_days']} days (since {report['period_start'][:10]})",
        f"  Shorts produced: {report['shorts_this_period']} (all time: {report['total_shorts_all_time']})",
        f"  With video: {report['shorts_with_video']}",
        f"  YouTube data: {'YES' if report['youtube_videos_fetched'] > 0 else 'NO'} ({report['youtube_videos_fetched']} videos)",
        "",
    ]

    lines.append("--- Hook Patterns Used ---")
    for pattern, count in report.get("hook_patterns", {}).items():
        if count > 0:
            lines.append(f"  Pattern {pattern}: {count}")
    lines.append("")

    lines.append("--- Category Performance ---")
    for cat in report.get("category_performance", []):
        views_str = f" | {cat['total_views']:,} views" if cat["total_views"] else ""
        lines.append(f"  {cat['category']}: {cat['shorts_produced']} Shorts{views_str}")
    lines.append("")

    if report.get("best_shorts"):
        lines.append("--- Best Shorts ---")
        for i, s in enumerate(report["best_shorts"], 1):
            lines.append(f"  #{i} {s['topic']} ({s['views']:,} views, {s['engagement_rate']:.1f}% eng)")
        lines.append("")

    if report.get("worst_shorts"):
        lines.append("--- Lowest Performing ---")
        for i, s in enumerate(report["worst_shorts"], 1):
            lines.append(f"  #{i} {s['topic']} ({s['views']:,} views)")
        lines.append("")

    if report.get("expansion_candidates"):
        lines.append("--- Top Expansion Candidates (Short-to-Long) ---")
        for i, c in enumerate(report["expansion_candidates"], 1):
            angle = f" — {c['angle']}" if c.get("angle") else ""
            lines.append(f"  #{i} {c['topic']} (score: {c['score']:.1f}){angle}")
        lines.append("")

    if report.get("topic_suggestions"):
        lines.append("--- Suggested Topics (not yet covered) ---")
        for t in report["topic_suggestions"][:5]:
            lines.append(f"  - {t}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Weekly intelligence report")
    parser.add_argument("--days", type=int, default=7, help="Period in days (default: 7)")
    parser.add_argument("--no-youtube", action="store_true", help="Skip YouTube API")
    args = parser.parse_args()

    print("Generating weekly intelligence report...")
    report = generate_weekly_report(days=args.days, fetch_youtube=not args.no_youtube)
    print(format_report(report))
    fname = f"weekly_{datetime.now().strftime('%Y-%m-%d')}.json"
    print(f"\nReport saved: {REPORTS_DIR / fname}")


if __name__ == "__main__":
    main()
