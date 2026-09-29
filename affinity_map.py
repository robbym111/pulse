"""
affinity_map.py — what else the audience talks about alongside the artist.

The StatSocial "behavioral taxonomy" idea, done in aggregate from what people
actually wrote in this pulse: which other artists, brands, films/shows,
places and events come up next to the query, how often, on which platforms,
and in what mood. That's the raw material for tour pairings, brand partners,
syncs, and how fans position the artist against their peers.

The names come from the per-item scoring pass (claude_sentiment's "mentions"),
so there are no extra calls per item. Only one strategist read on top.

Guardrails, on purpose:
  - Only public entities are counted (artists, brands, shows, places...).
    Never private people, never usernames.
  - Counts are aggregate. We report how many distinct authors mention an
    entity, never who they are, and nothing is looked up beyond this pulse.
  - It's co-mention, not affinity in the StatSocial sense: there is no
    population baseline, so "mentioned a lot" can mean loved, compared,
    or dunked on. The mood column and the read say which.

Standalone on per-source CSVs from an earlier run (older CSVs have no
mentions column, so they're extracted in one cheap batched pass):

    python3 affinity_map.py pulse_reddit_*.csv pulse_twitter_*.csv \\
        --keyword 'phoebe bridgers'
"""

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict

from common import PLATFORM_LABELS

TYPE_LABELS = {
    "artist": "Artists", "brand": "Brands & products", "film_tv": "Film, TV & games",
    "place": "Places & venues", "event": "Events & festivals", "other": "Other",
}
MIN_ITEMS = 2  # an entity needs this many separate items to count


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _is_subject(name, keyword):
    """True for the query's own artist/song ('Phoebe', 'Phoebe Bridgers', 'Lost Boys')."""
    from query_utils import parse_query
    phrases, terms = parse_query(keyword)
    n = _norm(name)
    if not n:
        return True
    targets = [_norm(" ".join(terms))] + [_norm(p) for p in phrases]
    targets = [t for t in targets if t]
    # the full name, or a piece of it at least 4 chars long (first/last name)
    return any(n == t or (len(n) >= 4 and n in t) for t in targets)


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def build_affinities(items, keyword):
    """Aggregate mentions across items. Returns entity dicts, most-mentioned first."""
    acc = defaultdict(lambda: {
        "names": Counter(), "types": Counter(), "items": [], "authors": set(),
        "platforms": Counter(), "scores": [],
    })
    for it in items:
        seen = set()
        for m in it.get("mentions") or []:
            key = _norm(m.get("name"))
            if not key or key in seen or _is_subject(m.get("name"), keyword):
                continue
            seen.add(key)  # count an entity once per item
            a = acc[key]
            a["names"][m["name"].strip()] += 1
            a["types"][m.get("type") or "other"] += 1
            a["items"].append(it)
            a["authors"].add((it.get("platform"), it.get("author")))
            a["platforms"][it.get("platform", "")] += 1
            a["scores"].append(_num(it.get("sentiment_score")))

    total_items = len(items) or 1
    out = []
    for key, a in acc.items():
        n = len(a["items"])
        if n < MIN_ITEMS:
            continue
        avg = sum(a["scores"]) / n
        best = max(a["items"], key=lambda x: (_num(x.get("impact")), len(x.get("text") or "")))
        out.append({
            "name": a["names"].most_common(1)[0][0],
            "type": a["types"].most_common(1)[0][0],
            "items": n,
            "share": round(100 * n / total_items, 1),
            "authors": len(a["authors"]),
            "platforms": {p: c for p, c in a["platforms"].most_common()},
            "avg_sentiment": round(avg, 2),
            "example": (best.get("quote") or best.get("text") or "")[:220],
            "example_link": best.get("permalink", ""),
            "_snippets": [(x.get("text") or "")[:200] for x in
                          sorted(a["items"], key=lambda x: _num(x.get("impact")), reverse=True)[:4]],
        })
    out.sort(key=lambda e: (e["authors"], e["items"]), reverse=True)
    return out


# --------------------------------------------------------------------------
# Strategist read
# --------------------------------------------------------------------------

READ_PROMPT = """You're advising the marketing team for "{keyword}". Below are the other
artists, brands, shows, places and events that come up in the audience's own posts about
"{keyword}", with how many people mention each, the average sentiment of those posts
(-1..+1, toward "{keyword}", not the other entity), and sample snippets.

Return a JSON object:
- "summary": 2-3 sentences on the audience's cultural world: who and what they connect
  "{keyword}" to, and what that says about them as an audience.
- "positioning": 2-4 short bullets on how fans position "{keyword}" against the other artists
  they bring up (e.g. "the sadder Taylor Swift", "heir to Elliott Smith"), each grounded in snippets.
- "partnership_angles": 3-6 objects {{"entity", "angle": one concrete idea (tour support, brand
  collab, sync, playlist, venue, festival), "why": one sentence grounded in how fans mention it}}.
- "cautions": 0-3 strings: entities mentioned in a negative or mocking context, or comparisons
  that hurt, that the team should be careful leaning into.

Rules: only use entities listed below. Ground every claim in the snippets; don't invent
associations. Return ONLY JSON.

Entities:
{rows}"""


def affinity_read(entities, keyword, model, max_entities=30):
    if not entities:
        return None
    from brief import client, _extract_json_object
    rows = "\n".join(
        f'- {e["name"]} ({e["type"]}) · {e["authors"]} people, {e["items"]} posts · '
        f'avg sentiment {e["avg_sentiment"]:+.2f} · '
        f'{", ".join(PLATFORM_LABELS.get(p, p) for p in e["platforms"])}\n'
        + "\n".join(f'    "{s}"' for s in e["_snippets"])
        for e in entities[:max_entities]
    )
    print(f"  Affinity read over top {min(len(entities), max_entities)} entities...")
    try:
        msg = client().messages.create(
            model=model, max_tokens=2500,
            messages=[{"role": "user", "content": READ_PROMPT.format(keyword=keyword, rows=rows)}],
        )
        raw = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        return _extract_json_object(raw)
    except Exception as e:
        print(f"  (affinity read failed: {e})")
        return None


# --------------------------------------------------------------------------
# Mentions for items that don't have them (older CSVs)
# --------------------------------------------------------------------------

EXTRACT_PROMPT = """For each numbered item, list the other named things it refers to besides
"{keyword}": each {{"name": canonical public name, "type": one of "artist", "brand", "film_tv",
"place", "event", "other"}}. Only public entities (artists, bands, albums, brands, products, films,
shows, games, venues, festivals, cities). Never private people or usernames.

Return ONLY a JSON array of {{"id": item number, "mentions": [...]}}.

Items:
{items}"""


def extract_mentions(items, keyword, model, batch_size=25):
    """Fill it['mentions'] for items missing it. One cheap call per batch."""
    from claude_sentiment import client, _extract_json, _clean_mentions
    todo = [it for it in items if "mentions" not in it]
    for b in range(0, len(todo), batch_size):
        batch = todo[b:b + batch_size]
        print(f"    Extracting mentions {b + 1}-{b + len(batch)} of {len(todo)}...")
        numbered = "\n".join(f"{i}. {(it.get('text') or '')[:600]}" for i, it in enumerate(batch))
        try:
            msg = client().messages.create(
                model=model, max_tokens=4000,
                messages=[{"role": "user",
                           "content": EXTRACT_PROMPT.format(keyword=keyword, items=numbered)}],
            )
            raw = "".join(x.text for x in msg.content if getattr(x, "type", None) == "text")
            by_id = {r.get("id"): r for r in _extract_json(raw) if isinstance(r, dict)}
        except Exception as e:
            print(f"    (mention batch failed: {e})")
            by_id = {}
        for i, it in enumerate(batch):
            it["mentions"] = _clean_mentions((by_id.get(i) or {}).get("mentions"))
    return items


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def _cell(s):
    return str(s).replace("|", "/").replace("\n", " ")


def _bullet(v):
    """Reads sometimes return a bullet as an object ({label, detail}); flatten to text."""
    if isinstance(v, dict):
        return " — ".join(str(x) for x in v.values() if not isinstance(x, (dict, list)))
    return str(v)


def _plats(e):
    return ", ".join(f"{PLATFORM_LABELS.get(p, p)} {c}" for p, c in e["platforms"].items())


def markdown_section(entities, read=None, per_type=8):
    if not entities:
        return []
    L = ["---", "## Audience Affinity Map — what else this audience talks about", ""]
    L.append("*Other artists, brands, shows and places named in the audience's own posts. "
             "\"People\" counts distinct authors. Sentiment is toward the artist in posts "
             "mentioning each one. This is co-mention, not a population-based affinity score.*")
    L.append("")
    if read and read.get("summary"):
        L.append(read["summary"])
        L.append("")
    if read and read.get("positioning"):
        L.append("**How fans position the artist**")
        L.append("")
        L.extend(f"- {_bullet(p)}" for p in read["positioning"])
        L.append("")

    by_type = defaultdict(list)
    for e in entities:
        by_type[e["type"]].append(e)
    for t in TYPE_LABELS:
        rows = by_type.get(t)
        if not rows:
            continue
        L.append(f"**{TYPE_LABELS[t]}**")
        L.append("")
        L.append("| Name | People | Posts | Sentiment | Platforms | Example |")
        L.append("|---|---|---|---|---|---|")
        for e in rows[:per_type]:
            ex = f"\"{_cell(e['example'][:120])}\""
            if e["example_link"]:
                ex = f"[{ex}]({e['example_link']})"
            L.append(f"| {_cell(e['name'])} | {e['authors']} | {e['items']} ({e['share']}%) | "
                     f"{e['avg_sentiment']:+.2f} | {_plats(e)} | {ex} |")
        L.append("")

    if read and read.get("partnership_angles"):
        L.append("**Partnership angles**")
        L.append("")
        for a in read["partnership_angles"]:
            L.append(f"- **{a.get('entity', '')}** — {a.get('angle', '')}")
            if a.get("why"):
                L.append(f"  - {a['why']}")
        L.append("")
    if read and read.get("cautions"):
        L.append("**Cautions**")
        L.append("")
        L.extend(f"- {_bullet(c)}" for c in read["cautions"])
        L.append("")
    return L


CSV_COLS = ["rank", "name", "type", "authors", "items", "share", "avg_sentiment",
            "platforms", "example", "example_link"]


def write_affinity_csv(entities, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
        w.writeheader()
        for i, e in enumerate(entities, 1):
            w.writerow(dict(e, rank=i, platforms=_plats(e)))


# --------------------------------------------------------------------------
# Standalone
# --------------------------------------------------------------------------

def main():
    from output import parse_mentions
    from query_utils import safe_filename

    p = argparse.ArgumentParser(
        description="Build the Audience Affinity Map from per-source CSVs of an earlier run.")
    p.add_argument("csvs", nargs="+", help="pulse_<source>_*.csv (or chat CSV) files")
    p.add_argument("--keyword", required=True, help="the query the pulse was run for")
    p.add_argument("--model", default="claude-haiku-4-5-20251001",
                   help="model for extracting mentions from older CSVs")
    p.add_argument("--brief-model", default="claude-opus-4-8")
    p.add_argument("--no-read", action="store_true", help="skip the strategist read")
    p.add_argument("--out", default=None, help="output prefix (default: pulse_affinity_<keyword>)")
    args = p.parse_args()

    items = []
    for path in args.csvs:
        with open(path, newline="", encoding="utf-8") as f:
            if not f.readline().startswith("#"):  # chat CSVs start with a comment row
                f.seek(0)
            for row in csv.DictReader(f):
                if "mentions" in row:
                    row["mentions"] = parse_mentions(row["mentions"])
                row["sentiment_score"] = _num(row.get("sentiment_score"))
                row["impact"] = _num(row.get("impact"))
                items.append(row)
    if not items:
        sys.exit("  No rows found in those CSVs.")

    # Chat and per-source CSVs of the same run overlap; keep one copy per link+text.
    uniq = {}
    for it in items:
        uniq.setdefault((it.get("permalink"), (it.get("text") or "")[:200]), it)
    items = list(uniq.values())

    missing = sum(1 for it in items if "mentions" not in it)
    if missing:
        print(f"  {missing} items have no mentions column; extracting with {args.model}...")
        extract_mentions(items, args.keyword, args.model)

    entities = build_affinities(items, args.keyword)
    print(f"  {len(items)} items → {len(entities)} entities mentioned {MIN_ITEMS}+ times")
    read = None if args.no_read else affinity_read(entities, args.keyword, args.brief_model)

    prefix = args.out or f"pulse_affinity_{safe_filename(args.keyword)}"
    write_affinity_csv(entities, prefix + ".csv")
    with open(prefix + ".md", "w", encoding="utf-8") as f:
        f.write(f"# Audience Affinity Map — {args.keyword}\n\n")
        f.write("\n".join(markdown_section(entities, read)))
    print(f"  ✓ {prefix}.md\n  ✓ {prefix}.csv")


if __name__ == "__main__":
    main()
