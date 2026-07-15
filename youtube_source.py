"""
youtube_source.py — pulls video comments via the YouTube Data API v3.

Reliable, free (10k quota units/day is plenty). Get a key at:
  console.cloud.google.com → enable "YouTube Data API v3" → create API key
Add to .env as YOUTUBE_API_KEY.

Interface matches every other source module: fetch_items(...).
"""

import os
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from common import clean_text, is_junk, make_item
from query_utils import relevance_matcher

load_dotenv()

API_BASE = "https://www.googleapis.com/youtube/v3"


def _key():
    k = os.environ.get("YOUTUBE_API_KEY")
    if not k:
        raise RuntimeError("Missing YOUTUBE_API_KEY in .env")
    return k


def _impact(likes, replies):
    return round((likes or 0) + 3.0 * (replies or 0), 1)


def _to_utc(iso):
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except Exception:
        return int(datetime.now(tz=timezone.utc).timestamp())


def _search_videos(keyword, limit, key):
    r = requests.get(
        f"{API_BASE}/search",
        params={
            "part": "snippet", "q": keyword, "type": "video",
            "order": "relevance", "maxResults": min(limit, 50), "key": key,
        },
        timeout=20,
    )
    r.raise_for_status()
    out = []
    for it in r.json().get("items", []):
        vid = it.get("id", {}).get("videoId")
        if not vid:
            continue
        snip = it.get("snippet", {})
        title = snip.get("title", "")
        # Description + channel help the relevance check catch videos whose
        # title alone doesn't name the artist (e.g. "NEW ALBUM ANNOUNCEMENT").
        blob = " ".join([title, snip.get("description", ""), snip.get("channelTitle", "")])
        out.append((vid, title, blob))
    return out


def _video_comments(video_id, video_title, limit, key):
    r = requests.get(
        f"{API_BASE}/commentThreads",
        params={
            "part": "snippet", "videoId": video_id, "order": "relevance",
            "maxResults": min(limit, 100), "textFormat": "plainText", "key": key,
        },
        timeout=20,
    )
    if r.status_code == 403:  # comments disabled
        return []
    r.raise_for_status()

    items = []
    for thread in r.json().get("items", []):
        snip = thread["snippet"]["topLevelComment"]["snippet"]
        text = clean_text(snip.get("textDisplay", ""))
        if is_junk(text):
            continue
        likes = snip.get("likeCount", 0)
        replies = thread["snippet"].get("totalReplyCount", 0)
        items.append(
            make_item(
                platform="youtube",
                type_="comment",
                id_=thread["id"],
                text=text,
                title=video_title,
                author=snip.get("authorDisplayName", ""),
                created_utc=_to_utc(snip.get("publishedAt", "")),
                score=likes,
                num_comments=replies,
                impact=_impact(likes, replies),
                permalink=f"https://youtube.com/watch?v={video_id}&lc={thread['id']}",
                venue=f"YouTube · {video_title[:40]}",
                extra={"like_count": likes, "reply_count": replies},
            )
        )
    return items


def fetch_items(keyword, video_limit=10, comments_per_video=30, raw_query=None):
    """Standard interface. Searches videos, pulls top comments from each.

    `raw_query` (the original Google-style query, e.g. 'dinosaur jr "several got
    away"') drives an on-topic filter so we don't scrape comments off the loosely
    related videos YouTube back-fills a niche search with. Falls back to `keyword`.
    """
    key = _key()
    print(f"    Searching YouTube for: {keyword!r}")
    videos = _search_videos(keyword, video_limit, key)

    is_relevant = relevance_matcher(raw_query or keyword)
    relevant = [(vid, title) for (vid, title, blob) in videos if is_relevant(blob)]
    dropped = len(videos) - len(relevant)
    if dropped:
        print(f"    Kept {len(relevant)}/{len(videos)} videos as on-topic "
              f"(dropped {dropped} off-topic).")

    items = []
    for vid, title in relevant:
        try:
            items.extend(_video_comments(vid, title, comments_per_video, key))
        except Exception as e:
            print(f"    (skipped video {vid}: {e})")
    print(f"    Got {len(items)} comments across {len(relevant)} videos")
    return items
