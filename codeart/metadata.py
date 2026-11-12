"""Title / description / tags for code-generated shorts (hook = what the algorithm does)."""
import json
from pathlib import Path

PROFILE = Path(__file__).resolve().parent.parent / "channel_profiles" / "nostalgic-mood.json"

COPY = {
    "fireflies": {
        "title": "They Never Talk. They Still Blink Together \U0001F332 Fireflies at Night #shorts",
        "body": ("A night forest, a creek, and {fireflies:,} fireflies that start out blinking at random.\n\n"
                 "Nobody leads them. In this simulation each firefly only watches its 200 nearest neighbors and nudges its own rhythm "
                 "towards theirs, and little by little the whole forest falls into step. Real fireflies do this too: Photinus carolinus "
                 "in the Great Smoky Mountains and Pteroptyx in Southeast Asia flash in synchrony by reacting to the flashes around them."),
        "sound": "Sound: generated with code (crickets, creek, owl, soft notes on each flash).",
        "extra": ["fireflies", "synchronous fireflies", "night forest", "forest sounds", "crickets", "nature", "nature sounds", "emergence", "synchronization"],
    },
    "sunflower": {
        "title": "How a Sunflower Packs {seeds:,} Seeds \U0001F33B Golden Hour Field #shorts",
        "body": ("A sunflower opening in its field at golden hour, with bees, butterflies and the wind in the grass.\n\n"
                 "Every seed follows the same rule: turn by a fixed angle, step a little further out. At 120 degrees the seeds "
                 "collapse into three spokes. At about 137.508 degrees, the golden angle, they spread evenly. Real sunflower heads "
                 "pack their seeds very nearly this way (Vogel's model, 1979), which is where the Fibonacci spirals you can count "
                 "on them come from."),
        "sound": "Sound: generated with code (wind, birdsong, bees, ambient pad).",
        "extra": ["sunflower", "sunflower field", "golden hour", "nature", "bees", "butterflies", "nature sounds", "golden angle", "fibonacci"],
    },
    "tree": {
        "title": "One Rule Grew {branches:,} Branches \U0001F342 Autumn at Sunset #shorts",
        "body": ("No tree here was drawn. One rule was: split, turn, shorten, repeat. Run it ten levels deep and "
                 "{branches:,} branches fall out of it, along with {leaves:,} leaves that let go on their own schedule.\n\n"
                 "A branch is a smaller copy of the trunk, a twig a smaller copy of the branch. The wind is one sine wave, "
                 "scaled by how far each branch sits from the trunk, which is why the trunk barely moves and the tips swing."),
        "extra": ["fractal tree", "l-system", "recursion", "autumn", "sunset"],
    },
    "rain": {
        "title": "{drops} Raindrops, Each One a Tiny Lens \U0001F327 Night Rain Bokeh #shorts",
        "body": ("Each of these {drops} droplets is a tiny lens: it shows the city lights behind the glass flipped upside down, "
                 "the same way a real water drop refracts light.\n\nThe bokeh is blurred circles of light, the drops are "
                 "samples of the sharp image mirrored inside a circle. No photo, no AI image model, just arrays and math."),
        "extra": ["rain on glass", "bokeh", "refraction", "night rain", "city lights"],
    },
    "aurora": {
        "title": "{stars} Stars and Three Sine Waves Made This Aurora \U0001F30C Lake at Night #shorts",
        "body": ("These aurora curtains are a handful of sine waves added together, with a faster wave on top that makes the "
                 "vertical streaks. The lake is the sky flipped and rippled by another sine.\n\n"
                 "{stars} stars, each twinkling on its own phase. Nothing was drawn by hand."),
        "extra": ["aurora", "northern lights", "night sky", "lake reflection", "stars"],
    },
}

FOOT = ("\n\nGenerated entirely with code (Python, numpy, OpenCV). No AI image models. Rendered frame by frame at 720x1280 / 60 fps.\n"
        "{sound}\n\n"
        "Subscribe to Nostalgic Mood for a new code-made atmosphere every week.\n\n"
        "#nature #generativeart #relaxing #shorts")


def build_metadata(scene, stats, channel="nostalgic-mood"):
    c = COPY[scene]
    prof = json.loads(PROFILE.read_text(encoding="utf-8"))
    base = prof["metadata_rules"]["tags_base"]
    return {
        "title": c["title"].format(**stats),
        "description": c["body"].format(**stats) + FOOT.format(sound=c.get("sound", "Music: procedurally generated ambient pad.")),
        "tags": list(dict.fromkeys(c["extra"] + base)),
        "is_short": True,
        "category_id": "24",          # Entertainment
        "upload_channel": channel,
        "channel_profile": channel,
        "title_mode": "off",
        "tag_research": False,        # curated tags; research is tuned for history topics
        "topic": scene,
    }
