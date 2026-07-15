"""
twitter_source.py — pulls tweets via twscrape (no paid API needed).

twscrape works by authenticating real Twitter accounts and scraping through
them. You need at least one account. More accounts = higher rate limits and
less risk of a single account getting flagged.

First-time setup (run once, not every time):
    python3 twitter_setup.py

That script adds your accounts and runs the login flow. Sessions are stored
locally in a .twscrape/ folder and reused on every subsequent run.

Impact score mirrors reddit_source: engagement-weighted, replies count more
than likes because a reply is higher-effort than a like.
"""

import asyncio
import os
from datetime import datetime, timezone

from twscrape import API, gather
from dotenv import load_dotenv
from query_utils import for_twitter

from common import clean_text, is_junk

load_dotenv()

MAX_TEXT_CHARS = 1500
TWSCRAPE_DB = os.environ.get("TWSCRAPE_DB", ".twscrape/accounts.db")


def _impact(like_count, reply_count, retweet_count, quote_count):
    """
    Engagement-weighted impact for tweets.
    Replies + quotes weighted highest (active engagement).
    Retweets next (amplification). Likes last (passive).
    """
    return round(
        (like_count or 0) * 1.0
        + (reply_count or 0) * 3.0
        + (retweet_count or 0) * 2.0
        + (quote_count or 0) * 2.5,
        1,
    )


def _tweet_to_item(tweet):
    text = clean_text(tweet.rawContent or "")
    like_count = getattr(tweet, "likeCount", 0) or 0
    reply_count = getattr(tweet, "replyCount", 0) or 0
    retweet_count = getattr(tweet, "retweetCount", 0) or 0
    quote_count = getattr(tweet, "quoteCount", 0) or 0

    username = ""
    if tweet.user:
        username = tweet.user.username or ""

    created = tweet.date or datetime.now(tz=timezone.utc)
    created_utc = int(created.timestamp())

    return {
        "type": "post",
        "id": str(tweet.id),
        "subreddit": "",
        "venue": f"Twitter/X · @{username}" if username else "Twitter/X",
        "post_title": text[:100],
        "author": f"@{username}" if username else "@unknown",
        "created_utc": created_utc,
        "score": like_count,
        "num_comments": reply_count,
        "upvote_ratio": None,
        "impact": _impact(like_count, reply_count, retweet_count, quote_count),
        "permalink": f"https://x.com/{username}/status/{tweet.id}",
        "text": text,
        "retweet_count": retweet_count,
        "quote_count": quote_count,
    }


async def _fetch(keyword, limit, since, lang):
    api = API(TWSCRAPE_DB)

    # Check we have at least one logged-in account
    accounts = await api.pool.get_all()
    active = [a for a in accounts if a.active]
    if not active:
        raise RuntimeError(
            "No active twscrape accounts found.\n"
            "Run: python3 twitter_setup.py\n"
            "to add and log in your Twitter account(s)."
        )

    query = for_twitter(keyword)
    if lang:
        query += f" lang:{lang}"
    if since:
        query += f" since:{since}"

    # Pull search results
    tweets = await gather(api.search(query, limit=limit))
    items = [_tweet_to_item(t) for t in tweets if t.rawContent]
    return [it for it in items if not is_junk(it["text"])]


def _time_filter_to_since(time_filter):
    from datetime import timedelta
    now = datetime.now(tz=timezone.utc)
    delta = {
        "hour":  timedelta(hours=1),
        "day":   timedelta(days=1),
        "week":  timedelta(weeks=1),
        "month": timedelta(days=30),
        "year":  timedelta(days=365),
        "all":   None,
    }.get(time_filter)
    if delta is None:
        return None
    return (now - delta).strftime("%Y-%m-%d")


def fetch_items(keyword, limit=100, time_filter="week", lang="en", since=None):
    """Standard interface matching all other source modules.

    `since` accepts a timezone-aware datetime (from --since) and overrides
    the time_filter-derived date string.
    """
    if since is not None:
        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        since_str = _time_filter_to_since(time_filter)
    print(f"    Searching Twitter/X for: {keyword!r}"
          + (f" since:{since_str}" if since_str else ""))
    items = asyncio.run(_fetch(keyword, limit, since_str, lang))
    print(f"    Got {len(items)} tweets")
    return items


# Legacy alias
def fetch_tweets(keyword, limit=100, since=None, lang="en"):
    return asyncio.run(_fetch(keyword, limit, since, lang))
