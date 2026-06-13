"""
Per-PC asset paths. Copy this file to `local_paths.py` and fill in the
paths for the current machine. `local_paths.py` is gitignored so each PC
can have its own values.

Usage:
    from local_paths import BGM, SFX, ARTIFACTS_DIR
"""
from pathlib import Path

# Folder where downloaded BGM/SFX tracks live.
DOWNLOADS = Path.home() / "Downloads"

# Folder where Gemini/Antigravity drops generated artifacts (set per PC).
ARTIFACTS_DIR = Path.home() / ".gemini" / "antigravity" / "brain"

# Background music tracks (keys used by run_*.py scripts).
BGM = {
    "abaddon":  DOWNLOADS / "ES_Return of the Longship - Dian Shuai.mp3",
    "marathon": DOWNLOADS / "ES_Packs of Savage Dogs - Dream Cave.mp3",
    "ezekiel":  DOWNLOADS / "ES_Horn - DEX 1200.mp3",
    "default":  DOWNLOADS / "ES_Boss Encountered - Trailer Worx.mp3",
}

# SFX tracks shared across runners.
SFX = {
    "crowd":  DOWNLOADS / "ES_Crowds, Battle, Medium Group, Mixed Genders, Battle Cry, Screams, Charge, Static 01 - Epidemic Sound.mp3",
    "hit":    DOWNLOADS / "ES_Weapons, Armor, Weapons, Shield, Hit 01 - Epidemic Sound.mp3",
    "swoosh": DOWNLOADS / "ES_Swooshes, Whoosh, Deep, Low, Cinematic - Epidemic Sound.mp3",
    "scream": DOWNLOADS / "ES_Voices, Scream, Medieval, Foot Archer, Battle Cries, Roars - Epidemic Sound.mp3",
}
