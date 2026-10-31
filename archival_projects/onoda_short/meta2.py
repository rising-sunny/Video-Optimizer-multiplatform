"""Textos finales del Short de Onoda: tags YT, Facebook, Instagram y filtro TikTok."""
import sys
sys.path.insert(0, "/home/user/Video-Optimizer-multiplatform")
from publish import youtube_tags as yt, facebook_metadata as fb, tiktok_filter as tf
from publish.instagram_uploader import _compose_caption
TITLE = "Hiroo Onoda: The Japanese Soldier Who Fought Until 1974"
DESC = """World War II ended in August 1945. Lieutenant Hiroo Onoda surrendered in March 1974.

Sent to Lubang Island in the Philippines in December 1944, the 22-year-old intelligence officer was ordered never to surrender. When leaflets announced the war was over, he dismissed them as enemy propaganda. His men surrendered or were killed, one by one; his last comrade was shot in 1972. In 1974 a young Japanese traveler, Norio Suzuki, found him, but Onoda refused to stand down without orders. On March 9, 1974, his former commander, Major Yoshimi Taniguchi, flew to Lubang and relieved him. He handed over his sword, his rifle and 500 rounds. During those years, up to 30 islanders were allegedly killed. He was pardoned by President Marcos and died in 2014, aged 91.

Archival footage: U.S. Army films, Philippines 1944–45 (U.S. National Archives, 111-ADC); Universal Newsreel, August 1945; Japanese surrender aboard USS Missouri. Public domain; footage is illustrative, no images of Onoda are shown. Music: original.

#HirooOnoda #WW2 #History #Japan #Philippines"""
tags = yt.finalize_youtube_tags(["hiroo onoda", "hiroo onoda the last japanese soldier", "hiroo onoda japanese soldier", "hiroo onoda story",
    "hiroo onoda documentary", "hiroo onoda surrender", "hiroo onoda 1974", "lt hiroo onoda", "last japanese soldier",
    "japanese holdout", "lubang island", "world war ii history", "world war ii stories", "ww2 history", "history shorts"])
print("TAGS", yt.counted_length(tags), ", ".join(tags))
m = fb.optimize_facebook_metadata({"title": TITLE, "description": DESC, "tags": tags}, research_title=TITLE, keyword="hiroo onoda",
                                  subject="Hiroo Onoda", research_tags=tags, brand="Stunning Facts of History")
print("FB_HASHTAGS", m.get("hashtags"), "| fuera:", m.get("hashtags_dropped")); print("FB_FIRST", m["description"].split("\n")[0])
TT = ("World War II ended in 1945. He surrendered in 1974. 🇯🇵 Lt. Hiroo Onoda was ordered never to surrender on Lubang Island. "
      "He dismissed the leaflets announcing peace, and only stood down when his old commander flew in to relieve him. "
      "Archival footage, U.S. National Archives (public domain).")
TT_TAGS = ["#HirooOnoda", "#history", "#ww2", "#HistoryTok", "#Japan", "#LearnOnTikTok"]
f = tf.review(description=TT, hashtags=TT_TAGS)
print("TIKTOK", "BLOQUEA" if tf.blocks(f) else "ok", tf.report(f))
IG = DESC.split("\n\nArchival footage")[0] + "\n\nArchival footage: U.S. National Archives (public domain).\n.\n.\n#HirooOnoda #WW2 #WorldWar2 #History #HistoryFacts #Japan #Philippines #LastSoldier #1974 #MilitaryHistory"
f2 = tf.review(description=IG)
print("IG_FILTER", tf.report(f2))
