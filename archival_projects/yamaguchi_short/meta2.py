"""Textos finales: tags YT, Facebook, Instagram y el filtro de TikTok."""
import json, sys
sys.path.insert(0, "/home/user/Video-Optimizer-multiplatform")
from publish import youtube_tags as yt, facebook_metadata as fb, tiktok_filter as tf
from publish.instagram_uploader import _compose_caption

TITLE = "Tsutomu Yamaguchi Survived Hiroshima AND Nagasaki"
DESC = """On August 6, 1945, Tsutomu Yamaguchi, a 29-year-old Mitsubishi ship designer, was about 3 km from the atomic bomb in Hiroshima. Eardrums burst, left side burned, he took the train home the next day. Home was Nagasaki.

On August 9, bandaged, he went back to work and was describing Hiroshima to his boss when the second bomb exploded, again about 3 km away. He survived. He lived to 93, and in March 2009 Japan officially recognized him as a survivor of both bombings, the only person to receive that recognition.

Archival footage: "A Tale of Two Cities" (U.S. War Department, 1946); U.S. National Archives 111-ADC-10038 (Hiroshima and Nagasaki, 1946); U.S. Strategic Bombing Survey color film USAF-11075 (Hiroshima, 1946). Public domain. Train footage is illustrative (1946). Music: original.

#TsutomuYamaguchi #Hiroshima #Nagasaki #WW2 #History"""
TAGS = ["tsutomu yamaguchi", "tsutomu yamaguchi story", "tsutomu yamaguchi documentary", "tsutomu yamaguchi atomic bomb",
        "survived both atomic bombs", "hiroshima and nagasaki", "hiroshima survivor", "nagasaki bomb", "hiroshima bomb",
        "hiroshima footage", "nagasaki bombing documentary", "atomic bomb survivor", "hibakusha", "niju hibakusha",
        "ww2 history", "world war 2", "history shorts", "1945"]
tags = yt.finalize_youtube_tags(TAGS)
print("TAGS", yt.counted_length(tags), ", ".join(tags))

m = fb.optimize_facebook_metadata({"title": TITLE, "description": DESC, "tags": tags}, research_title=TITLE,
                                  keyword="tsutomu yamaguchi", subject="Tsutomu Yamaguchi", research_tags=tags,
                                  brand="Stunning Facts of History")
print("FB_TITLE", m["title"]); print("FB_DESC\n" + m["description"]); print("FB_HASHTAGS", m.get("hashtags"), "| fuera:", m.get("hashtags_dropped"))
print("FB_SUMMARY", m.get("summary"))

TT = ("He survived Hiroshima… then went home to Nagasaki. 🇯🇵 Tsutomu Yamaguchi, 29, was 3 km from the first atomic bomb on "
      "August 6, 1945. Three days later he was describing it to his boss in Nagasaki when the second one fell. He lived to 93. "
      "Archival footage, U.S. National Archives (public domain).")
TT_TAGS = ["#TsutomuYamaguchi", "#history", "#ww2", "#Hiroshima", "#Nagasaki", "#HistoryTok", "#LearnOnTikTok"]
f = tf.review(title="", description=TT, hashtags=TT_TAGS)
print("TIKTOK", "BLOQUEA" if tf.blocks(f) else "ok", tf.report(f))

IG_DESC = DESC.split("\n\nArchival footage")[0] + "\n\nArchival footage: U.S. National Archives (public domain).\n.\n.\n#TsutomuYamaguchi #Hiroshima #Nagasaki #WW2 #History #WorldWar2 #HistoryFacts #Japan #1945 #OnThisDay"
print("IG\n" + _compose_caption(TITLE, IG_DESC))
