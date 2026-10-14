import sys
import tempfile
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from pipeline import blender_shots

img = "catarsis_media/trench_somme.jpg"
if not Path(img).exists():
    img = str(next(Path("catarsis_media").glob("*.jpg")))

for env in ("map", "war_room", "timeline"):
    print(f"\n=== {env} / motion=orbit ===", flush=True)
    r = blender_shots.render_shot(
        env, [img], duration=0.2, size=(270, 480), fps=30,
        cache_dir=tempfile.mkdtemp(), quality="draft", motion="orbit",
        timeout_s=300, log=print,
    )
    print("RESULT:", {k: r[k] for k in ("ok", "path", "seconds", "error", "cached") if k in r}, flush=True)
