"""
creator_discovery.py — who is actually driving the conversation about a query.

Audience-first creator ranking (the StatSocial "Discovery" idea): rank the
accounts in a pulse by the engagement they generated, not follower count.
A creator scores for engagement on their own posts plus the replies their
posts pulled in within this pulse. So a 2k-follower TikToker whose video
sparked 40 comments outranks a big account whose post nobody engaged with.

Guardrails, on purpose:
  - Only public posts already collected in this pulse are used. Nothing is
    looked up about an account beyond what it posted here.
  - Handles are never linked across platforms. @x on TikTok and @x on X stay
    separate rows, because the same handle isn't proof it's the same person.
  - Deleted/unknown authors and press outlets are left out (press has its own
    tiered scoring in editorial_source).

Run inside combined_report.py (automatic), or standalone on per-source CSVs
from an earlier run:

    python3 creator_discovery.py pulse_reddit_*.csv pulse_twitter_*.csv \\
        --keyword 'phoebe bridgers'
"""

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict

from common import PLATFORM_LABELS

SKIP_AUTHORS = {"", "[deleted]", "unknown", "@unknown", "automoderator", "@"}
SKIP_PLATFORMS = {"news"}

REPLY_WEIGHT = 2.0  # each captured reply is worth this on top of its own impact

# Pull a parent post id out of a permalink so comments can be credited to the
# account whose post they're replying to.
_PARENT_RES = {
    "reddit": re.compile(r"/comments/([a-z0-9]+)", re.I),
    "tiktok": re.compile(r"/video/(\d+)"),
}

# Stance thresholds on the author's own average sentiment (-1..+1)
CHAMPION_AT = 0.3
CRITIC_AT = -0.2


def _parent_key(it):
    rx = _PARENT_RES.get(it.get("platform"))
    if not rx:
        return None
    m = rx.search(it.get("permalink") or "")
    return (it["platform"], m.group(1)) if m else None


def _stance(avg):
    if avg >= CHAMPION_AT:
        return "champion"
    if avg <= CRITIC_AT:
        return "critic"
    return "mixed"


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


_OFFICIAL_SUFFIX = re.compile(r"(vevo|official|music|records|tv)$")


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _looks_official(author, keyword):
    """True if the handle is basically the artist named in the query (e.g.
    'PhoebeBridgersVEVO' for 'phoebe bridgers "lost boys"'). Heuristic."""
    a = _OFFICIAL_SUFFIX.sub("", _norm(author))
    return len(a) >= 4 and a in _norm(keyword)


def _parent(it, post_author):
    """(account credited for this comment, link to the thing it replied to)."""
    if it.get("platform") == "youtube" and it.get("video_channel"):
        return it["video_channel"], (it.get("permalink") or "").split("&lc=")[0]
    key = _parent_key(it)
    if key and key in post_author:
        return post_author[key]
    return None, ""


def rank_creators(items, keyword=""):
    """
    Group items by (platform, author) and score each account.
    Returns a list of account dicts, highest conversation_score first.

    role "creator" = posted content (or, on YouTube, owns a video whose comments
    are in the pulse). role "voice" = only commented. role "official" = the
    handle looks like the artist in `keyword`. Only creators are pitched as
    partners; voices and official accounts are shown for context.
    """
    # Map each post to its author so replies can be credited back.
    post_author = {}
    for it in items:
        if it.get("type") == "post":
            key = _parent_key(it)
            if key:
                post_author[key] = (it.get("author", ""), it.get("permalink", ""))

    acc = defaultdict(lambda: {
        "posts": 0, "comments": 0, "own_impact": 0.0,
        "replies": 0, "reply_impact": 0.0, "reply_scores": [], "reply_link": "",
        "reply_title": "", "scores": [], "themes": Counter(), "items": [],
    })

    for it in items:
        platform = it.get("platform", "")
        author = (it.get("author") or "").strip()
        if platform in SKIP_PLATFORMS:
            continue
        if author.lower() not in SKIP_AUTHORS:
            a = acc[(platform, author)]
            if it.get("type") == "post":
                a["posts"] += 1
            else:
                a["comments"] += 1
            a["own_impact"] += _num(it.get("impact"))
            a["scores"].append(_num(it.get("sentiment_score")))
            a["themes"].update(it.get("themes") or [])
            a["items"].append(it)

        # Credit this comment to the account whose post/video it's under.
        if it.get("type") != "post":
            parent, link = _parent(it, post_author)
            if parent and parent != author and parent.lower() not in SKIP_AUTHORS:
                p = acc[(platform, parent)]
                p["replies"] += 1
                p["reply_impact"] += _num(it.get("impact"))
                p["reply_scores"].append(_num(it.get("sentiment_score")))
                if not p["items"]:  # channel with no posts of its own here
                    p["themes"].update(it.get("themes") or [])
                    if _num(it.get("impact")) >= p.get("_best_reply", -1):
                        p["_best_reply"] = _num(it.get("impact"))
                        p["reply_link"] = link
                        p["reply_title"] = it.get("post_title", "")

    out = []
    for (platform, author), a in acc.items():
        score = a["own_impact"] + a["reply_impact"] + REPLY_WEIGHT * a["replies"]
        avg = sum(a["scores"]) / len(a["scores"]) if a["scores"] else None
        reply_avg = (sum(a["reply_scores"]) / len(a["reply_scores"])
                     if a["reply_scores"] else None)
        if a["items"]:
            best = max(a["items"], key=lambda x: (_num(x.get("impact")),
                                                 abs(_num(x.get("sentiment_score")))))
            top_link, top_text = best.get("permalink", ""), (best.get("text") or "")[:300]
        else:
            top_link, top_text = a["reply_link"], f"(video) {a['reply_title']}"[:300]
        quoted = [x for x in a["items"] if x.get("quote")]
        quote_item = max(quoted, key=lambda x: _num(x.get("impact"))) if quoted else None
        out.append({
            "platform": platform,
            "author": author,
            "role": ("official" if keyword and _looks_official(author, keyword)
                     else "creator" if a["posts"] or not a["items"] else "voice"),
            "conversation_score": round(score, 1),
            "posts": a["posts"],
            "comments": a["comments"],
            "own_engagement": round(a["own_impact"], 1),
            "replies_sparked": a["replies"],
            "avg_sentiment": round(avg, 2) if avg is not None else None,
            "stance": _stance(avg) if avg is not None else "—",
            "audience_sentiment": round(reply_avg, 2) if reply_avg is not None else None,
            "top_themes": [t for t, _ in a["themes"].most_common(3)],
            "quote": (quote_item or {}).get("quote") or "",
            "top_link": top_link,
            "top_text": top_text,
        })

    out.sort(key=lambda c: (c["conversation_score"], c["posts"] + c["comments"]),
             reverse=True)
    # Drop accounts that generated nothing measurable and said only one thing.
    return [c for c in out
            if c["conversation_score"] > 0 or c["posts"] + c["comments"] >= 2]


# --------------------------------------------------------------------------
# Strategist read — which creators to approach, which to keep an eye on
# --------------------------------------------------------------------------

READ_PROMPT = """You're advising the marketing team for "{keyword}" on creator partnerships.
Below are the creators in this pulse (accounts that posted content or made the videos being
discussed), ranked by the engagement they generated, not follower count.

Field meanings: "score" = engagement generated. "own sentiment" = how positive their own post
was (-1..+1), not engagement. "audience sentiment" = how positive the replies to them were.

Return a JSON object:
- "summary": 2-3 sentences on who is actually driving this conversation (types of accounts,
  which platforms, whether the loudest creators are fans, critics, reviewers, or meme accounts).
- "partner_shortlist": 0-6 objects {{"account", "platform", "why": one sentence grounded in what
  they made and how their audience reacted, "approach": one concrete ask (e.g. early access,
  a stitch/duet prompt, a listening-party invite)}}. Favor genuine champions whose content pulled
  real replies over accounts that are merely prolific. Return an empty list if no one fits.
- "watch_list": 0-4 objects {{"account", "platform", "why": the criticism or risk their content is
  driving, "how_to_react": one sentence}}. Only creators whose critical content is getting traction.

Rules:
- Use ONLY accounts listed below, exactly as written.
- Judge them only on the content and engagement shown here. Never guess at anyone's age,
  identity, location, or personal life.
- Never cite personal disclosures (health, mental health, trauma, grief, sexuality, religion,
  politics, war or crisis) as a reason to approach someone, even if their post mentions them.
Return ONLY JSON."""


def _fmt(v):
    return f"{v:+.2f}" if v is not None else "n/a"


def creator_read(creators, keyword, model, max_creators=25):
    """One synthesis call over the top creators (never commenters). Returns a dict or None."""
    pool = [c for c in creators if c["role"] == "creator"][:max_creators]
    if not pool:
        print("  Creator read skipped: no content creators in this pulse, only commenters.")
        return None
    from brief import client, _extract_json_object

    rows = "\n".join(
        f'- {c["author"]} ({PLATFORM_LABELS.get(c["platform"], c["platform"])}) · '
        f'score {c["conversation_score"]:g} · {c["posts"]} posts · '
        f'{c["replies_sparked"]} replies sparked · own sentiment {_fmt(c["avg_sentiment"])} · '
        f'audience sentiment {_fmt(c["audience_sentiment"])} · '
        f'themes: {", ".join(c["top_themes"]) or "—"}\n  content: "{c["top_text"][:250]}"'
        for c in pool
    )
    print(f"  Creator read over top {len(pool)} creators...")
    try:
        msg = client().messages.create(
            model=model,
            max_tokens=2500,
            messages=[{"role": "user",
                       "content": READ_PROMPT.format(keyword=keyword) + "\n\nCreators:\n" + rows}],
        )
        raw = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        return _extract_json_object(raw)
    except Exception as e:
        print(f"  (creator read failed: {e})")
        return None


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def _cell(s):
    return str(s).replace("|", "/").replace("\n", " ")


def _acct(c):
    return f"[{_cell(c['author'])}]({c['top_link']})" if c["top_link"] else _cell(c["author"])


def _stance_cell(c):
    return c["stance"] if c["avg_sentiment"] is None else f"{c['stance']} ({c['avg_sentiment']:+.2f})"


def markdown_section(creators, read=None, top_n=15, top_voices=5):
    """Markdown block for the combined brief."""
    if not creators:
        return []
    made = [c for c in creators if c["role"] in ("creator", "official")]
    voices = [c for c in creators if c["role"] == "voice"]

    L = ["---", "## Creator Discovery — who's driving the conversation", ""]
    L.append("*Ranked by the engagement each account generated in this pulse (its own posts "
             "plus the replies they drew), not by follower count.*")
    L.append("")
    if read and read.get("summary"):
        L.append(read["summary"])
        L.append("")

    if made:
        L.append("**Creators** (posted content, or made the video being discussed)")
        L.append("")
        L.append("| # | Account | Platform | Score | Posts | Replies drawn | Audience sentiment | Own stance | Themes |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for i, c in enumerate(made[:top_n], 1):
            L.append(
                f"| {i} | {_acct(c)}{' *(official)*' if c['role'] == 'official' else ''} | {PLATFORM_LABELS.get(c['platform'], c['platform'])} | "
                f"{c['conversation_score']:g} | {c['posts']} | {c['replies_sparked']} | "
                f"{_fmt(c['audience_sentiment'])} | {_stance_cell(c)} | "
                f"{_cell(', '.join(c['top_themes']) or '—')} |"
            )
        L.append("")
    else:
        L.append("*No content creators in this pulse, only commenters. Include X or TikTok "
                 "for creator rankings.*")
        L.append("")

    if read and read.get("partner_shortlist"):
        L.append("**Partner shortlist**")
        L.append("")
        for p in read["partner_shortlist"]:
            L.append(f"- **{p.get('account', '')}** ({p.get('platform', '')}) — {p.get('why', '')}")
            if p.get("approach"):
                L.append(f"  - → {p['approach']}")
        L.append("")

    if read and read.get("watch_list"):
        L.append("**Watch list**")
        L.append("")
        for w in read["watch_list"]:
            L.append(f"- **{w.get('account', '')}** ({w.get('platform', '')}) — {w.get('why', '')}")
            if w.get("how_to_react"):
                L.append(f"  - → {w['how_to_react']}")
        L.append("")

    if voices and top_voices:
        L.append("**Loudest voices** (most-engaged comments; context, not partner picks)")
        L.append("")
        for c in voices[:top_voices]:
            said = c["quote"] or c["top_text"][:140]
            L.append(f"- \"{_cell(said)}\" — *{c['author']}*, "
                     f"{PLATFORM_LABELS.get(c['platform'], c['platform'])} · "
                     f"engagement {c['conversation_score']:g} · {_stance_cell(c)}")
        L.append("")
    return L


CSV_COLS = [
    "rank", "platform", "author", "role", "conversation_score", "posts", "comments",
    "own_engagement", "replies_sparked", "avg_sentiment", "stance",
    "audience_sentiment", "top_themes", "quote", "top_link", "top_text",
]


def write_creators_csv(creators, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
        w.writeheader()
        for i, c in enumerate(creators, 1):
            row = dict(c, rank=i, top_themes="; ".join(c["top_themes"]))
            if row["audience_sentiment"] is None:
                row["audience_sentiment"] = ""
            w.writerow(row)


# --------------------------------------------------------------------------
# Standalone: re-rank creators from per-source CSVs of an earlier run
# --------------------------------------------------------------------------

def load_items_from_csv(path):
    """Read a per-source pulse CSV (output.write_csv format) back into items."""
    items = []
    with open(path, newline="", encoding="utf-8") as f:
        first = f.readline()
        if not first.startswith("#"):  # chat CSVs start with a comment row
            f.seek(0)
        for row in csv.DictReader(f):
            row["themes"] = [t.strip() for t in (row.get("themes") or "").split(";") if t.strip()]
            row["impact"] = _num(row.get("impact"))
            row["sentiment_score"] = _num(row.get("sentiment_score"))
            items.append(row)
    return items


def main():
    p = argparse.ArgumentParser(
        description="Rank the accounts driving a pulse from existing per-source CSVs.")
    p.add_argument("csvs", nargs="+", help="pulse_<source>_*.csv files from a previous run")
    p.add_argument("--keyword", required=True, help="the query the pulse was run for")
    p.add_argument("--top", type=int, default=15, help="rows to show in the brief table")
    p.add_argument("--brief-model", default="claude-opus-4-8")
    p.add_argument("--no-read", action="store_true",
                   help="skip the Claude partner/watch-list read (no API cost)")
    p.add_argument("--out", default=None, help="output prefix (default: pulse_creators_<keyword>)")
    args = p.parse_args()

    items = []
    for path in args.csvs:
        got = load_items_from_csv(path)
        if got and ("type" not in got[0] or "impact" not in got[0]):
            print(f"  ! skipping {path}: no type/impact columns. Use the per-source "
                  f"pulse_<source>_*.csv files, not the chat CSV.")
            continue
        items.extend(got)
    if not items:
        sys.exit("  No rows found in those CSVs.")

    creators = rank_creators(items, args.keyword)
    print(f"  {len(items)} items → {len(creators)} ranked accounts")
    read = None if args.no_read else creator_read(creators, args.keyword, args.brief_model)

    from query_utils import safe_filename
    prefix = args.out or f"pulse_creators_{safe_filename(args.keyword)}"
    write_creators_csv(creators, prefix + ".csv")
    with open(prefix + ".md", "w", encoding="utf-8") as f:
        f.write(f"# Creator Discovery — {args.keyword}\n\n")
        f.write("\n".join(markdown_section(creators, read, top_n=args.top)))
    print(f"  ✓ {prefix}.md\n  ✓ {prefix}.csv")


if __name__ == "__main__":
    main()
