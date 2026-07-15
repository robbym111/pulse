#!/usr/bin/env python3
"""
reddit-pulse: sentiment + impact analysis for any keyword across Reddit and Twitter/X.

Usage:
    python main.py "Lost Boys" --subreddits indieheads,popheads,phoebebridgers
    python main.py "Lost Boys" --sources reddit,twitter
    python main.py "your keyword" --sources twitter --tweet-limit 200

Run `python main.py --help` for everything.
"""

import argparse
import sys
from datetime import datetime

from reddit_source import fetch_items
from twitter_source import fetch_items as twitter_fetch_items
from claude_sentiment import score_items
from output import print_summary, write_csv


def parse_args():
    p = argparse.ArgumentParser(
        description="Reddit + Twitter sentiment & impact analysis via Claude API.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("keyword", help='Search term, e.g. "Lost Boys" or "Phoebe Bridgers"')

    # Source selection
    p.add_argument(
        "--sources",
        default="reddit",
        help='Comma-separated sources: "reddit", "twitter", or "reddit,twitter"',
    )

    # Reddit flags
    p.add_argument(
        "--subreddits",
        default="all",
        help='Comma-separated subreddits (no r/ prefix). Use "all" for site-wide.',
    )
    p.add_argument(
        "--time",
        default="week",
        choices=["hour", "day", "week", "month", "year", "all"],
        help="Reddit time window.",
    )
    p.add_argument("--post-limit", type=int, default=40, help="Max Reddit posts to pull.")
    p.add_argument(
        "--comments-per-post",
        type=int,
        default=20,
        help="Top comments per Reddit post (0 = posts only).",
    )
    p.add_argument(
        "--sort",
        default="relevance",
        choices=["relevance", "new", "top", "hot", "comments"],
    )

    # Twitter flags
    p.add_argument("--tweet-limit", type=int, default=100, help="Max tweets to pull.")
    p.add_argument(
        "--tweet-since",
        default=None,
        help='Only tweets after this date, e.g. "2025-06-01".',
    )
    p.add_argument(
        "--tweet-lang",
        default="en",
        help='Language filter for tweets. Pass "any" for no filter.',
    )

    # Scoring flags
    p.add_argument(
        "--model",
        default="claude-haiku-4-5-20251001",
        help="Anthropic model. Haiku = cheap/fast. Sonnet = more nuance.",
    )
    p.add_argument("--batch-size", type=int, default=15, help="Items per Claude API call.")

    # Output flags
    p.add_argument("--csv", default=None, help="Output CSV path.")
    p.add_argument("--top-n", type=int, default=8, help="Top-impact items in terminal.")

    return p.parse_args()


def main():
    args = parse_args()
    sources = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
    items = []

    # ── Reddit ────────────────────────────────────────────────────────────────
    if "reddit" in sources:
        subs = [s.strip() for s in args.subreddits.split(",") if s.strip()]
        print(f"\n  [Reddit] Searching r/{'+'.join(subs)} for: \"{args.keyword}\"")
        print(f"  Window: {args.time} | sort: {args.sort} | posts: {args.post_limit}\n")
        try:
            reddit_items = fetch_items(
                keyword=args.keyword,
                subreddits=subs,
                time_filter=args.time,
                sort=args.sort,
                post_limit=args.post_limit,
                comments_per_post=args.comments_per_post,
            )
            for it in reddit_items:
                it["platform"] = "reddit"
            items.extend(reddit_items)
            posts = sum(1 for i in reddit_items if i["type"] == "post")
            print(f"  Pulled {posts} posts and {len(reddit_items) - posts} comments.\n")
        except Exception as e:
            print(f"  Reddit fetch failed: {e}\n  Check REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET in .env\n")

    # ── Twitter ───────────────────────────────────────────────────────────────
    if "twitter" in sources:
        lang = None if args.tweet_lang == "any" else args.tweet_lang
        print(f"  [Twitter] Searching for: \"{args.keyword}\" | limit: {args.tweet_limit}")
        try:
            tweets = twitter_fetch_items(
                keyword=args.keyword,
                limit=args.tweet_limit,
                time_filter=args.time,
                lang=lang or "en",
            )
            for it in tweets:
                it["platform"] = "twitter"
            items.extend(tweets)
            print(f"  Pulled {len(tweets)} tweets.\n")
        except RuntimeError as e:
            print(f"  Twitter fetch failed: {e}\n")
        except Exception as e:
            print(f"  Twitter fetch failed: {e}\n  Run python3 twitter_setup.py first.\n")

    if not items:
        sys.exit("  No items pulled from any source. Check credentials and try again.")

    print(f"  Total items: {len(items)}. Scoring sentiment with Claude...\n")

    # ── Sentiment scoring ─────────────────────────────────────────────────────
    try:
        scored = score_items(
            items, model=args.model, batch_size=args.batch_size, keyword=args.keyword
        )
    except Exception as e:
        sys.exit(f"  Sentiment scoring failed: {e}\n  Check ANTHROPIC_API_KEY in .env")

    # ── Output ────────────────────────────────────────────────────────────────
    print_summary(scored, keyword=args.keyword, top_n=args.top_n)

    csv_path = args.csv or _default_csv_name(args.keyword)
    write_csv(scored, csv_path)
    print(f"\n  Full data written to: {csv_path}\n")


def _default_csv_name(keyword):
    safe = "".join(c if c.isalnum() else "_" for c in keyword).strip("_").lower()
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return f"pulse_{safe}_{stamp}.csv"


if __name__ == "__main__":
    main()
