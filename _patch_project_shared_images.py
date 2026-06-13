"""One-shot patch for the Las_Guerras_Pùnicas project (and reusable for similar cases).

Symptom: project was generated with images_per_segment_ratio > 1 (e.g. 1 image
per 2 segments). The legacy _restore_media_paths dedup wiped the shared
image_path from follower segments, so timeline shows only odd segments with images.

Fix: for each segment without image_path, look backward to the nearest segment
that HAS an image_path, and copy it. Only does this if there's no segment with
a different image_path closer (i.e. respects natural group boundaries).

Idempotent: re-running on an already-patched project is a no-op.
"""
import json
import os
import shutil
import sys
import time


def patch_project(project_json_path: str, dry_run: bool = False) -> dict:
    """Patch a single project.json. Returns stats dict."""
    with open(project_json_path, encoding='utf-8') as fh:
        data = json.load(fh)

    storyboard = data.get('storyboard') or data
    segments = storyboard.get('segments') or []
    if not segments:
        return {"error": "no segments found", "patched": 0, "total": 0}

    total = len(segments)
    before_with_image = sum(1 for s in segments if s.get('image_path'))

    # Forward propagation: each segment without image_path inherits from the most
    # recent segment that HAS image_path. We deliberately do NOT cross group
    # boundaries — but since we don't know the group structure, we use a simple
    # rule: a segment without an image inherits from the immediately previous
    # segment that has one. This handles ratio=2 (odd-leader pattern) cleanly.
    last_image_path = None
    last_image_source = None
    patched = 0
    for seg in segments:
        ip = seg.get('image_path')
        if ip:
            last_image_path = ip
            last_image_source = seg.get('image_source')
        elif last_image_path:
            seg['image_path'] = last_image_path
            if last_image_source and not seg.get('image_source'):
                seg['image_source'] = last_image_source
            patched += 1

    after_with_image = sum(1 for s in segments if s.get('image_path'))

    stats = {
        "total": total,
        "before_with_image": before_with_image,
        "after_with_image": after_with_image,
        "patched": patched,
        "dry_run": dry_run,
    }

    if not dry_run and patched > 0:
        # Backup
        ts = time.strftime("%Y%m%d_%H%M%S")
        backup = project_json_path + f".backup_{ts}.json"
        shutil.copy2(project_json_path, backup)
        stats["backup"] = backup

        # Persist
        with open(project_json_path, "w", encoding='utf-8') as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)

    return stats


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in sys.argv

    if args:
        target = args[0]
    else:
        target = os.path.join(
            "projects",
            "Las_Guerras_Pùnicas_20260521_231735.json",
            "project.json",
        )

    if not os.path.isfile(target):
        print(f"Project not found: {target}")
        sys.exit(2)

    print(f"Patching {'(dry-run) ' if dry_run else ''}{target}")
    stats = patch_project(target, dry_run=dry_run)

    print()
    print("Stats:")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    if "error" in stats:
        sys.exit(1)


if __name__ == "__main__":
    main()
