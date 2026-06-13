# trend_spotter.py — Enhanced multi-source trend detection
"""
Detects trending topics from multiple sources for video idea generation.

Sources:
  1. Google Trends (pytrends) — real-time search trends
  2. YouTube Trending — popular videos via YouTube Data API v3
  3. YouTube Search Suggest — autocomplete queries (no API key needed)
  4. Reddit — hot posts from relevant subreddits (no API key needed)
  5. Wikipedia — most viewed articles (no API key needed)
  6. SERP API — search engine results (if configured)
  7. Groq AI — AI-predicted trends (fallback)
  8. Static fallback — evergreen topics (last resort)
"""

import json
import datetime
import os
import random
import re
import time
from typing import List, Dict, Optional
from urllib.parse import quote_plus

# ── Optional imports ─────────────────────────────────────────────────────
try:
    from pytrends.request import TrendReq
    PYTRENDS_AVAILABLE = True
except ImportError:
    PYTRENDS_AVAILABLE = False
    print("️ pytrends no instalado. pip install pytrends")

try:
    from serp_api_client import SerpApiClient, SERP_API_AVAILABLE
except ImportError:
    SERP_API_AVAILABLE = False
    SerpApiClient = None

try:
    from groq_client import GroqAiClient
except ImportError:
    GroqAiClient = None

try:
    import requests as _requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 1: GOOGLE TRENDS (pytrends)
# ═══════════════════════════════════════════════════════════════════════════

def get_google_trends(region: str = "US") -> List[str]:
    """Fetch trending searches from Google Trends via pytrends."""
    if not PYTRENDS_AVAILABLE:
        return []

    region_map = {
        "US": "united_states", "GB": "united_kingdom", "CA": "canada",
        "AU": "australia", "IN": "india", "ES": "spain", "MX": "mexico",
        "AR": "argentina", "CL": "chile", "CO": "colombia", "PE": "peru",
        "NZ": "new_zealand", "IE": "ireland", "ZA": "south_africa",
        "GLOBAL": "united_states",
    }
    pytrends_region = region_map.get(region.upper(), "united_states")

    try:
        pytrends = TrendReq(hl="en-US", tz=360, timeout=(5, 10))

        try:
            data = pytrends.trending_searches(pn=pytrends_region)
        except Exception:
            if pytrends_region != "united_states":
                try:
                    data = pytrends.trending_searches(pn="united_states")
                except Exception:
                    return []
            else:
                return []

        if data is not None and not data.empty:
            trends = data.head(15)[0].tolist()
            print(f"   Google Trends ({region}): {len(trends)} trends")
            return trends
    except Exception as e:
        print(f"  ️ Google Trends error: {e}")
    return []


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 2: YOUTUBE TRENDING (scraping, no API key needed)
# ═══════════════════════════════════════════════════════════════════════════

def get_youtube_trending(region: str = "US", max_results: int = 15) -> List[str]:
    """
    Fetch currently trending YouTube videos via web scraping.
    Extracts video titles from YouTube's trending page HTML.
    No API key needed.
    """
    if not REQUESTS_AVAILABLE:
        return []

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    all_titles = []

    # Scrape YouTube trending page — titles appear in "title":{"runs":[{"text":"..."}]}
    try:
        url = f"https://www.youtube.com/feed/trending?gl={region}"
        resp = _requests.get(url, headers=headers, timeout=12)
        if resp.status_code == 200:
            # YouTube embeds JSON data in the HTML (ytInitialData)
            import re as _re
            match = _re.search(r'var ytInitialData\s*=\s*(\{.+?\});\s*</script>', resp.text)
            if match:
                try:
                    yt_data = json.loads(match.group(1))
                    # Navigate the nested structure to find video titles
                    tabs = (yt_data.get("contents", {})
                            .get("twoColumnBrowseResultsRenderer", {})
                            .get("tabs", []))
                    for tab in tabs:
                        tab_content = (tab.get("tabRenderer", {})
                                       .get("content", {})
                                       .get("sectionListRenderer", {})
                                       .get("contents", []))
                        for section in tab_content:
                            items = (section.get("itemSectionRenderer", {})
                                     .get("contents", [{}])[0]
                                     .get("shelfRenderer", {})
                                     .get("content", {})
                                     .get("expandedShelfContentsRenderer", {})
                                     .get("items", []))
                            for item in items:
                                title_runs = (item.get("videoRenderer", {})
                                              .get("title", {})
                                              .get("runs", []))
                                for run in title_runs:
                                    t = run.get("text", "").strip()
                                    if t:
                                        all_titles.append(t)
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass

            # Fallback: regex extract titles from meta tags / JSON fragments
            if not all_titles:
                title_pattern = _re.compile(r'"title":\s*\{"runs":\[\{"text":"([^"]{10,120})"\}')
                found = title_pattern.findall(resp.text)
                all_titles.extend(found[:max_results])

    except Exception as e:
        print(f"  ️ YouTube Trending scrape error: {e}")

    # Deduplicate preserving order
    seen = set()
    unique = []
    for t in all_titles:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            unique.append(t)

    if unique:
        print(f"   YouTube Trending ({region}): {len(unique[:max_results])} videos")
    return unique[:max_results]


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 3: YOUTUBE SEARCH SUGGEST (autocomplete, no API key needed)
# ═══════════════════════════════════════════════════════════════════════════

def get_youtube_search_suggest(seed_queries: List[str] = None) -> List[str]:
    """
    Fetch YouTube autocomplete suggestions for seed queries.
    This reveals what people are actively searching on YouTube right now.
    No API key needed — uses the public autocomplete endpoint.
    """
    if not REQUESTS_AVAILABLE:
        return []

    if not seed_queries:
        seed_queries = [
            "mysterious", "ancient history", "unexplained",
            "military secrets", "natural disaster", "conspiracy",
            "what really happened", "scientists discover",
        ]

    suggestions = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for query in seed_queries[:6]:  # Limit requests
        try:
            url = (
                f"https://suggestqueries-clients6.youtube.com/complete/search"
                f"?client=youtube&ds=yt&q={quote_plus(query)}"
            )
            resp = _requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                # Response is JSONP, extract the JSON array
                text = resp.text
                # Find the JSON array between ( and )
                start = text.find("(")
                end = text.rfind(")")
                if start >= 0 and end > start:
                    json_text = text[start + 1:end]
                    data = json.loads(json_text)
                    if isinstance(data, list) and len(data) > 1:
                        for item in data[1]:
                            if isinstance(item, list) and item:
                                s = item[0]
                                if isinstance(s, str) and s != query:
                                    suggestions.append(s)
            time.sleep(0.2)  # Be polite
        except Exception:
            continue

    # Deduplicate
    seen = set()
    unique = []
    for s in suggestions:
        key = s.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(s)

    if unique:
        print(f"   YouTube Suggest: {len(unique)} suggestions")
    return unique[:15]


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 4: REDDIT (no API key needed — public JSON endpoints)
# ═══════════════════════════════════════════════════════════════════════════

def get_reddit_trending(subreddits: List[str] = None, max_per_sub: int = 5) -> List[str]:
    """
    Fetch hot posts from relevant subreddits via public JSON API.
    No API key needed — Reddit serves .json endpoints publicly.
    """
    if not REQUESTS_AVAILABLE:
        return []

    if not subreddits:
        subreddits = [
            "todayilearned",        # Viral history/science facts
            "history",              # History discussions
            "UnresolvedMysteries",  # Mysteries
            "Damnthatsinteresting", # Viral interesting content
            "science",              # Science news
            "worldnews",            # Global trending events
            "interestingasfuck",    # Viral content
            "explainlikeimfive",    # Educational trending
        ]

    headers = {
        "User-Agent": "VideoOptimizer/1.0 (trend detection)"
    }

    hot_topics = []
    for sub in subreddits:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit={max_per_sub}&t=day"
            resp = _requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                posts = data.get("data", {}).get("children", [])
                for post in posts:
                    post_data = post.get("data", {})
                    title = post_data.get("title", "")
                    score = post_data.get("score", 0)
                    # Only include posts with decent traction
                    if title and score > 100 and not post_data.get("stickied", False):
                        hot_topics.append(title)
            time.sleep(0.5)  # Reddit rate limit: ~1 req/sec
        except Exception:
            continue

    if hot_topics:
        print(f"   Reddit: {len(hot_topics)} hot topics from {len(subreddits)} subreddits")
    return hot_topics[:20]


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 5: WIKIPEDIA MOST VIEWED (no API key needed)
# ═══════════════════════════════════════════════════════════════════════════

def get_wikipedia_trending(max_results: int = 15) -> List[str]:
    """
    Fetch most viewed Wikipedia articles from yesterday.
    High Wikipedia views often correlate with viral topics.
    Uses the official Wikimedia REST API (no key needed).
    """
    if not REQUESTS_AVAILABLE:
        return []

    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    date_str = yesterday.strftime("%Y/%m/%d")

    try:
        url = (
            f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/"
            f"en.wikipedia/all-access/{date_str}"
        )
        headers = {
            "User-Agent": "VideoOptimizer/1.0 (trend detection)",
            "Accept": "application/json",
        }
        resp = _requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return []

        data = resp.json()
        articles = data.get("items", [{}])[0].get("articles", [])

        # Filter out generic/meta pages
        skip_titles = {
            "Main_Page", "Special:Search", "-", "Wikipedia:Featured_pictures",
            "Portal:Current_events", "Special:Contributions",
        }

        topics = []
        for article in articles:
            title = article.get("article", "")
            views = article.get("views", 0)
            if (title and title not in skip_titles
                    and not title.startswith("Special:")
                    and not title.startswith("Wikipedia:")
                    and not title.startswith("File:")
                    and not title.startswith("Portal:")
                    and views > 50000):
                # Convert underscores to spaces
                clean_title = title.replace("_", " ")
                topics.append(clean_title)

        if topics:
            print(f"   Wikipedia: {len(topics[:max_results])} most-viewed articles")
        return topics[:max_results]

    except Exception as e:
        print(f"  ️ Wikipedia error: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 6: SERP API (trending keywords from search engine)
# ═══════════════════════════════════════════════════════════════════════════

def get_serp_trends(region: str = "US") -> List[str]:
    """Fetch trending topics via SERP API Google search results."""
    if not SERP_API_AVAILABLE:
        return []

    try:
        serp = SerpApiClient()
        location = {
            "US": "United States", "GB": "United Kingdom",
            "CA": "Canada", "AU": "Australia", "IN": "India",
        }.get(region, "United States")

        results = serp.search_google(
            "trending searches today news pop culture",
            location=location,
        )
        if not results:
            return []

        trends = []
        for key in ("related_searches", "top_stories"):
            if key in results:
                for item in results[key]:
                    val = item.get("query" if key == "related_searches" else "title", "")
                    if not val and isinstance(item, str):
                        val = item
                    if val:
                        trends.append(val)

        if trends:
            print(f"   SERP API ({region}): {len(trends)} trends")
        return trends[:15]

    except Exception as e:
        print(f"  ️ SERP API error: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 7: AI-PREDICTED TRENDS (Groq fallback)
# ═══════════════════════════════════════════════════════════════════════════

def get_ai_predicted_trends(ai_client, region="US") -> List[str]:
    """
    Use AI to predict/infer current trends based on date and general knowledge.
    Useful when real-time APIs fail.
    """
    if not ai_client:
        return []

    today = datetime.date.today().strftime("%Y-%m-%d")

    prompt = f"""
    You are an expert on global trends and viral content.
    Today is {today}.

    Generate a list of 10 topics that are likely trending TODAY in {region} (or globally).
    Consider:
    - Recent or ongoing sporting events
    - Recent movie/series releases
    - Important tech news
    - Holidays or seasonal events for this date
    - Recent viral memes or topics
    - Historical anniversaries happening today
    - Scientific discoveries or announcements

    Respond ONLY with a comma-separated list of strings, no numbering or explanations.
    Example: World Cup, New iPhone, Elections, Christmas, Marvel...
    """

    try:
        response = ai_client._generate(prompt)
        trends = [t.strip() for t in response.split(",") if t.strip()]
        if trends:
            print(f"   AI Prediction ({region}): {len(trends)} inferred trends")
            return trends[:15]
    except Exception as e:
        print(f"  ️ AI trend prediction error: {e}")

    return []


# ═══════════════════════════════════════════════════════════════════════════
# SOURCE 8: STATIC FALLBACK
# ═══════════════════════════════════════════════════════════════════════════

def get_fallback_trends() -> List[str]:
    """
    Last-resort fallback with evergreen topics.
    Returns 10 random topics from a curated list.
    """
    all_fallbacks = [
        "ancient civilizations discoveries",
        "unsolved mysteries of history",
        "military operations declassified",
        "lost cities found",
        "conspiracy theories and cover ups",
        "unexplained phenomena",
        "ufo sightings and government files",
        "haunted places with real history",
        "secret societies throughout history",
        "ancient artifacts no one can explain",
        "mysterious disappearances never solved",
        "paranormal cases from declassified archives",
        "famous last words in history",
        "archaeological mysteries of ancient worlds",
        "weapons that changed warfare",
        "time capsules and what they revealed",
        "cold war secrets recently declassified",
        "historical conspiracies still debated today",
    ]
    random.shuffle(all_fallbacks)
    return all_fallbacks[:10]


# ═══════════════════════════════════════════════════════════════════════════
# UNIFIED TREND AGGREGATOR
# ═══════════════════════════════════════════════════════════════════════════

def get_trending_topics(
    region: str = "US",
    ai_client=None,
    regions: List[str] = None,
    channel_categories: List[str] = None,
) -> List[str]:
    """
    Aggregates trends from ALL available sources, deduplicates and ranks.

    Args:
        region: Primary region code (US, GB, CA, AU, IN, etc.)
        ai_client: Optional GroqAiClient for AI fallback
        regions: List of regions to scan (default: US, GB, GLOBAL)
        channel_categories: Channel categories for YouTube Suggest seeds

    Returns:
        List of trending topic strings (deduplicated, max ~40)
    """
    if regions is None:
        regions = ["US", "GB", "GLOBAL"]

    all_trends = []
    source_counts = {}

    print(" Scanning trend sources...")

    # ── Source 1: Google Trends (multi-region) ──
    for r in regions:
        gt = get_google_trends(r)
        if gt:
            all_trends.extend(gt)
            source_counts["Google Trends"] = source_counts.get("Google Trends", 0) + len(gt)

    # ── Source 2: YouTube Trending ──
    yt = get_youtube_trending(region=region)
    if yt:
        all_trends.extend(yt)
        source_counts["YouTube Trending"] = len(yt)

    # ── Source 3: YouTube Search Suggest ──
    seed_queries = None
    if channel_categories:
        # Use channel categories as seed queries for more relevant suggestions
        seed_queries = [cat.lower() for cat in channel_categories[:4]]
        seed_queries.extend(["what really happened", "scientists discover"])

    ys = get_youtube_search_suggest(seed_queries=seed_queries)
    if ys:
        all_trends.extend(ys)
        source_counts["YouTube Suggest"] = len(ys)

    # ── Source 4: Reddit ──
    rd = get_reddit_trending()
    if rd:
        all_trends.extend(rd)
        source_counts["Reddit"] = len(rd)

    # ── Source 5: Wikipedia ──
    wp = get_wikipedia_trending()
    if wp:
        all_trends.extend(wp)
        source_counts["Wikipedia"] = len(wp)

    # ── Source 6: SERP API ──
    sp = get_serp_trends(region=region)
    if sp:
        all_trends.extend(sp)
        source_counts["SERP API"] = len(sp)

    # ── Source 7: AI Prediction (only if we got very few trends) ──
    if len(all_trends) < 10 and ai_client:
        ai = get_ai_predicted_trends(ai_client, region)
        if ai:
            all_trends.extend(ai)
            source_counts["AI Prediction"] = len(ai)

    # ── Source 8: Static fallback (last resort) ──
    if not all_trends:
        print("  ️ All sources failed — using static fallback")
        all_trends = get_fallback_trends()
        source_counts["Static Fallback"] = len(all_trends)

    # ── Deduplicate (case-insensitive, preserving first occurrence) ──
    seen = set()
    unique_trends = []
    for t in all_trends:
        t_clean = t.strip()
        if not t_clean:
            continue
        key = t_clean.lower()
        # Skip very short or very long entries
        if len(key) < 3 or len(key) > 200:
            continue
        if key not in seen:
            seen.add(key)
            unique_trends.append(t_clean)

    # ── Summary ──
    total_raw = sum(source_counts.values())
    active_sources = len(source_counts)
    print(f"\n Trend Summary: {len(unique_trends)} unique topics from {active_sources} sources ({total_raw} raw)")
    for source, count in source_counts.items():
        print(f"   • {source}: {count}")

    return unique_trends


# ═══════════════════════════════════════════════════════════════════════════
# TREND ANALYSIS (converts raw trends  video ideas via AI)
# ═══════════════════════════════════════════════════════════════════════════

def analyze_trends_for_video_ideas(
    trends_list: List[str],
    categories: List[str],
    ai_client,
    channel_performance: Dict = None,
    used_titles: List[str] = None,
) -> Dict:
    """
    Use AI to convert raw trends into video ideas for the channel.
    Uses channel performance data to prioritize categories and title patterns
    that have proven to work.
    """
    if not ai_client:
        print(" AI Client required to analyze trends.")
        return {"error": "AI client not available."}

    today = datetime.date.today().strftime("%Y-%m-%d")
    category_str = ", ".join(categories)
    trends_str = "\n".join(f"- {trend}" for trend in trends_list[:30])

    print(f" AI: Analyzing {len(trends_list)} trends for: {category_str}...")

    # ── Build channel performance context ─────────────────────────────
    perf_context = ""
    if channel_performance:
        top_cats = channel_performance.get("best_performing_categories", [])
        title_info = channel_performance.get("title_patterns", {})

        if top_cats:
            cat_lines = []
            for cat in top_cats:
                cat_lines.append(f"    - {cat['name']}: {cat.get('avg_views', '?')} avg views ({cat.get('notes', '')})")
            perf_context += "\n    CHANNEL PERFORMANCE DATA (from YouTube Studio analytics):\n"
            perf_context += "    Best-performing categories (PRIORITIZE these):\n"
            perf_context += "\n".join(cat_lines) + "\n"

        if title_info:
            keywords = title_info.get("high_performing_keywords", [])
            examples = title_info.get("top_title_examples", [])
            perf_context += f"""
    TITLE OPTIMIZATION DATA:
    - 52% of top titles contain specific NUMBERS  include a number when possible
    - 63% of top titles use a COLON  use format "[Subject]: [Hook]"
    - Best length: 40-55 characters
    - Keywords that drive views: {', '.join(keywords[:10])}
    - Example top titles (500+ views each):
"""
            for ex in examples[:4]:
                perf_context += f"      * {ex}\n"

    # ── Build used titles exclusion list ─────────────────────────────
    used_titles_context = ""
    if used_titles:
        # Limitar a los últimos 250 títulos para no sobrecargar el prompt
        recent_titles = used_titles[-250:]
        titles_str = "\n".join(f"    - {t}" for t in recent_titles)
        used_titles_context = f"""
    ️ CRITICAL — ALREADY USED TITLES (DO NOT repeat or create similar ones):
{titles_str}

    You MUST generate completely DIFFERENT topics and angles. Do NOT rephrase
    or slightly modify any title from the list above. Choose FRESH subjects.
    A topic still counts as DUPLICATE if it covers the same core subject,
    event, person, place, disaster or mystery with a different hook, number,
    wording or list format. Do NOT generate "same topic, different angle".
"""

    prompt = f"""
    You are a WORLD-CLASS YouTube viral content strategist for "Stunning Revelations".
    Current date: {today}

    YOUR MISSION:
    Find the EXPLOSIVE intersection between today's trends and my target categories.
    PRIORITIZE categories and title styles that have PROVEN to perform on this channel.
    ONLY choose final topics that are firmly about major historical events, ancient civilizations,
    military secrets, conspiracies, mysteries, UFOs or paranormal phenomena.

    TARGET CATEGORIES: {category_str}
{perf_context}{used_titles_context}
    TODAY'S REAL TRENDS (from Google, YouTube, Reddit, Wikipedia):
    {trends_str}

    INSTRUCTIONS:
    1. Analyze the trends and find creative connections to my categories.
    2. PRIORITIZE the 3 algorithmic pillars that work for this channel:
       - Cosmic/Space Catastrophes (Asteroids, solar storms, explosions).
       - Ancient Warfare (Alexander the Great, lost Roman Legions, military tactics).
       - Natural Disasters (Record-breaking magnitudes, extreme events).
    3. If trends don't fit directly, use lateral thinking ONLY when the final topic still lands squarely in the 3 pillars or history/mystery.
    4. Generate 5 VIDEO IDEAS with HIGH VIRALITY POTENTIAL today.
    5. Each title MUST follow the "Triple Hook": [Specific Subject] + [Exact Number/Magnitude] + [Adjective/Emoji].
    6. Each title MUST be EXACTLY between 48 and 55 characters in length.
    7. Each idea MUST be about a COMPLETELY DIFFERENT topic than the already-used titles listed above.
    8. ABSOLUTELY EXCLUDE health, medicine, fitness, celebrities, entertainment, sports, or generic current affairs.

    FOR EACH IDEA:
    - Title: Follow the proven Triple Hook formula. 48-55 chars exactly. End with a relevant emoji (💥, 🌍, ⏳).
    - Category: Which of my categories it fits.
    - Justification: Why it will work TODAY.

    MANDATORY JSON FORMAT:
    {{
      "ideas": [
        {{"title": "SHOCKING TITLE 1", "category": "Category A", "justification": "Clear connection to trend X..."}},
        {{"title": "SHOCKING TITLE 2", "category": "Category B", "justification": "..."}},
        {{"title": "SHOCKING TITLE 3", "category": "Category C", "justification": "..."}},
        {{"title": "SHOCKING TITLE 4", "category": "Category D", "justification": "..."}},
        {{"title": "SHOCKING TITLE 5", "category": "Category E", "justification": "..."}}
      ]
    }}
    """
    try:
        response_text = ai_client._generate(prompt)
        # Clean response for JSON
        response_text = response_text.strip().replace("```json", "").replace("```", "")
        response_text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", response_text)
        # Extract JSON block
        if "{" in response_text and "}" in response_text:
            start = response_text.find("{")
            end = response_text.rfind("}") + 1
            if start >= 0 and end > start:
                response_text = response_text[start:end]
        data = json.loads(response_text)
        ideas_count = len(data.get("ideas", []))
        print(f" AI generated {ideas_count} video ideas from trends")
        return data
    except Exception as e:
        print(f" AI trend analysis error: {e}")
        return {"error": f"AI error: {e}"}
