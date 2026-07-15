"""
editorial_source.py — pulls music-press coverage from outlet RSS feeds.

No API key needed — uses public RSS via feedparser. We match the keyword against
recent articles from a curated set of music outlets, then keep ones long enough
to carry a real opinion.

Tune FEEDS to the outlets you care about. fetch_items(...) matches the standard
source interface used by combined_report.py.
"""

from datetime import datetime, timezone, timedelta
from time import mktime

import feedparser

from common import clean_text, is_junk, make_item

# Curated music-press RSS feeds. Add/remove to taste.
FEEDS = {
    "Pitchfork": "https://pitchfork.com/feed/feed-news/rss",
    "Stereogum": "https://www.stereogum.com/feed/",
    "Rolling Stone": "https://www.rollingstone.com/music/feed/",
    "NME": "https://www.nme.com/news/music/feed",
    "Consequence": "https://consequence.net/feed/",
    "The Guardian Music": "https://www.theguardian.com/music/rss",
    "Billboard": "https://www.billboard.com/feed/",
    "Paste": "https://www.pastemagazine.com/feeds/music/rss",
    "DIY": "https://diymag.com/feed",
    "Clash": "https://www.clashmusic.com/feed/",
}

# Reach tiers for impact weighting
TIER_1 = {"pitchfork", "rolling stone", "billboard", "the guardian music", "nme", "stereogum"}
TIER_2 = {"consequence", "clash", "diy", "paste"}


def _impact(outlet):
    o = outlet.lower()
    if o in TIER_1:
        return 100.0
    if o in TIER_2:
        return 60.0
    return 30.0


def _entry_utc(entry):
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            return int(mktime(t))
    return int(datetime.now(tz=timezone.utc).timestamp())


def _matches(entry, keyword):
    kw = keyword.lower()
    blob = " ".join(
        [getattr(entry, "title", ""), getattr(entry, "summary", "")]
    ).lower()
    return kw in blob


def fetch_items(keyword, max_articles=15, min_words=200, recent_days=30):
    """
    Standard interface. Scans curated feeds, keeps recent articles matching the
    keyword. min_words filters out blurbs that carry no real critical content.
    """
    print(f"    Scanning {len(FEEDS)} music-press feeds for: {keyword!r}")
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=recent_days)
    items = []

    for outlet, url in FEEDS.items():
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"    (feed failed: {outlet}: {e})")
            continue

        for entry in feed.entries:
            if not _matches(entry, keyword):
                continue
            created = datetime.fromtimestamp(_entry_utc(entry), tz=timezone.utc)
            if created < cutoff:
                continue

            title = clean_text(getattr(entry, "title", ""))
            summary = clean_text(getattr(entry, "summary", ""))
            text = f"{title}. {summary}".strip()
            if is_junk(text) or len(text.split()) < min_words // 10:
                # RSS summaries are short; relax the word gate to ~1/10 of min_words
                # (full-article scraping would honor min_words exactly)
                if len(text.split()) < 12:
                    continue

            items.append(
                make_item(
                    platform="news",
                    type_="review",
                    id_=getattr(entry, "id", entry.link),
                    text=text,
                    title=title,
                    author=outlet,
                    created_utc=_entry_utc(entry),
                    impact=_impact(outlet),
                    permalink=getattr(entry, "link", ""),
                    venue=outlet,
                    subreddit=outlet,  # reuse for CSV venue column
                )
            )
            if len(items) >= max_articles:
                break
        if len(items) >= max_articles:
            break

    print(f"    Got {len(items)} editorial articles")
    return items
