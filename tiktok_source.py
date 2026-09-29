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

For music, the richer signal is the videos made WITH the song's sound, so on
top of hashtags we also:
  1. find the artist's own account (account search on the bare terms of the
     query) and pull their recent videos,
  2. harvest sounds from every video we've seen, keeping the ones credited to
     the artist or titled like a quoted phrase in the query,
  3. pull the videos using the top few sounds (plus any sound links passed in
     via `sounds`).
Each video records how we found it (`tiktok_via`) and its sound, so the brief
can report per-sound adoption.

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


def _music(d):
    m = d.get("music") or {}
    return m if isinstance(m, dict) else {}


def _video_to_item(video, via="hashtag"):
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
        music = _music(d)

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
            "tiktok_via": via,
            "sound_id": str(music.get("id") or ""),
            "sound_title": music.get("title") or "",
            "sound_author": music.get("authorName") or "",
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


# --------------------------------------------------------------------------
# Artist account + sounds
# --------------------------------------------------------------------------

_SOUND_ID_RE = re.compile(r"/music/[^/?#]*?-?(\d{8,})")
_HANDLE_SUFFIX = re.compile(r"(official|music|vevo|tv|hq)$")


def parse_sound_ref(ref):
    """Sound URL (tiktok.com/music/Kill-Me-7673480507100121104) or bare id → id.
    Returns None for anything else, e.g. a /discover/ search page."""
    ref = (ref or "").strip()
    if ref.isdigit():
        return ref
    m = _SOUND_ID_RE.search(ref)
    return m.group(1) if m else None


def _artist_name(keyword):
    """The bare (unquoted) terms of the query, e.g. 'phoebe bridgers' for
    'phoebe bridgers "lost boys"'. None if the query is only phrases."""
    _, terms = parse_query(keyword)
    return " ".join(terms) or None


def _is_artist_handle(name, artist):
    """Strict: the handle/name IS the artist (phoebebridgers, PhoebeBridgersOfficial),
    so fan pages like phoebebridgersfanpage don't pass."""
    a = _smash(artist or "")
    return len(a) >= 4 and _HANDLE_SUFFIX.sub("", _smash(name or "")) == a


def _credits_artist(author_name, artist):
    """Loose: a sound's credit line names the artist ('Phoebe Bridgers & Bo Burnham')."""
    a = _smash(artist or "")
    return len(a) >= 4 and a in _smash(author_name or "")


def _sound_matches(music, artist, phrases):
    title = (music.get("title") or "").lower()
    if artist and _credits_artist(music.get("authorName"), artist):
        return True
    return any(p.lower() in title for p in phrases)


def _rank_sounds(video_dicts, artist, phrases):
    """Count how often each on-topic sound appears across videos we've seen."""
    counts, info = {}, {}
    for d in video_dicts:
        m = _music(d)
        sid = str(m.get("id") or "")
        if not sid or not _sound_matches(m, artist, phrases):
            continue
        counts[sid] = counts.get(sid, 0) + 1
        info[sid] = m
    return [(sid, info[sid]) for sid in sorted(counts, key=counts.get, reverse=True)]


async def _find_artist_account(api, artist):
    """Best-effort: the artist's own account from TikTok's account search."""
    try:
        cands = []
        async for user in api.search.users(artist, count=8):
            cands.append(user)
        for user in cands:
            if _is_artist_handle(getattr(user, "username", ""), artist):
                return user
        for user in cands[:3]:  # fall back to display names
            info = await user.info()
            u = (info.get("userInfo") or {}).get("user") or {}
            if u.get("verified") and _is_artist_handle(u.get("nickname"), artist):
                return user
    except Exception as e:
        print(f"      account search failed: {str(e)[:90]}")
    return None


async def _videos_from(feed, via, want, cutoff, seen_ids, extra=None):
    """Drain an async video feed into (video, item) pairs, skipping dupes/old."""
    out = []
    try:
        async for video in feed:
            item = _video_to_item(video, via=via)
            if item is None or item["id"] in seen_ids:
                continue
            if cutoff and item["created_utc"] and \
                    datetime.fromtimestamp(item["created_utc"], tz=timezone.utc) < cutoff:
                continue
            if extra:
                item.update(extra)
            seen_ids.add(item["id"])
            out.append((video, item))
            if len(out) >= want:
                break
    except Exception as e:
        print(f"      ({via} feed stopped: {str(e)[:90]})")
    return out


async def _sound_videos(api, sound_id, want, cutoff, seen_ids):
    """Videos made with one sound. Tags each with the sound's total video count."""
    sound = api.sound(id=sound_id)
    title, author, total = "", "", None
    try:
        info = await sound.info()
        mi = info.get("musicInfo") or {}
        m, st = mi.get("music") or {}, mi.get("stats") or {}
        title, author = m.get("title") or "", m.get("authorName") or ""
        total = st.get("videoCount")
    except Exception as e:
        print(f"      sound {sound_id} info failed: {str(e)[:90]}")
    print(f"    Sound: {title or sound_id} — {author or '?'}"
          + (f" · {total:,} videos on TikTok" if isinstance(total, int) else ""))
    extra = {"sound_id": sound_id, "sound_video_count": total}
    if title:
        extra["sound_title"] = title
    if author:
        extra["sound_author"] = author
    # Sound feeds aren't chronological, so scan deeper when a cutoff applies.
    scan = want * 3 if cutoff else want
    pairs = await _videos_from(sound.videos(count=scan), "sound", want, cutoff, seen_ids, extra)
    print(f"      +{len(pairs)} videos using this sound")
    return pairs


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


async def _fetch(keyword, video_limit, comments_per_video, time_filter, since_cutoff=None,
                 sounds=None, max_sounds=3, sound_videos=20, artist_videos=10):
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
    artist = _artist_name(keyword)
    print(f"    Hashtag candidates: {', '.join('#' + c for c in candidates)}")
    print(f"    Relevance: phrase{'s' if len(phrases)!=1 else ''} {phrases or '—'} "
          f"OR all terms {terms or '—'}")

    explicit = []
    for ref in sounds or []:
        sid = parse_sound_ref(ref)
        if sid:
            explicit.append(sid)
        else:
            print(f"    ! Not a sound link, skipping: {ref}\n"
                  f"      (Use a tiktok.com/music/... link. /discover/ pages are search "
                  f"pages; the artist search already covers them.)")

    items = []
    async with TikTokApi() as api:
        await _create_sessions(api)

        pairs = []  # (video_obj, item_dict)
        seen_ids = set()

        # 1. Hashtags
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

        # 2. The artist's own account
        seen_dicts = [v.as_dict for v, _ in pairs]
        if artist and artist_videos:
            print(f"    Looking for {artist}'s TikTok account...")
            user = await _find_artist_account(api, artist)
            if user:
                print(f"      Found @{getattr(user, 'username', '?')}")
                own = await _videos_from(user.videos(count=artist_videos), "artist_account",
                                         artist_videos, cutoff, seen_ids)
                pairs.extend(own)
                seen_dicts += [v.as_dict for v, _ in own]
                print(f"      +{len(own)} of their recent videos")
            else:
                print("      No matching account found.")

        # 3. Sounds: explicit links first, then the most common on-topic sounds
        sound_ids = list(explicit)
        if max_sounds:
            for sid, m in _rank_sounds(seen_dicts, artist, phrases):
                if len(sound_ids) >= len(explicit) + max_sounds:
                    break
                if sid not in sound_ids:
                    sound_ids.append(sid)
        if sound_ids:
            print(f"    Pulling videos for {len(sound_ids)} sound(s)...")
        for sid in sound_ids:
            pairs.extend(await _sound_videos(api, sid, sound_videos, cutoff, seen_ids))

        for _, item in pairs:
            items.append(item)

        # Comments: the most-engaged videos first, since the endpoint gets
        # bot-blocked and we may not get through all of them.
        pairs.sort(key=lambda p: p[1]["impact"], reverse=True)
        print(f"    Pulling comments from {len(pairs)} videos...")
        consecutive_blocks = 0
        total_comments = 0
        for video, item in pairs:
            comments, blocked = await _comments_for_video(video, comments_per_video)
            for c in comments:  # carry the sound so comments count toward it
                for k in ("sound_id", "sound_title", "sound_author", "tiktok_via"):
                    c[k] = item.get(k)
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


def fetch_items(keyword, video_limit=20, comments_per_video=30, time_filter="week", since=None,
                sounds=None, max_sounds=3, sound_videos=20, artist_videos=10):
    """Standard interface matching all other source modules.

    `since` accepts a timezone-aware datetime (from --since) and overrides
    the time_filter-derived cutoff. `sounds` is a list of sound links/ids to
    always pull; `max_sounds` more are found automatically (0 = off).
    `artist_videos` recent videos are pulled from the artist's own account.
    """
    print(f"    Searching TikTok for: {keyword!r}")
    items = asyncio.run(_fetch(keyword, video_limit, comments_per_video, time_filter,
                               since_cutoff=since, sounds=sounds, max_sounds=max_sounds,
                               sound_videos=sound_videos, artist_videos=artist_videos))
    posts = sum(1 for i in items if i["type"] == "post")
    comments = len(items) - posts
    print(f"    Got {posts} videos + {comments} comments")
    return items


# --------------------------------------------------------------------------
# Brief section: per-sound adoption
# --------------------------------------------------------------------------

def _sound_url(sid, title):
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title or "sound").strip("-") or "sound"
    return f"https://www.tiktok.com/music/{slug}-{sid}"


def sound_markdown(items, top_creators=3):
    """Markdown lines summarizing the sounds pulled (videos found via a sound)."""
    by_sound = {}
    for it in items:
        if it.get("tiktok_via") != "sound" or not it.get("sound_id"):
            continue
        by_sound.setdefault(it["sound_id"], []).append(it)
    if not by_sound:
        return []

    L = ["---", "## TikTok sounds — who's making videos with the music", ""]
    L.append("| Sound | Videos on TikTok | Pulled here | Views (pulled) | Avg sentiment | Top creators on it |")
    L.append("|---|---|---|---|---|---|")
    for sid, its in sorted(by_sound.items(), key=lambda kv: -len(kv[1])):
        vids = [i for i in its if i["type"] == "post"]
        first = vids[0] if vids else its[0]
        title = first.get("sound_title") or sid
        author = first.get("sound_author") or ""
        total = first.get("sound_video_count")
        views = sum(i.get("view_count", 0) or 0 for i in vids)
        scores = [i.get("sentiment_score", 0.0) for i in its if "sentiment_score" in i]
        avg = f"{sum(scores) / len(scores):+.2f}" if scores else "—"
        tops = sorted(vids, key=lambda i: i.get("impact", 0), reverse=True)[:top_creators]
        creators = ", ".join(f"[{i['author']}]({i['permalink']})" for i in tops) or "—"
        name = f"[{title}]({_sound_url(sid, title)})" + (f" — {author}" if author else "")
        L.append(f"| {name.replace('|', '/')} | {f'{total:,}' if isinstance(total, int) else '—'} | "
                 f"{len(vids)} videos, {len(its) - len(vids)} comments | {views:,} | {avg} | {creators} |")
    L.append("")
    L.append("*\"Videos on TikTok\" is TikTok's own count for the sound. The rest covers "
             "only the videos pulled in this run.*")
    L.append("")
    return L
