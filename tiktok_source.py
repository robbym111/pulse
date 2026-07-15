"""
tiktok_source.py — pulls TikTok video metadata + comments via TikTokApi.

No paid API needed. Uses a real browser (Playwright) under the hood.
You need an ms_token cookie from tiktok.com — run tiktok_setup.py first.

TikTok aggressively fights scrapers. The two things that actually beat the
"empty response / detected as a bot" wall are (1) a NON-headless browser and
(2) the webkit engine, which has a less-fingerprintable automation surface than
chromium. We try those first and fall back gracefully. We also retry, because
the first request after a cold session often gets shadow-blocked.

The current TikTokApi build dropped keyword video search (api.search.videos),
so we search by hashtag instead: we turn the query into hashtag candidates
(quoted phrases and the artist name, smashed into tags) and pull videos +
their comment threads from each.

Setup (run once):
    python3 tiktok_setup.py
"""

import asyncio
import os
import re
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

from common import clean_text, is_junk
from query_utils import parse_query, relevance_matcher

load_dotenv()

MAX_TEXT_CHARS = 1500
MS_TOKEN = os.environ.get("TIKTOK_MS_TOKEN", "")

# Browser strategies, in order. Headless webkit is stable and needs no display,
# and works fine as long as we resolve each hashtag's .info() before listing its
# videos (that populates the challenge ID TikTok requires). Non-headless is the
# fallback for environments where headless still gets shadow-blocked.
_BROWSER_STRATEGIES = [
    {"browser": "webkit", "headless": True},
    {"browser": "chromium", "headless": True},
    {"browser": "webkit", "headless": False},
    {"browser": "chromium", "headless": False},
]

_FETCH_RETRIES = 3          # per hashtag, against shadow-blocks
_RETRY_SLEEP = 4.0          # seconds between retries


def _impact(view_count, like_count, comment_count, share_count):
    return round(
        (view_count or 0) * 0.01
        + (like_count or 0) * 1.0
        + (comment_count or 0) * 3.0
        + (share_count or 0) * 2.0,
        1,
    )


def _video_to_item(video):
    try:
        d = video.as_dict  # all fields live here, not as attributes
        desc = clean_text(d.get("desc") or "")
        author_d = d.get("author") or {}
        author = author_d.get("uniqueId") if isinstance(author_d, dict) else "unknown"
        author = author or "unknown"
        video_id = str(d.get("id") or "")

        stats = d.get("stats") or d.get("statsV2") or {}

        def _stat(key):
            v = stats.get(key, 0) if isinstance(stats, dict) else 0
            try:
                return int(v or 0)
            except (TypeError, ValueError):
                return 0

        view_count = _stat("playCount")
        like_count = _stat("diggCount")
        comment_count = _stat("commentCount")
        share_count = _stat("shareCount")

        created_utc = int(d.get("createTime") or 0)

        return {
            "platform": "tiktok",
            "type": "post",
            "id": video_id,
            "subreddit": "",
            "venue": f"TikTok · @{author}",
            "post_title": desc[:100] or f"TikTok by @{author}",
            "author": f"@{author}",
            "created_utc": int(created_utc),
            "score": like_count,
            "num_comments": comment_count,
            "upvote_ratio": None,
            "impact": _impact(view_count, like_count, comment_count, share_count),
            "permalink": f"https://www.tiktok.com/@{author}/video/{video_id}",
            "text": desc,
            "view_count": view_count,
            "share_count": share_count,
        }
    except Exception:
        return None


def _comment_to_item(comment, video_author, video_id):
    try:
        d = getattr(comment, "as_dict", None) or {}
        text = clean_text(d.get("text") or "")
        if not text or is_junk(text):
            return None
        user = d.get("user") or {}
        author = (user.get("unique_id") or user.get("uniqueId")
                  if isinstance(user, dict) else None) or "unknown"
        like_count = int(d.get("digg_count") or d.get("diggCount") or 0)
        created_utc = int(d.get("create_time") or d.get("createTime") or 0)
        comment_id = str(d.get("cid") or d.get("id") or "")

        return {
            "platform": "tiktok",
            "type": "comment",
            "id": comment_id,
            "subreddit": "",
            "venue": f"TikTok · @{video_author}",
            "post_title": text[:100],
            "author": f"@{author}",
            "created_utc": int(created_utc),
            "score": like_count,
            "num_comments": 0,
            "upvote_ratio": None,
            "impact": like_count * 1.0,
            "permalink": f"https://www.tiktok.com/@{video_author}/video/{video_id}",
            "text": text,
            "view_count": 0,
            "share_count": 0,
        }
    except Exception:
        return None


def _time_filter_to_days(time_filter):
    return {
        "hour": 1 / 24,
        "day": 1,
        "week": 7,
        "month": 30,
        "year": 365,
        "all": None,
    }.get(time_filter, 7)


def _smash(text):
    """Turn free text into a hashtag-safe token: lowercase, alnum only."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _hashtag_candidates(keyword):
    """
    Build ranked hashtag candidates from a Google-style query.

    For 'phoebe bridgers "lost boys"':
      phrases = ["lost boys"], terms = ["phoebe", "bridgers"]
      → ["phoebebridgers", "phoebebridgerslostboys", "lostboys", ...]

    Ordering is deliberate: ARTIST-specific tags first. A bare song/phrase tag
    like #lostboys is shared with unrelated content (the 1987 film, a Broadway
    musical), so searching it first would burn the whole video budget on noise.
    The artist tag (#phoebebridgers) is the cleanest signal, so it leads.
    """
    phrases, terms = parse_query(keyword)
    candidates = []

    # 1. The artist/bare terms joined (e.g. phoebebridgers) — cleanest signal
    if terms:
        candidates.append(_smash("".join(terms)))

    # 2. Phrase + artist combined (sometimes a real fan tag)
    if phrases and terms:
        candidates.append(_smash("".join(terms) + phrases[0]))

    # 3. Whole query smashed
    candidates.append(_smash(keyword))

    # 4. Each quoted phrase smashed (song/album/tour — noisier, so later)
    for ph in phrases:
        candidates.append(_smash(ph))

    # 5. Individual words as a last resort
    for w in re.findall(r"\w+", keyword.lower()):
        candidates.append(_smash(w))

    # Dedup, drop empties and ultra-short tags (<3 chars = noise)
    seen, out = set(), []
    for c in candidates:
        if len(c) >= 3 and c not in seen:
            seen.add(c)
            out.append(c)
    return out


async def _create_sessions(api):
    """Try browser strategies until one builds a working session."""
    last_err = None
    for strat in _BROWSER_STRATEGIES:
        try:
            print(f"    Opening TikTok session "
                  f"({strat['browser']}, headless={strat['headless']})...")
            await api.create_sessions(
                ms_tokens=[MS_TOKEN],
                num_sessions=1,
                sleep_after=3,
                browser=strat["browser"],
                headless=strat["headless"],
            )
            return strat
        except Exception as e:
            last_err = e
            print(f"    ({strat['browser']} headless={strat['headless']} "
                  f"failed: {str(e)[:80]})")
    raise RuntimeError(f"Could not open any TikTok session. Last error: {last_err}")


async def _videos_for_hashtag(api, htag, want, cutoff, seen_ids, is_relevant):
    """Pull up to `want` relevant videos for one hashtag, retrying on bot-blocks.

    TikTok requires the hashtag's challenge ID before it will serve its video
    feed, so we resolve .info() first. Without this, .videos() silently yields
    nothing. We over-fetch (the feed is full of off-topic videos sharing the
    tag) and keep only those whose description mentions the artist.
    """
    collected = []
    # The feed mixes in off-topic videos, so scan deeper than `want`.
    scan = max(want * 3, 30)
    for attempt in range(1, _FETCH_RETRIES + 1):
        try:
            tag = api.hashtag(name=htag)
            await tag.info()  # resolves the challenge ID — required before .videos()
            async for video in tag.videos(count=scan):
                vid = str(video.id)
                if vid in seen_ids:
                    continue
                item = _video_to_item(video)
                if item is None:
                    continue
                if not is_relevant(item["text"]):
                    continue
                if cutoff:
                    created = datetime.fromtimestamp(item["created_utc"], tz=timezone.utc)
                    if created < cutoff:
                        continue
                seen_ids.add(vid)
                collected.append((video, item))
                if len(collected) >= want:
                    break
            return collected  # success (even if empty list is a real "no results")
        except Exception as e:
            msg = str(e)
            if "empty response" in msg.lower() and attempt < _FETCH_RETRIES:
                print(f"      #{htag}: bot-blocked, retry {attempt}/{_FETCH_RETRIES}...")
                await asyncio.sleep(_RETRY_SLEEP)
                continue
            print(f"      #{htag} failed: {msg[:90]}")
            return collected
    return collected


async def _comments_for_video(video, comments_per_video):
    """
    Pull comments for one video (single best-effort attempt).

    TikTok's comment endpoint is far more aggressively bot-blocked than the
    video feed and returns an empty response when headless. We try once and
    surface whether it was *blocked* (exception) vs. *genuinely empty* (no
    comments) so the caller can stop wasting time once it's clearly blocked.

    Returns (items, blocked: bool).
    """
    vd = video.as_dict
    author_d = vd.get("author") or {}
    author = (author_d.get("uniqueId") if isinstance(author_d, dict) else None) or "unknown"
    video_id = str(vd.get("id") or "")
    out = []
    try:
        async for comment in video.comments(count=comments_per_video):
            c_item = _comment_to_item(comment, author, video_id)
            if c_item:
                out.append(c_item)
            if len(out) >= comments_per_video:
                break
        return out, False
    except Exception:
        return out, True


async def _fetch(keyword, video_limit, comments_per_video, time_filter, since_cutoff=None):
    from TikTokApi import TikTokApi

    if not MS_TOKEN:
        raise RuntimeError("TIKTOK_MS_TOKEN not set in .env\nRun: python3 tiktok_setup.py")

    if since_cutoff is not None:
        cutoff = since_cutoff
    else:
        days = _time_filter_to_days(time_filter)
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days) if days else None

    candidates = _hashtag_candidates(keyword)
    is_relevant = relevance_matcher(keyword)
    phrases, terms = parse_query(keyword)
    print(f"    Hashtag candidates: {', '.join('#' + c for c in candidates)}")
    print(f"    Relevance: phrase{'s' if len(phrases)!=1 else ''} {phrases or '—'} "
          f"OR all terms {terms or '—'}")

    items = []
    async with TikTokApi() as api:
        await _create_sessions(api)

        pairs = []  # (video_obj, item_dict)
        seen_ids = set()
        for htag in candidates:
            if len(pairs) >= video_limit:
                break
            want = video_limit - len(pairs)
            print(f"    Searching #{htag} (want {want})...")
            found = await _videos_for_hashtag(
                api, htag, want, cutoff, seen_ids, is_relevant
            )
            pairs.extend(found)
            print(f"      +{len(found)} relevant videos (total {len(pairs)})")

        for _, item in pairs:
            items.append(item)

        print(f"    Pulling comments from {len(pairs)} videos...")
        consecutive_blocks = 0
        total_comments = 0
        for video, item in pairs:
            comments, blocked = await _comments_for_video(video, comments_per_video)
            items.extend(comments)
            total_comments += len(comments)
            if blocked and not comments:
                consecutive_blocks += 1
            else:
                consecutive_blocks = 0
            # Once TikTok is clearly shadow-blocking the comment endpoint, stop
            # hammering it — video descriptions + engagement are the signal.
            if consecutive_blocks >= 3:
                print("      Comment endpoint is bot-blocked (headless); "
                      "skipping remaining comment fetches.")
                break
        print(f"    Pulled {total_comments} comments total.")

    return items


def fetch_items(keyword, video_limit=20, comments_per_video=30, time_filter="week", since=None):
    """Standard interface matching all other source modules.

    `since` accepts a timezone-aware datetime (from --since) and overrides
    the time_filter-derived cutoff.
    """
    print(f"    Searching TikTok for: {keyword!r}")
    items = asyncio.run(_fetch(keyword, video_limit, comments_per_video, time_filter, since_cutoff=since))
    posts = sum(1 for i in items if i["type"] == "post")
    comments = len(items) - posts
    print(f"    Got {posts} videos + {comments} comments")
    return items
