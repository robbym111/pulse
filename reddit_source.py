"""
reddit_source.py — pulls posts + comments via Reddit's public RSS/Atom feed.

No credentials required. Reddit's search RSS is public and live.
Comments are fetched from each post's own .rss comment feed.
"""

import time
import datetime
import re
import json
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

from common import clean_text, is_junk

REQUEST_DELAY = 3.0
MAX_TEXT_CHARS = 1500
NS = {"atom": "http://www.w3.org/2005/Atom"}

_RSS_HEADERS = {
    "User-Agent": "reddit-pulse/0.4 (public RSS reader)",
    "Accept": "application/atom+xml, application/xml, text/xml",
}
_JSON_HEADERS = {
    "User-Agent": "reddit-pulse/0.4 (public RSS reader)",
    "Accept": "application/json",
}


def _fetch(url, headers, retries=4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = 15 * (attempt + 1)
                print(f"    (rate limited, waiting {wait}s...)")
                time.sleep(wait)
            else:
                raise


def _impact(score, num_comments, upvote_ratio):
    base = (score or 0) + 2.0 * (num_comments or 0)
    return round(base * (0.5 + (upvote_ratio or 0.5)), 1)


def _parse_feed(xml_text):
    root = ET.fromstring(xml_text)
    entries = root.findall("atom:entry", NS)
    posts = []
    for entry in entries:
        title = (entry.findtext("atom:title", "", NS) or "").strip()
        link_el = entry.find("atom:link", NS)
        permalink = link_el.attrib.get("href", "") if link_el is not None else ""
        content = entry.findtext("atom:content", "", NS) or ""
        author = entry.findtext("atom:author/atom:name", "[deleted]", NS) or "[deleted]"
        updated = entry.findtext("atom:updated", "", NS) or ""
        raw_id = entry.findtext("atom:id", "", NS) or ""
        post_id = raw_id.split("_")[-1] if "_" in raw_id else raw_id.split("/")[-1]

        cat_el = entry.find("atom:category", NS)
        subreddit = cat_el.attrib.get("term", "") if cat_el is not None else ""
        if not subreddit:
            m = re.search(r"/r/([^/]+)/", permalink)
            subreddit = m.group(1) if m else ""

        body = re.sub(r"<[^>]+>", " ", content).strip()
        body = re.sub(r"\s+", " ", body)
        text = clean_text(f"{title}. {body}")

        created_utc = 0
        if updated:
            try:
                dt = datetime.datetime.fromisoformat(updated.replace("Z", "+00:00"))
                created_utc = int(dt.timestamp())
            except Exception:
                pass

        if is_junk(text):
            continue

        posts.append({
            "platform": "reddit",
            "type": "post",
            "id": post_id,
            "subreddit": subreddit,
            "venue": f"r/{subreddit}" if subreddit else "",
            "post_title": title,
            "author": author,
            "created_utc": created_utc,
            "score": 0,
            "num_comments": 0,
            "upvote_ratio": None,
            "impact": 0,
            "permalink": permalink,
            "text": text[:MAX_TEXT_CHARS],
        })
    return posts


def _enrich_post(post):
    """Fetch live score/num_comments for a post via JSON API (best-effort)."""
    pid = post["id"]
    subreddit = post["subreddit"]
    if not pid or not subreddit:
        return
    url = f"https://www.reddit.com/r/{subreddit}/comments/{pid}/.json?limit=1"
    try:
        raw = _fetch(url, _JSON_HEADERS)
        data = json.loads(raw)
        p = data[0]["data"]["children"][0]["data"]
        post["score"] = p.get("score", 0)
        post["num_comments"] = p.get("num_comments", 0)
        post["upvote_ratio"] = p.get("upvote_ratio")
        post["impact"] = _impact(post["score"], post["num_comments"], post["upvote_ratio"])
        time.sleep(REQUEST_DELAY)
    except Exception:
        pass


def _fetch_comments(post, limit):
    permalink = post.get("permalink", "")
    if not permalink or limit <= 0:
        return []
    url = f"{permalink.rstrip('/')}.rss?limit={min(limit, 50)}&sort=top"
    try:
        xml_text = _fetch(url, _RSS_HEADERS)
    except Exception as e:
        print(f"    (skipped comments on {post.get('id')}: {e})")
        return []

    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []

    comments = []
    for entry in root.findall("atom:entry", NS)[1:]:  # skip first (the post itself)
        content = entry.findtext("atom:content", "", NS) or ""
        author = entry.findtext("atom:author/atom:name", "[deleted]", NS) or "[deleted]"
        link_el = entry.find("atom:link", NS)
        cpermalink = link_el.attrib.get("href", "") if link_el is not None else ""
        updated = entry.findtext("atom:updated", "", NS) or ""
        raw_id = entry.findtext("atom:id", "", NS) or ""
        cid = raw_id.split("_")[-1] if "_" in raw_id else raw_id.split("/")[-1]

        ctext = re.sub(r"<[^>]+>", " ", content).strip()
        ctext = re.sub(r"\s+", " ", ctext)
        ctext = re.split(r"submitted by", ctext)[0].strip()
        ctext = clean_text(ctext)

        if is_junk(ctext):
            continue

        created_utc = 0
        if updated:
            try:
                dt = datetime.datetime.fromisoformat(updated.replace("Z", "+00:00"))
                created_utc = int(dt.timestamp())
            except Exception:
                pass

        comments.append({
            "platform": "reddit",
            "type": "comment",
            "id": cid,
            "subreddit": post.get("subreddit", ""),
            "venue": post.get("venue", ""),
            "post_title": post.get("post_title", ""),
            "author": author,
            "created_utc": created_utc,
            "score": 0,
            "num_comments": 0,
            "upvote_ratio": None,
            "impact": 0,
            "permalink": cpermalink,
            "text": ctext[:MAX_TEXT_CHARS],
        })
    return comments


def fetch_items(keyword, subreddits, time_filter, sort, post_limit, comments_per_post):
    items = []
    seen_ids = set()
    rss_sort = "new" if sort in ("new", "relevance") else sort

    for sub in subreddits:
        params = urllib.parse.urlencode({
            "q": keyword,
            "sort": rss_sort,
            "restrict_sr": "on",
            "t": time_filter,
        })
        url = f"https://www.reddit.com/r/{sub}/search.rss?{params}"
        try:
            xml_text = _fetch(url, _RSS_HEADERS)
            posts = _parse_feed(xml_text)
            for p in posts:
                if p["id"] and p["id"] not in seen_ids:
                    seen_ids.add(p["id"])
                    items.append(p)
            print(f"    r/{sub}: {len(posts)} posts")
            time.sleep(REQUEST_DELAY)
        except Exception as e:
            print(f"    (skipped r/{sub}: {e})")

    posts = items[:post_limit]

    print(f"  Enriching {len(posts)} posts with live scores...")
    for p in posts:
        _enrich_post(p)

    all_items = []
    if comments_per_post > 0:
        print(f"  Fetching up to {comments_per_post} comments per post...")
    for p in posts:
        all_items.append(p)
        if comments_per_post > 0:
            comments = _fetch_comments(p, comments_per_post)
            all_items.extend(comments)
            time.sleep(REQUEST_DELAY)

    return all_items
