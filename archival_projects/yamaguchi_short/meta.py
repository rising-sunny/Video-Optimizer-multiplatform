"""Metadata del Short de Yamaguchi con las herramientas del repo (investigacion, titulos, tags, FB, IG, filtro TikTok)."""
import json, sys
sys.path.insert(0, "/home/user/Video-Optimizer-multiplatform")
import certifi
certifi.where = lambda: "/root/.ccr/ca-bundle.crt"
from publish import youtube_tags as yt, youtube_titles as tt, facebook_metadata as fb, tiktok_filter as tf
from publish.instagram_uploader import _compose_caption

TOPIC = "Tsutomu Yamaguchi, the man who survived both atomic bombs, Hiroshima and Nagasaki 1945"
SCRIPT = ("Tsutomu Yamaguchi, 29, ship designer for Mitsubishi. August 6, 1945, Hiroshima, 8:15 a.m. 3 km from the blast. "
          "Next day he took the train home to Nagasaki. August 9, he described Hiroshima to his boss. Then the flash. "
          "He lived to 93. In 2009 Japan officially recognized him as a survivor of both bombs.")
res = yt.gather_research(TOPIC, script=SCRIPT, suggest_fn=yt.youtube_autocomplete, log=lambda m: None)
print("RES", json.dumps(res, ensure_ascii=False, default=str)[:2500])
bible = json.load(open("/home/user/Video-Optimizer-multiplatform/daily_shorts/channel_strategy_profile.json"))
titles = sys.argv[1:]
for t in titles:
    s = tt.score_title(t, res, SCRIPT, is_short=True, bible=bible)
    print(f"{s.get('score')}\t{s.get('valid')}\t{t}\t{'; '.join(s.get('reasons', [])[:4])}")
