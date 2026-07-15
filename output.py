"""
output.py — terminal summary + CSV export.

Knows all five platforms via common.PLATFORM_LABELS. Top-impact view includes
every source (YouTube/TikTok comments can be high-impact too, unlike before).
"""

import csv
from collections import Counter
from datetime import datetime, timezone

from common import PLATFORM_LABELS


def _fmt_pct(n, total):
    return f"{100 * n / total:.0f}%" if total else "0%"


def _bar(frac, width=24):
    filled = round(frac * width)
    return "█" * filled + "·" * (width - filled)


def _platform_counts(items):
    c = Counter(it.get("platform", "reddit") for it in items)
    parts = [f"{PLATFORM_LABELS.get(p, p)}: {n}" for p, n in c.most_common()]
    return "  |  ".join(parts)


def _venue(it):
    return it.get("venue") or f"r/{it.get('subreddit', '')}"


def print_summary(items, keyword, top_n=8):
    total = len(items)
    labels = Counter(it.get("sentiment_label", "neutral") for it in items)

    scores = [it.get("sentiment_score", 0.0) for it in items]
    avg = sum(scores) / total if total else 0.0

    weight_sum = sum(it.get("impact", 0) for it in items) or 1
    weighted = (
        sum(it.get("sentiment_score", 0.0) * it.get("impact", 0) for it in items)
        / weight_sum
    )

    print("=" * 64)
    print(f'  SENTIMENT PULSE — "{keyword}"')
    print("=" * 64)
    print(f"  Items analyzed: {total}  ({_platform_counts(items)})")
    print(f"  Average sentiment:         {avg:+.2f}  (-1 to +1)")
    print(f"  Impact-weighted sentiment: {weighted:+.2f}  (loudest voices)")
    print()

    print("  Sentiment split")
    for lbl in ("positive", "mixed", "neutral", "negative"):
        n = labels.get(lbl, 0)
        frac = n / total if total else 0
        print(f"    {lbl:<9} {_bar(frac)} {n:>4}  {_fmt_pct(n, total)}")
    print()

    # Themes
    theme_counter = Counter()
    for it in items:
        for t in it.get("themes", []):
            theme_counter[t] += 1
    if theme_counter:
        print("  Top themes")
        for theme, n in theme_counter.most_common(10):
            print(f"    {n:>4}×  {theme}")
        print()

    # Top impact items — all sources, not just posts/tweets
    top_items = sorted(items, key=lambda x: x.get("impact", 0), reverse=True)
    print(f"  Top {min(top_n, len(top_items))} highest-impact items")
    for it in top_items[:top_n]:
        plat = PLATFORM_LABELS.get(it.get("platform", "reddit"), "?")[:2].upper()
        lean = it.get("sentiment_label", "?")
        print(
            f"    [{plat}][{lean:^8}] {it.get('impact', 0):>7.0f} impact"
            f"  ·  {it.get('score', 0)}↑  {it.get('num_comments', 0)}💬"
        )
        print(f"       {it.get('post_title', '')[:80]}")
        print(f"       {it.get('permalink', '')}")
    print()

    # Sharpest takes
    ranked = [it for it in items if abs(it.get("sentiment_score", 0)) > 0.3]
    ranked.sort(key=lambda x: x.get("sentiment_score", 0))
    if ranked:
        print("  Sharpest negative take")
        neg = ranked[0]
        print(f"    ({neg.get('sentiment_score', 0):+.2f}) {neg['text'][:160].strip()}")
        print(f"    {neg.get('permalink', '')}")
        print()
        print("  Strongest positive take")
        pos = ranked[-1]
        print(f"    ({pos.get('sentiment_score', 0):+.2f}) {pos['text'][:160].strip()}")
        print(f"    {pos.get('permalink', '')}")
    print("=" * 64)


def write_chat_csv(items, keyword, stamp, path, max_rows=2000):
    """
    Chat-optimised export for pasting into Claude Chat.

    Columns are slim but include Claude's per-item quote + takeaway so
    Claude Chat can query the pre-digested insights without re-reading
    raw text. Sorted by impact desc. max_rows=None means no cap.
    """
    cols = [
        "platform", "venue", "author", "post_title",
        "sentiment_label", "sentiment_score", "themes",
        "quote", "takeaway", "text", "permalink",
    ]

    sorted_items = sorted(items, key=lambda x: x.get("impact", 0), reverse=True)
    capped = sorted_items[:max_rows] if max_rows else sorted_items

    scores = [it.get("sentiment_score", 0.0) for it in items]
    avg = sum(scores) / len(scores) if scores else 0.0

    platforms = sorted({PLATFORM_LABELS.get(it.get("platform", ""), it.get("platform", ""))
                        for it in items if it.get("platform")})
    platforms_str = ", ".join(platforms) if platforms else "multiple platforms"

    header = (f"# Pulse export for {keyword} — {stamp} — "
              f"{len(capped)} items across {platforms_str} — "
              f"average sentiment {avg:+.2f}")

    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(header + "\n")
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for it in capped:
            row = dict(it)
            row["themes"] = "; ".join(it.get("themes", []))
            row["quote"] = it.get("quote") or ""
            row["takeaway"] = it.get("takeaway") or ""
            w.writerow(row)


def write_csv(items, path):
    cols = [
        "platform", "type", "subreddit", "venue", "post_title", "author",
        "created_iso", "score", "num_comments", "impact",
        "sentiment_label", "sentiment_score", "themes",
        "like_count", "retweet_count", "reply_count", "quote_count",
        "view_count", "share_count",
        "permalink", "text",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for it in items:
            row = dict(it)
            row["created_iso"] = datetime.fromtimestamp(
                it.get("created_utc", 0), tz=timezone.utc
            ).isoformat()
            row["themes"] = "; ".join(it.get("themes", []))
            w.writerow(row)
