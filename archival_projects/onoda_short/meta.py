"""Metadata del Short de Yamaguchi con las herramientas del repo (investigacion, titulos, tags, FB, IG, filtro TikTok)."""
import json, sys
sys.path.insert(0, "/home/user/Video-Optimizer-multiplatform")
import certifi
certifi.where = lambda: "/root/.ccr/ca-bundle.crt"
from publish import youtube_tags as yt, youtube_titles as tt, facebook_metadata as fb, tiktok_filter as tf
from publish.instagram_uploader import _compose_caption

TOPIC = "Hiroo Onoda, the Japanese soldier who kept fighting World War II until 1974"
SCRIPT = ("World War II ended in 1945. Hiroo Onoda surrendered in 1974. December 1944, Lubang Island, the Philippines. Lt. Hiroo Onoda, 22, intelligence officer. Orders: never surrender. "
          "Leaflets announced peace, he called them fakes. 1972 his last comrade was shot. 1974 a young traveler found him. March 9, 1974 his old major arrived. "
          "He handed over his sword, rifle and 500 rounds. 29 years.")
res = yt.gather_research(TOPIC, script=SCRIPT, suggest_fn=yt.youtube_autocomplete, log=lambda m: None)
print("RES", json.dumps(res, ensure_ascii=False, default=str)[:2500])
bible = json.load(open("/home/user/Video-Optimizer-multiplatform/daily_shorts/channel_strategy_profile.json"))
titles = sys.argv[1:]
for t in titles:
    s = tt.score_title(t, res, SCRIPT, is_short=True, bible=bible)
    print(f"{s.get('score')}\t{s.get('valid')}\t{t}\t{'; '.join(s.get('reasons', [])[:4])}")
