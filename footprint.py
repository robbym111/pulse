"""
footprint.py — where the audience is, and how each platform's audience differs.

The StatSocial "cross-platform footprint" idea, from the pulse itself: for each
platform, its share of the conversation (posts and distinct people), its mood,
and the themes and names it over-indexes on compared with the pulse as a whole.
That answers "where do we show up, and with what message" per platform.

The index is within-pulse: 100 = the pulse average, shown as a multiple. A
theme at 2.4× on TikTok is talked about 2.4 times as much there, relative to
TikTok's volume, as across all platforms. It's not a population index, and platform volumes depend on the
fetch limits you set, so shares describe this pulse, not the internet.

Engagement numbers aren't comparable across platforms (a YouTube like and a
Reddit upvote are different currencies), so engagement is reported per
platform as a median, never summed across them.
"""

from collections import Counter, defaultdict

from common import PLATFORM_LABELS

MIN_THEME_ITEMS = 3   # a theme needs this many items on a platform to be indexed
TOP_DISTINCTIVE = 3


def _median(xs):
    xs = sorted(xs)
    if not xs:
        return 0
    mid = len(xs) // 2
    return xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2


def _index(count_p, n_p, count_all, n_all):
    if not (n_p and count_all and n_all):
        return 0
    return round(100 * (count_p / n_p) / (count_all / n_all))


def build_footprint(items):
    """Per-platform profile dicts, largest platform first."""
    by_p = defaultdict(list)
    for it in items:
        by_p[it.get("platform") or "other"].append(it)
    n_all = len(items) or 1
    people_all = {(it.get("platform"), it.get("author")) for it in items if it.get("author")}

    theme_all = Counter(t for it in items for t in set(it.get("themes") or []))
    ment_all = Counter(m["name"] for it in items
                       for m in {m["name"]: m for m in it.get("mentions") or []}.values())

    out = []
    for p, its in by_p.items():
        n = len(its)
        scores = [float(it.get("sentiment_score") or 0) for it in its]
        labels = Counter(it.get("sentiment_label", "neutral") for it in its)
        people = {it.get("author") for it in its if it.get("author")}
        themes = Counter(t for it in its for t in set(it.get("themes") or []))
        ments = Counter(m["name"] for it in its
                        for m in {m["name"]: m for m in it.get("mentions") or []}.values())

        distinctive = sorted(
            ((t, c, _index(c, n, theme_all[t], n_all)) for t, c in themes.items()
             if c >= MIN_THEME_ITEMS),
            key=lambda x: (x[2], x[1]), reverse=True)
        out.append({
            "platform": p,
            "items": n,
            "item_share": round(100 * n / n_all, 1),
            "people": len(people),
            "people_share": round(100 * len(people) / (len(people_all) or 1), 1),
            "avg_sentiment": round(sum(scores) / n, 2) if n else 0.0,
            "positive_pct": round(100 * labels.get("positive", 0) / n) if n else 0,
            "negative_pct": round(100 * labels.get("negative", 0) / n) if n else 0,
            "median_engagement": _median([float(it.get("impact") or 0) for it in its]),
            "top_themes": [t for t, _ in themes.most_common(4)],
            "distinctive_themes": [{"theme": t, "items": c, "index": i}
                                   for t, c, i in distinctive[:TOP_DISTINCTIVE] if i > 100],
            "top_mentions": [{"name": m, "items": c, "index": _index(c, n, ment_all[m], n_all)}
                             for m, c in ments.most_common(3) if c >= 2],
        })
    out.sort(key=lambda f: f["items"], reverse=True)
    return out


# --------------------------------------------------------------------------
# Strategist read
# --------------------------------------------------------------------------

READ_PROMPT = """You're advising the marketing team for "{keyword}" on where to show up.
Below is how the conversation splits across platforms in this pulse: each platform's share of
posts and people, its mood, its top themes, and the themes it over-indexes on, as a multiple
of the pulse average (2.4× = talked about 2.4 times as much there as across all platforms).

Return a JSON object:
- "summary": 2-3 sentences: where the conversation is concentrated and the biggest difference
  between platforms (mood, focus, or who's talking).
- "platform_plays": one object per platform listed, {{"platform", "play": one concrete sentence on
  what to post or do there, grounded in its distinctive themes and mood}}.
- "gaps": 0-3 strings: mismatches worth acting on (e.g. a platform with lots of volume but sour
  mood, or a theme that's huge on one platform and absent elsewhere).

Only use the platforms and themes below. Note that shares reflect this pulse's fetch limits,
not total platform size. Return ONLY JSON.

Platforms:
{rows}"""


def footprint_read(footprint, keyword, model):
    if len(footprint) < 2:
        return None  # nothing to compare
    from brief import client, _extract_json_object
    rows = "\n".join(
        f'- {PLATFORM_LABELS.get(f["platform"], f["platform"])}: {f["item_share"]}% of posts, '
        f'{f["people_share"]}% of people, sentiment {f["avg_sentiment"]:+.2f} '
        f'({f["positive_pct"]}% pos / {f["negative_pct"]}% neg) · top themes: '
        f'{", ".join(f["top_themes"]) or "—"} · over-indexes on: '
        + (", ".join(f'{d["theme"]} ({_x(d["index"])})' for d in f["distinctive_themes"]) or "—")
        + (" · names: " + ", ".join(m["name"] for m in f["top_mentions"]) if f["top_mentions"] else "")
        for f in footprint
    )
    print(f"  Footprint read across {len(footprint)} platforms...")
    try:
        msg = client().messages.create(
            model=model, max_tokens=2000,
            messages=[{"role": "user", "content": READ_PROMPT.format(keyword=keyword, rows=rows)}],
        )
        raw = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        return _extract_json_object(raw)
    except Exception as e:
        print(f"  (footprint read failed: {e})")
        return None


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def _x(index):
    """Index 260 -> '2.6×' (times the pulse average)."""
    return f"{index / 100:.1f}×"


def _label(p):
    return PLATFORM_LABELS.get(p, p)


def markdown_section(footprint, read=None):
    if len(footprint) < 2:
        return []  # one platform has nothing to compare against
    L = ["---", "## Cross-Platform Footprint — where the audience is, and how it differs", ""]
    L.append("*Shares are of this pulse (they depend on fetch limits). \"2.6×\" = talked about "
             "2.6 times as much on that platform as across the whole pulse. "
             "Engagement is a per-platform median and isn't comparable across platforms.*")
    L.append("")
    if read and read.get("summary"):
        L.append(read["summary"])
        L.append("")

    L.append("| Platform | Posts | People | Sentiment | Pos / Neg | Median engagement | Over-indexes on |")
    L.append("|---|---|---|---|---|---|---|")
    for f in footprint:
        dist = ", ".join(f'{d["theme"]} ({_x(d["index"])})' for d in f["distinctive_themes"]) or "—"
        L.append(f"| {_label(f['platform'])} | {f['items']} ({f['item_share']}%) | "
                 f"{f['people']} ({f['people_share']}%) | {f['avg_sentiment']:+.2f} | "
                 f"{f['positive_pct']}% / {f['negative_pct']}% | {f['median_engagement']:g} | {dist} |")
    L.append("")

    ment_rows = [f for f in footprint if f["top_mentions"]]
    if ment_rows:
        L.append("**Names each platform brings up most**")
        L.append("")
        for f in ment_rows:
            L.append(f"- **{_label(f['platform'])}:** "
                     + ", ".join(f'{m["name"]} ({m["items"]})' for m in f["top_mentions"]))
        L.append("")

    if read and read.get("platform_plays"):
        L.append("**Platform plays**")
        L.append("")
        for p in read["platform_plays"]:
            L.append(f"- **{p.get('platform', '')}** — {p.get('play', '')}")
        L.append("")
    if read and read.get("gaps"):
        L.append("**Gaps to act on**")
        L.append("")
        L.extend(f"- {g}" for g in read["gaps"])
        L.append("")
    return L
