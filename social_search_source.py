"""
social_search_source.py — pulls Twitter/X (and optionally Threads) posts via
the Brave Search API's site: filter.

No Twitter API key needed. Brave indexes public tweets and returns the post text
as search snippets. Free tier = 2,000 queries/month.

Get a key: https://api.search.brave.com (free signup)
Add to .env: BRAVE_API_KEY=...

Limitations vs. native Twitter API:
  - Results are curated by search index, not chronological
  - Engagement counts (likes/RTs) are not available
  - Threads.net is not yet indexed by Brave
  - Freshness: 'pd' = past day, 'pw' = past week, 'pm' = past month
"""

import gzip
import json
import os
import re
import time
import urllib.parse
import urllib.request

from dotenv import load_dotenv

load_dotenv()

BRAVE_API = "https://api.search.brave.com/res/v1/web/search"
REQUEST_DELAY = 1.0
MAX_TEXT_CHARS = 1000

# Sites to search — Threads disabled until Brave indexes it
SOCIAL_SITES = {
    "twitter": "x.com",
    # "threads": "threads.net",  # not yet indexed by Brave
}

# Noise patterns — off-topic results that match keyword but aren't about it
_NOISE_RE = re.compile(
    r"(buy now|shop|discount|sale|promo|click here|subscribe|newsletter|"
    r"follow us|cookie|privacy policy|terms of service)",
    re.IGNORECASE,
)


def _key():
    k = os.environ.get("BRAVE_API_KEY")
    if not k:
        raise RuntimeError(
            "Missing BRAVE_API_KEY. Get a free key at https://api.search.brave.com "
            "and add it to your .env."
        )
    return k


def _brave_search(query, count=20, freshness="pw"):
    params = urllib.parse.urlencode({
        "q": query,
        "count": min(count, 20),
        "freshness": freshness,
        "text_decorations": 0,
    })
    url = f"{BRAVE_API}?{params}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "X-Subscription-Token": _key(),
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
    try:
        raw = gzip.decompress(raw)
    except Exception:
        pass
    return json.loads(raw)


def _clean_text(html_text):
    """Strip HTML tags and decode entities from Brave snippets."""
    text = re.sub(r"<[^>]+>", "", html_text or "")
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#x27;", "'", text)
    text = re.sub(r"&#\w+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_handle(url):
    """Pull @handle from x.com/handle/status/... URLs."""
    m = re.match(r"https?://x\.com/([^/]+)/status/", url or "")
    return f"@{m.group(1)}" if m else ""


def _is_on_topic(keyword, text, url):
    """Basic relevance check — require meaningful keyword overlap in text+url."""
    terms = [t.lower() for t in re.split(r"\s+", keyword) if len(t) > 2]
    blob = (text + " " + url).lower()
    hits = sum(1 for t in terms if t in blob)
    return hits >= max(1, len(terms) // 2)


def fetch_items(keyword, result_limit=30, freshness="pw"):
    """
    freshness: 'pd' = past day, 'pw' = past week, 'pm' = past month
    """
    items = []
    seen_urls = set()

    for platform, site in SOCIAL_SITES.items():
        query = f'site:{site} {keyword}'
        print(f"    Searching {site} for: {keyword!r} (freshness={freshness})")
        try:
            data = _brave_search(query, count=result_limit, freshness=freshness)
            results = data.get("web", {}).get("results", [])
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            print(f"    (skipped {site}: {e})")
            continue

        for res in results:
            url = res.get("url", "")
            if not url or url in seen_urls:
                continue

            raw_desc = res.get("description", "") or res.get("extra_snippets", [""])[0]
            text = _clean_text(raw_desc)
            title = _clean_text(res.get("title", ""))

            # Use description if it has content, else fall back to title
            body = text if len(text) > len(title) else f"{title} {text}".strip()
            body = body[:MAX_TEXT_CHARS]

            if not body:
                continue

            # Drop off-topic noise
            if not _is_on_topic(keyword, body, url):
                continue
            if _NOISE_RE.search(body):
                continue

            seen_urls.add(url)
            handle = _extract_handle(url) if platform == "twitter" else ""
            venue = f"Twitter/X · {handle}" if handle else f"Twitter/X"

            items.append({
                "type": "post",
                "id": url.split("/")[-1][:20],
                "subreddit": "",
                "venue": venue,
                "post_title": title[:120],
                "author": handle or site,
                "created_utc": 0,  # Brave doesn't expose tweet timestamps
                "score": 0,
                "num_comments": 0,
                "upvote_ratio": None,
                "impact": 0,
                "permalink": url,
                "text": body,
            })

    print(f"    Got {len(items)} on-topic social posts")
    return items
