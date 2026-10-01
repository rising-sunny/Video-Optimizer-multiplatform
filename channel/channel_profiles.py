"""Named channel profiles; the legacy profile remains the default."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHANNEL = "stunning-facts-of-history"
CHANNELS = {
    DEFAULT_CHANNEL: {"name": "@StunningFactsofHistory", "profile": "daily_shorts/channel_strategy_profile.json", "token": "token.json", "channel_id": "UCXQ1_6A-JkBeQsMkiDcunGA", "format": "traditional"},
    "stunning-revelations": {"name": "@Stunning-Revelations", "profile": "channel_profiles/stunning-revelations.json", "token": "token_stunning-revelations.json", "channel_id": "UC66EnGiys6V3gKe-J0XD-_Q", "format": "micro_documentary"},
}
_active = DEFAULT_CHANNEL


def active_channel():
    return _active


def select_channel(key):
    global _active
    if key not in CHANNELS:
        raise ValueError(f"Unknown channel: {key}")
    _active = key
    from channel import channel_strategy
    channel_strategy._cached_strategy = None
    import sys
    pipeline = sys.modules.get('pipeline.daily_short_pipeline')
    if pipeline is not None and hasattr(pipeline, 'refresh_channel_config'):
        pipeline.refresh_channel_config()
    return key


def load_profile(key=None):
    key = key or active_channel()
    with (ROOT / CHANNELS[key]["profile"]).open(encoding="utf-8") as handle:
        return json.load(handle)


def token_path(key=None):
    return ROOT / CHANNELS[key or active_channel()]["token"]
