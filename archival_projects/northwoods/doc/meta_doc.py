"""Metadata YouTube del documental Northwoods (Stunning Revelations) con las herramientas del repo."""
import json, sys
sys.path.insert(0, "/home/user/Video-Optimizer-multiplatform")
from publish import youtube_tags as yt, youtube_titles as tt
SCRIPT = " ".join(x[0] for x in __import__("script").SCRIPT if x[0] != "card")
res = yt.gather_research("Operation Northwoods 1962, the Pentagon plan to stage attacks and blame Cuba, declassified 1997",
                         script=SCRIPT, suggest_fn=yt.youtube_autocomplete, log=lambda m: None)
print("KW", res.get("keyword")); print("SUG", list(res.get("suggestions", {}))[:40])
bible = json.load(open("/home/user/Video-Optimizer-multiplatform/channel_profiles/stunning-revelations.json"))
for t in sys.argv[1:]:
    s = tt.score_title(t, res, SCRIPT, is_short=False, bible=bible)
    print(f"{s.get('score')}\t{s.get('valid')}\t{t}\t{'; '.join(s.get('reasons', [])[:4])}")
