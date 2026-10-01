"""Assignment slots and editable-plan timing (before the render's flash limiter)."""
from pathlib import Path


def media_slots(spec):
    kind = spec.get("kind")
    if kind == "split":
        return [("medias", i) for i in range(len(spec.get("medias") or [None] * 3))]
    if kind == "double":
        return [("media", None), ("media2", None)]
    if kind in ("media", "overlay", "impact"):
        return [("media", None)]
    return []


def slot_value(spec, slot):
    key, index = slot
    if index is None:
        return spec.get(key)
    values = spec.get(key) or []
    return values[index] if index < len(values) else None


def set_slot(spec, slot, value):
    key, index = slot
    if index is None:
        spec[key] = value
    else:
        values = list(spec.get(key) or [None] * 3)
        values.extend([None] * max(0, index + 1 - len(values)))
        values[index] = value
        spec[key] = values


def missing_slots(spec, media, *, check_files=True):
    missing = []
    for slot in media_slots(spec):
        index = slot_value(spec, slot)
        valid = type(index) is int and 0 <= index < len(media)
        if valid and check_files:
            try:
                valid = Path(media[index].get("file", "")).is_file()
            except (ValueError, OSError):
                valid = False
        if not valid:
            missing.append(slot)
    return missing


def assignment_summary(sequence, media):
    visual = [i for i, spec in enumerate(sequence) if media_slots(spec)]
    pending = {i: missing_slots(sequence[i], media) for i in visual}
    pending = {i: slots for i, slots in pending.items() if slots}
    return {"total": len(sequence), "visual": len(visual), "complete": len(visual) - len(pending),
            "pending": pending, "slots": sum(len(media_slots(sequence[i])) for i in visual),
            "missing": sum(len(slots) for slots in pending.values())}


def plan_timings(sequence, fps=30):
    """Cumulative frame rounding matches build_shots before flash adjustments."""
    result, seconds, previous = [], 0.0, 0
    for spec in sequence:
        seconds += max(0.0, float(spec.get("seconds", 0)))
        end = round(seconds * fps)
        result.append((previous / fps, end / fps))
        previous = end
    return result


def timecode(seconds):
    ms = round(seconds * 1000)
    minutes, rest = divmod(ms, 60000)
    whole, fraction = divmod(rest, 1000)
    return f"{minutes:02d}:{whole:02d}.{fraction:03d}"
