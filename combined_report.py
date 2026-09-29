"""
combined_report.py — runs all three sources and merges into one cross-platform brief.

Usage:
    python3 combined_report.py "Lost Boys" \
        --subreddits indieheads,popheads,phoebebridgers,fantanoforever \
        --time day

Produces:
    pulse_combined_<keyword>_<timestamp>_brief.md  — the unified report
    pulse_reddit_..., pulse_youtube_..., pulse_editorial_...  — individual CSVs
"""

import argparse
import sys
from datetime import datetime, timezone

from claude_sentiment import score_items
from brief import synthesize_brief
from output import write_csv, write_chat_csv
from query_utils import for_reddit, for_youtube, for_editorial, safe_filename, display_query


def parse_args():
    p = argparse.ArgumentParser(
        description="Cross-platform pulse: Reddit + YouTube + editorial in one brief.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("keyword")
    p.add_argument("--subreddits", default="indieheads,popheads",
                   help="Subreddits for the Reddit pulse.")
    p.add_argument("--time", default="week",
                   choices=["hour", "day", "week", "month", "year", "all"])
    p.add_argument("--sort", default="new")
    p.add_argument("--post-limit", type=int, default=25,
                   help="Max posts/videos per Reddit subreddit and YouTube.")
    p.add_argument("--comments-per-post", type=int, default=30,
                   help="Top comments to pull per post/video.")
    p.add_argument("--tweet-limit", type=int, default=200,
                   help="Max tweets to pull from Twitter/X.")
    p.add_argument("--editorial-days", type=int, default=30)
    p.add_argument("--editorial-min-words", type=int, default=200)
    p.add_argument("--editorial-articles", type=int, default=25,
                   help="Max editorial articles to pull.")
    p.add_argument("--model", default="claude-haiku-4-5-20251001")
    p.add_argument("--brief-model", default="claude-opus-4-8")
    p.add_argument("--batch-size", type=int, default=15)
    p.add_argument("--skip-reddit", action="store_true")
    p.add_argument("--skip-youtube", action="store_true")
    p.add_argument("--skip-editorial", action="store_true")
    p.add_argument("--skip-twitter", action="store_true")
    p.add_argument("--skip-tiktok", action="store_true")
    p.add_argument("--tiktok-sounds", default="",
                   help="comma-separated TikTok sound links or ids to always pull")
    p.add_argument("--tiktok-max-sounds", type=int, default=3,
                   help="extra sounds to find automatically from the artist (0 = off)")
    p.add_argument("--tiktok-sound-videos", type=int, default=20,
                   help="videos to pull per sound")
    p.add_argument("--tiktok-artist-videos", type=int, default=10,
                   help="recent videos to pull from the artist's own account (0 = off)")
    p.add_argument("--skip-footprint", action="store_true",
                   help="skip the Cross-Platform Footprint (one brief-model call)")
    p.add_argument("--db", default="pulse_history.db",
                   help="SQLite history to append each run to")
    p.add_argument("--no-db", action="store_true", help="don't append to the history database")
    p.add_argument("--skip-affinity", action="store_true",
                   help="skip the Audience Affinity Map (one brief-model call)")
    p.add_argument("--skip-creators", action="store_true",
                   help="skip Creator Discovery (ranking + one brief-model call)")
    p.add_argument("--creators", type=int, default=15,
                   help="accounts to show in the Creator Discovery table")
    p.add_argument("--tiktok-videos", type=int, default=20,
                   help="Max TikTok videos to pull.")
    p.add_argument("--tiktok-comments", type=int, default=30,
                   help="Comments per TikTok video.")
    p.add_argument("--chat-rows", type=int, default=2000,
                   help="Max rows in the chat-optimised CSV (0 = no cap).")
    p.add_argument("--since",
                   help="Only include items after this date/time. "
                        "Accepts: 'YYYY-MM-DD', 'YYYY-MM-DD HH:MM', or 'NdNh' (e.g. '2d12h'). "
                        "Overrides --time for sources that support a cutoff.")
    return p.parse_args()


def _safe_name(keyword):
    safe = safe_filename(keyword)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return safe, stamp


def _parse_since(since_str):
    """Parse --since into an aware UTC datetime, or raise ValueError."""
    import re
    s = since_str.strip()
    # Relative shorthand: e.g. "2d", "12h", "2d12h"
    m = re.fullmatch(r"(?:(\d+)d)?(?:(\d+)h)?", s, re.I)
    if m and (m.group(1) or m.group(2)):
        from datetime import timedelta
        days = int(m.group(1) or 0)
        hours = int(m.group(2) or 0)
        return datetime.now(tz=timezone.utc) - timedelta(days=days, hours=hours)
    # Absolute: "YYYY-MM-DD" or "YYYY-MM-DD HH:MM" (treated as local time)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            naive = datetime.strptime(s, fmt)
            return naive.astimezone(timezone.utc)
        except ValueError:
            continue
    raise ValueError(
        f"--since {since_str!r} not recognised. "
        "Use 'YYYY-MM-DD', 'YYYY-MM-DD HH:MM', or a relative offset like '2d' or '12h' or '2d12h'."
    )


def _fetch_and_score(source_name, platform, fetch_fn, fetch_kwargs, keyword, model, batch_size):
    print(f"\n{'='*60}")
    print(f"  PULLING: {source_name.upper()}")
    print(f"{'='*60}")
    try:
        items = fetch_fn(**fetch_kwargs)
    except Exception as e:
        print(f"  ✗ {source_name} fetch failed: {e}")
        return []
    if not items:
        print(f"  ✗ No items from {source_name}.")
        return []
    # Guarantee every item carries its platform tag (sources may or may not set it)
    for it in items:
        it.setdefault("platform", platform)
    posts = sum(1 for i in items if i["type"] in ("post", "review"))
    comments = len(items) - posts
    print(f"  Pulled {posts} top-level + {comments} comments. Scoring...\n")
    try:
        return score_items(items, model=model, batch_size=batch_size, keyword=keyword)
    except Exception as e:
        print(f"  ✗ Scoring failed for {source_name}: {e}")
        return []


def write_combined_brief(reddit, youtube, editorial, briefs, keyword, path, twitter=None, tiktok=None,
                         creator_lines=None, extra_lines=None, affinity_lines=None,
                         footprint_lines=None):
    stamp = datetime.now().strftime("%B %d, %Y at %H:%M")
    twitter = twitter or []
    tiktok = tiktok or []
    all_items = reddit + youtube + twitter + tiktok + editorial
    total = len(all_items)
    scores = [it.get("sentiment_score", 0.0) for it in all_items]
    avg = sum(scores) / total if total else 0.0

    from collections import Counter
    labels = Counter(it.get("sentiment_label", "neutral") for it in all_items)

    def pct(lbl):
        return f"{100 * labels.get(lbl, 0) / total:.0f}%" if total else "0%"

    L = []
    L.append(f"# Cross-Platform Pulse Brief — {keyword}")
    L.append("")

    # Pull the Reddit brief headline as the top-line since it's richest
    top_brief = briefs.get("reddit") or briefs.get("youtube") or briefs.get("editorial")
    if top_brief and top_brief.get("headline"):
        L.append(f"> **{top_brief['headline']}**")
        L.append("")

    L.append(f"*Generated {stamp} · {total} items across Reddit, YouTube, Twitter/X, TikTok, and music press · "
             f"avg sentiment {avg:+.2f} (−1 to +1)*")
    L.append("")

    # Cross-platform snapshot table
    L.append("## At a glance — by platform")
    L.append("")
    L.append("| Platform | Items | Avg sentiment | Positive | Negative |")
    L.append("|---|---|---|---|---|")
    for name, items in [("Reddit", reddit), ("YouTube", youtube), ("Twitter/X", twitter), ("TikTok", tiktok), ("Editorial", editorial)]:
        if not items:
            L.append(f"| {name} | — | — | — | — |")
            continue
        n = len(items)
        sc = [it.get("sentiment_score", 0.0) for it in items]
        av = sum(sc) / n
        lb = Counter(it.get("sentiment_label", "neutral") for it in items)
        pos_pct = f"{100 * lb.get('positive', 0) / n:.0f}%"
        neg_pct = f"{100 * lb.get('negative', 0) / n:.0f}%"
        L.append(f"| {name} | {n} | {av:+.2f} | {pos_pct} | {neg_pct} |")
    L.append("")

    # Overall sentiment split
    L.append("**Overall sentiment**")
    L.append("")
    L.append("| | |")
    L.append("|---|---|")
    for lbl in ("positive", "mixed", "neutral", "negative"):
        n = labels.get(lbl, 0)
        L.append(f"| {lbl.capitalize()} | {pct(lbl)} ({n}) |")
    L.append("")

    # Per-source sections
    source_order = [
        ("reddit",    "Reddit — Fan Discourse",     reddit),
        ("youtube",   "YouTube — Video Comments",   youtube),
        ("twitter",   "Twitter/X — Hot Takes",      twitter),
        ("tiktok",    "TikTok — Video Comments",    tiktok),
        ("editorial", "Editorial — Music Press",    editorial),
    ]
    for key, title, items in source_order:
        brief = briefs.get(key)
        if not items or not brief:
            continue

        L.append(f"---")
        L.append(f"## {title}")
        L.append("")

        if brief.get("exec_summary"):
            for bullet in brief["exec_summary"]:
                L.append(f"- {bullet}")
            L.append("")

        if brief.get("narrative"):
            L.append(brief["narrative"])
            L.append("")

        if brief.get("whats_exciting"):
            L.append(f"**What's resonating**")
            L.append("")
            for h in brief["whats_exciting"]:
                hook = h.get("hook", "")
                ev = h.get("evidence", "")
                line = f"- **{hook}**"
                if ev:
                    line += f" — *\"{ev}\"*"
                L.append(line)
            L.append("")

        if brief.get("creative_ideas"):
            L.append(f"**Ideas from this platform**")
            L.append("")
            for idea in brief["creative_ideas"]:
                L.append(f"- {idea}")
            L.append("")

        if brief.get("watch_outs"):
            L.append(f"**Watch-outs**")
            L.append("")
            for w in brief["watch_outs"]:
                concern = w.get("concern", "")
                ev = w.get("evidence", "")
                react = w.get("how_to_react", "")
                L.append(f"- **{concern}**")
                if ev:
                    L.append(f"  - *\"{ev}\"*")
                if react:
                    L.append(f"  - → {react}")
            L.append("")

        # Top quotes from this source
        quotes = sorted(
            [it for it in items if it.get("quote")],
            key=lambda x: abs(x.get("sentiment_score", 0)), reverse=True
        )
        if quotes:
            L.append(f"**Quotes**")
            L.append("")
            seen = set()
            shown = 0
            for it in quotes:
                q = (it.get("quote") or "").strip()
                if q in seen or shown >= 5:
                    continue
                seen.add(q)
                from output import _venue
                venue = _venue(it)
                link = it.get("permalink", "")
                author = it.get("author", "")
                label = f"[{venue}]({link})" if link else venue
                L.append(f"- \"{q}\" — *{author}*, {label}")
                shown += 1
            L.append("")

    # Cross-platform creative synthesis
    all_ideas = []
    for key, _, _ in source_order:
        brief = briefs.get(key)
        if brief and brief.get("creative_ideas"):
            all_ideas.extend(brief["creative_ideas"])

    if extra_lines:
        L.extend(extra_lines)

    if footprint_lines:
        L.extend(footprint_lines)

    if creator_lines:
        L.extend(creator_lines)

    if affinity_lines:
        L.extend(affinity_lines)

    if all_ideas:
        L.append("---")
        L.append("## Master ideas list — across all platforms")
        L.append("")
        for idea in all_ideas:
            L.append(f"- {idea}")
        L.append("")

    L.append("---")
    L.append("*Sources: Reddit public RSS · YouTube Data API · music press RSS. "
             "Sentiment + synthesis by Claude.*")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def _tiktok_sound_lines(items):
    if not items:
        return None
    try:
        from tiktok_source import sound_markdown
    except ImportError:
        return None
    return sound_markdown(items) or None


def main():
    args = parse_args()
    safe, stamp = _safe_name(args.keyword)
    label = display_query(args.keyword)

    since_cutoff = None
    if args.since:
        try:
            since_cutoff = _parse_since(args.since)
            print(f"\n  Since: {since_cutoff.strftime('%Y-%m-%d %H:%M UTC')}")
        except ValueError as e:
            sys.exit(f"  Error: {e}")

    print(f"\n  Search query: {label}")

    results = {}
    briefs = {}

    # --- REDDIT ---
    if not args.skip_reddit:
        try:
            from reddit_source import fetch_items as reddit_fetch
        except ImportError as e:
            print(f"  Reddit skipped — module missing: {e}")
            reddit_fetch = None
        if reddit_fetch:
            subs = [s.strip() for s in args.subreddits.split(",") if s.strip()]
            scored = _fetch_and_score(
                "Reddit", "reddit", reddit_fetch,
                dict(keyword=for_reddit(args.keyword), subreddits=subs, time_filter=args.time,
                     sort=args.sort, post_limit=args.post_limit,
                     comments_per_post=args.comments_per_post),
                args.keyword, args.model, args.batch_size,
            )
            if scored:
                results["reddit"] = scored
                csv_path = f"pulse_reddit_{safe}_{stamp}.csv"
                write_csv(scored, csv_path)
                print(f"  Reddit CSV: {csv_path}")
                brief = synthesize_brief(scored, keyword=args.keyword,
                                         model=args.brief_model, source="reddit")
                if brief:
                    briefs["reddit"] = brief

    # --- YOUTUBE ---
    if not args.skip_youtube:
        try:
            from youtube_source import fetch_items as yt_fetch
        except ImportError as e:
            print(f"  YouTube skipped — module missing: {e}")
            yt_fetch = None
        if yt_fetch:
            scored = _fetch_and_score(
                "YouTube", "youtube", yt_fetch,
                dict(keyword=for_youtube(args.keyword), video_limit=args.post_limit,
                     comments_per_video=args.comments_per_post, raw_query=args.keyword),
                args.keyword, args.model, args.batch_size,
            )
            if scored:
                results["youtube"] = scored
                csv_path = f"pulse_youtube_{safe}_{stamp}.csv"
                write_csv(scored, csv_path)
                print(f"  YouTube CSV: {csv_path}")
                brief = synthesize_brief(scored, keyword=args.keyword,
                                         model=args.brief_model, source="youtube")
                if brief:
                    briefs["youtube"] = brief

    # --- EDITORIAL ---
    if not args.skip_editorial:
        try:
            from editorial_source import fetch_items as ed_fetch
        except ImportError as e:
            print(f"  Editorial skipped — module missing: {e}")
            ed_fetch = None
        if ed_fetch:
            scored = _fetch_and_score(
                "Editorial", "news", ed_fetch,
                dict(keyword=for_editorial(args.keyword), max_articles=args.editorial_articles,
                     min_words=args.editorial_min_words,
                     recent_days=args.editorial_days),
                args.keyword, args.model, args.batch_size,
            )
            if scored:
                results["editorial"] = scored
                csv_path = f"pulse_editorial_{safe}_{stamp}.csv"
                write_csv(scored, csv_path)
                print(f"  Editorial CSV: {csv_path}")
                brief = synthesize_brief(scored, keyword=args.keyword,
                                         model=args.brief_model, source="editorial")
                if brief:
                    briefs["editorial"] = brief

    # --- TWITTER ---
    if not args.skip_twitter:
        try:
            from twitter_source import fetch_items as tw_fetch
        except ImportError as e:
            print(f"  Twitter skipped — module missing: {e}")
            tw_fetch = None
        if tw_fetch:
            tw_kwargs = dict(keyword=args.keyword, limit=args.tweet_limit, time_filter=args.time)
            if since_cutoff:
                tw_kwargs["since"] = since_cutoff
            scored = _fetch_and_score(
                "Twitter/X", "twitter", tw_fetch,
                tw_kwargs,
                args.keyword, args.model, args.batch_size,
            )
            if scored:
                results["twitter"] = scored
                csv_path = f"pulse_twitter_{safe}_{stamp}.csv"
                write_csv(scored, csv_path)
                print(f"  Twitter CSV: {csv_path}")
                brief = synthesize_brief(scored, keyword=args.keyword,
                                         model=args.brief_model, source="twitter")
                if brief:
                    briefs["twitter"] = brief

    # --- TIKTOK ---
    if not args.skip_tiktok:
        try:
            from tiktok_source import fetch_items as tiktok_fetch
            tt_kwargs = dict(keyword=args.keyword, video_limit=args.tiktok_videos,
                             comments_per_video=args.tiktok_comments, time_filter=args.time,
                             sounds=[x for x in args.tiktok_sounds.split(",") if x.strip()],
                             max_sounds=args.tiktok_max_sounds,
                             sound_videos=args.tiktok_sound_videos,
                             artist_videos=args.tiktok_artist_videos)
            if since_cutoff:
                tt_kwargs["since"] = since_cutoff
            scored = _fetch_and_score(
                "TikTok", "tiktok", tiktok_fetch,
                tt_kwargs,
                args.keyword, args.model, args.batch_size,
            )
            if scored:
                results["tiktok"] = scored
                csv_path = f"pulse_tiktok_{safe}_{stamp}.csv"
                write_csv(scored, csv_path)
                print(f"  TikTok CSV: {csv_path}")
                brief = synthesize_brief(scored, keyword=args.keyword,
                                         model=args.brief_model, source="tiktok")
                if brief:
                    briefs["tiktok"] = brief
        except ImportError:
            print("  TikTok skipped — run: pip install TikTokApi playwright && playwright install chromium")
        except RuntimeError as e:
            print(f"  TikTok skipped — {e}")

    if not results:
        sys.exit("\n  No data from any source. Check your keywords and credentials.")

    all_items = (
        results.get("reddit", [])
        + results.get("youtube", [])
        + results.get("twitter", [])
        + results.get("tiktok", [])
        + results.get("editorial", [])
    )

    reads = {}

    # --- CROSS-PLATFORM FOOTPRINT ---
    footprint, footprint_lines = [], None
    if not args.skip_footprint:
        from footprint import build_footprint, footprint_read, markdown_section as footprint_md
        footprint = build_footprint(all_items)
        reads["footprint"] = footprint_read(footprint, args.keyword, args.brief_model)
        footprint_lines = footprint_md(footprint, reads["footprint"])

    # --- CREATOR DISCOVERY ---
    creators, creator_lines = [], None
    if not args.skip_creators:
        from creator_discovery import rank_creators, creator_read, markdown_section, write_creators_csv
        creators = rank_creators(all_items, args.keyword)
        if creators:
            creators_path = f"pulse_creators_{safe}_{stamp}.csv"
            write_creators_csv(creators, creators_path)
            print(f"\n  Creator Discovery: {len(creators)} accounts ranked → {creators_path}")
            reads["creators"] = creator_read(creators, args.keyword, args.brief_model)
            creator_lines = markdown_section(creators, reads["creators"], top_n=args.creators)

    # --- AUDIENCE AFFINITY MAP ---
    entities, affinity_lines = [], None
    if not args.skip_affinity:
        from affinity_map import build_affinities, affinity_read, markdown_section as affinity_md, \
            write_affinity_csv
        entities = build_affinities(all_items, args.keyword)
        if entities:
            affinity_path = f"pulse_affinity_{safe}_{stamp}.csv"
            write_affinity_csv(entities, affinity_path)
            print(f"\n  Affinity Map: {len(entities)} co-mentioned entities → {affinity_path}")
            reads["affinity"] = affinity_read(entities, args.keyword, args.brief_model)
            affinity_lines = affinity_md(entities, reads["affinity"])

    # --- COMBINED BRIEF ---
    md_path = f"pulse_combined_{safe}_{stamp}_brief.md"
    print(f"\n  Writing combined brief...")
    write_combined_brief(
        reddit=results.get("reddit", []),
        youtube=results.get("youtube", []),
        twitter=results.get("twitter", []),
        tiktok=results.get("tiktok", []),
        editorial=results.get("editorial", []),
        briefs=briefs,
        keyword=args.keyword,
        path=md_path,
        creator_lines=creator_lines,
        affinity_lines=affinity_lines,
        footprint_lines=footprint_lines,
        extra_lines=_tiktok_sound_lines(results.get("tiktok", [])),
    )
    print(f"\n  ✓ Combined brief: {md_path}")

    chat_path = f"pulse_chat_{safe}_{stamp}.csv"
    max_rows = args.chat_rows if args.chat_rows > 0 else None
    write_chat_csv(all_items, keyword=args.keyword, stamp=stamp, path=chat_path,
                   max_rows=max_rows)
    print(f"  ✓ Chat CSV:       {chat_path}  ({len(all_items)} items)")

    # --- STRUCTURED EXPORT + HISTORY ---
    from export import build_run, write_json, append_history
    run = build_run(args.keyword, stamp, since_cutoff, all_items, briefs=briefs,
                    creators=creators, affinities=entities, footprint=footprint, reads=reads)
    json_path = f"pulse_{safe}_{stamp}.json"
    write_json(run, json_path)
    print(f"  ✓ JSON export:    {json_path}")
    if not args.no_db:
        try:
            append_history(run, args.db, json_path)
            print(f"  ✓ History:        {args.db}  (python3 history.py trend '{args.keyword}')\n")
        except Exception as e:
            print(f"  ✗ History append failed: {e}\n")


if __name__ == "__main__":
    main()
