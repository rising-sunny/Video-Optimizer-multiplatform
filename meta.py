"""Titulos (puntaje), tags, FB, IG y filtro TikTok de los Shorts Gunther y Sea-Spray."""
import json, sys
sys.path.insert(0, "/home/user/Video-Optimizer-multiplatform")
import certifi
certifi.where = lambda: "/root/.ccr/ca-bundle.crt"
from publish import youtube_tags as yt, youtube_titles as tt, facebook_metadata as fb, tiktok_filter as tf
from publish.instagram_uploader import _compose_caption
R = "/home/user/Video-Optimizer-multiplatform/"
J = {
 "gu": dict(topic="Henry Gunther, the last American soldier killed in World War I at 10:59 on November 11, 1918",
   bible=R + "daily_shorts/channel_strategy_profile.json", brand="Stunning Facts of History", kw="henry gunther", subject="Henry Gunther",
   titles=["Henry Gunther: Killed One Minute Before the Armistice", "Henry Gunther, the Last Soldier Killed in WW1", "Killed One Minute Before the Armistice: Henry Gunther"],
   desc="""The armistice ending World War I was signed before dawn on November 11, 1918, but the ceasefire was set for 11:00 a.m. The fighting went on all morning.

Henry Gunther, 23, a bank clerk from Baltimore, had been drafted into the 313th Infantry ("Baltimore's Own"). A letter home describing miserable conditions at the front was read by the Army censor, and he was demoted from sergeant to private. At 10:59 a.m., near Chaumont-devant-Damvillers, France, he charged a German machine-gun position. The German soldiers, who knew the war was about to end, tried to wave him back. He kept going and was hit by a short burst, about one minute before the ceasefire.

General Pershing's order of the day named him the last American killed in the war. The Army restored his rank of sergeant and awarded him the Distinguished Service Cross. On that last day, nearly 11,000 men were killed, wounded or missing.

Archival footage: U.S. National Archives, Signal Corps historical films (Meuse-Argonne Offensive; Armistice celebrations, 1918; 79th Division). The Evening Star, Nov. 11, 1918 (Library of Congress, Chronicling America). Photo of Henry Gunther: public domain. All public domain.
Music: "Crusade - Heavy Industry" by Kevin MacLeod (incompetech.com), licensed under Creative Commons: By Attribution 4.0 License, http://creativecommons.org/licenses/by/4.0/

#WW1 #ArmisticeDay #History""",
   tags=["henry gunther", "last soldier killed in ww1", "last american killed in ww1", "armistice day", "armistice 1918",
         "11th hour of the 11th day", "november 11 1918", "world war 1", "ww1 history", "wwi", "meuse argonne offensive",
         "veterans day", "remembrance day", "history shorts", "ww1 footage", "1918"],
   tt=("The war ended at 11:00. He fell at 10:59. Henry Gunther, 23, a bank clerk from Baltimore, charged a German position one minute "
       "before the WWI ceasefire on November 11, 1918. The armistice had been signed before dawn. Archival footage: U.S. National Archives."),
   tt_tags=["#history", "#ww1", "#ArmisticeDay", "#RemembranceDay", "#HistoryTok", "#LearnOnTikTok"],
   ig_tags="#WW1 #ArmisticeDay #RemembranceDay #VeteransDay #History #HistoryFacts #WorldWar1 #1918 #OnThisDay #Baltimore"),
 "ss": dict(topic="Operation Sea-Spray, the 1950 secret US Navy test that sprayed bacteria over San Francisco",
   bible=R + "channel_profiles/stunning-revelations.json", brand="Stunning Revelations", kw="operation sea-spray", subject="Operation Sea-Spray",
   titles=["The Navy Secretly Sprayed Bacteria Over San Francisco", "Operation Sea-Spray: The Secret Test on 800,000 People", "In 1950, the U.S. Sprayed Bacteria on Its Own City"],
   desc="""From September 20 to 27, 1950, a U.S. Navy ship off the coast released two bacteria, Serratia marcescens and Bacillus globigii, toward San Francisco. It was a secret biological-warfare vulnerability test: Operation Sea-Spray. The Army's monitors at 43 locations concluded that nearly all of the city's 800,000 residents had inhaled at least 5,000 particles. There is no evidence health authorities were warned.

Weeks later, 11 patients at Stanford Hospital in San Francisco developed rare Serratia urinary infections. One of them, Edward J. Nevin, died. The Army later called any link a coincidence, and a court never found the test responsible. The test was first reported by Newsday in November 1976; in 1977, at Senate hearings, the Army disclosed 239 open-air tests between 1949 and 1969.

Sources: "Biological Testing Involving Human Subjects by the Department of Defense, 1977", Senate hearings (March 8 and May 23, 1977); U.S. Army, "U.S. Army Activity in the U.S. Biological Warfare Programs" (1977).
Archival footage: "What You Should Know About Biological Warfare" (U.S. Federal Civil Defense Administration, 1951; dramatized scenes, illustrative); Prelinger Archives home movies of San Francisco, 1940s (illustrative).
Music: "Invariance" by Kevin MacLeod (incompetech.com), licensed under Creative Commons: By Attribution 4.0 License, http://creativecommons.org/licenses/by/4.0/

#OperationSeaSpray #Declassified #SanFrancisco""",
   tags=["operation sea-spray", "operation sea spray", "san francisco bacteria 1950", "serratia marcescens", "secret government experiments",
         "biological warfare test", "us army secret tests", "declassified", "cold war secrets", "senate hearings 1977",
         "human experiments usa", "san francisco history", "edward nevin", "1950", "true story", "dark history"],
   tt=("In 1950, a U.S. Navy ship sprayed bacteria toward San Francisco for seven days. Almost all 800,000 residents breathed it in, and no one was told. "
       "The Army disclosed it in 1977. Sources: 1977 U.S. Senate hearings."),
   tt_tags=["#history", "#declassified", "#SanFrancisco", "#coldwar", "#HistoryTok", "#LearnOnTikTok"],
   ig_tags="#OperationSeaSpray #Declassified #SanFrancisco #ColdWar #History #HiddenHistory #DarkHistory #1950 #TrueStory #Government"),
}
for key in sys.argv[1:]:
    c = J[key]; print("=" * 30, key)
    script = c["desc"].split("\n\nArchival")[0].split("\n\nSources")[0]
    try:
        res = yt.gather_research(c["topic"], script=script, suggest_fn=yt.youtube_autocomplete, log=lambda m: None)
    except Exception as e:
        print("research fallo", e); res = {}
    bible = json.load(open(c["bible"]))
    for t in c["titles"]:
        s = tt.score_title(t, res, script, is_short=True, bible=bible)
        print(f"{s.get('score')}\t{s.get('valid')}\t{t}\t{'; '.join(s.get('reasons', [])[:3])}")
    tags = yt.finalize_youtube_tags(c["tags"]); print("TAGS", yt.counted_length(tags), ", ".join(tags))
    m = fb.optimize_facebook_metadata({"title": c["titles"][0], "description": c["desc"], "tags": tags}, research_title=c["titles"][0],
                                      keyword=c["kw"], subject=c["subject"], research_tags=tags, brand=c["brand"])
    print("FB_TITLE", m["title"]); print("FB_DESC\n" + m["description"]); print("FB_HASHTAGS", m.get("hashtags"))
    f = tf.review(title="", description=c["tt"], hashtags=c["tt_tags"]); print("TIKTOK", "BLOQUEA" if tf.blocks(f) else "ok", tf.report(f))
    print("TT_TEXT", c["tt"], " ".join(c["tt_tags"]))
    ig = c["desc"].split("\n\nArchival")[0].split("\n\nSources")[0] + "\n\nArchival footage: public domain.\n.\n.\n" + c["ig_tags"]
    print("IG\n" + _compose_caption(c["titles"][0], ig))
