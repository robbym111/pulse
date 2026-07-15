"""
common.py — shared item shape, text cleaning, and noise filtering.

Every source module builds items through make_item() so the schema can't drift,
and runs text through clean_text() so HTML entities and boilerplate never reach
the scorer (you stop paying Claude to read scaffolding).
"""

import html
import re

MAX_TEXT_CHARS = 1500

# Boilerplate / scaffolding that is not fan opinion. These match the START of
# the text (after cleaning) or are exact-ish scaffolding, so a fan post that
# merely mentions "submitted by" in passing is NOT dropped.
JUNK_PREFIXES = (
    "please do not comment on just the scores",
    "this thread is for",
    "welcome to the daily",
    "official discussion thread",
)
JUNK_EXACT = ("[deleted]", "[removed]", "view this post on instagram")

# A post whose text is basically just a URL + title with no body carries no
# sentiment signal. We detect "link-only" by stripping and measuring.
_URL_RE = re.compile(r"https?://\S+")
_WS_RE = re.compile(r"\s+")


def clean_text(raw):
    """Decode HTML entities, strip URLs/markup noise, collapse whitespace."""
    if not raw:
        return ""
    t = html.unescape(raw)            # &#32; &amp; etc.
    t = t.replace("\u200b", "")       # zero-width space
    t = _URL_RE.sub("", t)            # drop bare URLs
    t = _WS_RE.sub(" ", t).strip()
    return t[:MAX_TEXT_CHARS]


def is_junk(text):
    """True if the cleaned text is boilerplate, empty, or too short to score."""
    if not text:
        return True
    low = text.lower().strip()
    if low in JUNK_EXACT:
        return True
    if any(low.startswith(p) for p in JUNK_PREFIXES):
        return True
    # RSS submission scaffolding: a title followed only by "submitted by /u/..."
    # with no actual body. Real fan posts have substantive text after.
    if "submitted by" in low:
        body = low.split("submitted by")[0].strip()
        if len(body.split()) < 8:  # just a headline, no opinion
            return True
    if len(text) < 3:
        return True
    return False


def make_item(
    *,
    platform,
    type_,
    id_,
    text,
    title="",
    author="",
    created_utc=0,
    score=0,
    num_comments=0,
    impact=0.0,
    permalink="",
    venue="",
    subreddit="",
    extra=None,
):
    """
    Single source of truth for item shape. Every source returns these keys,
    so output/brief/combined never have to guess what's present.
    """
    item = {
        "platform": platform,
        "type": type_,
        "id": str(id_),
        "subreddit": subreddit,
        "venue": venue or _default_venue(platform, subreddit, author),
        "post_title": (title or text)[:100],
        "author": author,
        "created_utc": int(created_utc or 0),
        "score": score or 0,
        "num_comments": num_comments or 0,
        "upvote_ratio": None,
        "impact": round(float(impact or 0), 1),
        "permalink": permalink,
        "text": text,
        # placeholders so downstream .get() calls are always safe
        "like_count": 0,
        "retweet_count": 0,
        "reply_count": 0,
        "quote_count": 0,
        "view_count": 0,
        "share_count": 0,
    }
    if extra:
        item.update(extra)
    return item


def _default_venue(platform, subreddit, author):
    if platform == "reddit" and subreddit:
        return f"r/{subreddit}"
    if platform == "twitter":
        return f"Twitter/X · @{author}" if author else "Twitter/X"
    if platform == "youtube":
        return "YouTube"
    if platform == "tiktok":
        return f"TikTok · {author}" if author else "TikTok"
    if platform == "news":
        return author or "Music press"
    return platform


# Display labels for the five platforms — used by output.py and combined_report.py
PLATFORM_LABELS = {
    "reddit": "Reddit",
    "twitter": "Twitter/X",
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "news": "Editorial",
}
