"""
export.py — structured delivery of every pulse, plus a history across runs.

The StatSocial "enterprise delivery" idea, sized for one marketer:

  - pulse_<query>_<stamp>.json: the whole run in one file (meta, every scored
    item, the per-source briefs, creators, affinities, footprint, and the
    strategist reads). Anything downstream (a dashboard, a notebook, another
    Claude chat, Snowflake later) reads this instead of scraping Markdown.
  - pulse_history.db (SQLite): every run appended, so you can compare artists
    and track how sentiment, platforms, creators and co-mentions move over
    time. Open it with history.py, the sqlite3 CLI, or DB Browser for SQLite.

Stdlib only.
"""

import json
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, query TEXT, generated_utc TEXT, since_utc TEXT,
    n_items INTEGER, avg_sentiment REAL, sources TEXT, json_path TEXT
);
CREATE TABLE IF NOT EXISTS items (
    run_id TEXT, platform TEXT, type TEXT, id TEXT, author TEXT, created_utc INTEGER,
    impact REAL, sentiment_label TEXT, sentiment_score REAL, themes TEXT, mentions TEXT,
    quote TEXT, takeaway TEXT, permalink TEXT, text TEXT, sound_title TEXT,
    PRIMARY KEY (run_id, platform, type, id)
);
CREATE TABLE IF NOT EXISTS creators (
    run_id TEXT, rank INTEGER, platform TEXT, author TEXT, role TEXT,
    conversation_score REAL, posts INTEGER, replies_sparked INTEGER,
    avg_sentiment REAL, audience_sentiment REAL, top_link TEXT
);
CREATE TABLE IF NOT EXISTS affinities (
    run_id TEXT, rank INTEGER, name TEXT, type TEXT, authors INTEGER, items INTEGER,
    avg_sentiment REAL
);
CREATE TABLE IF NOT EXISTS platforms (
    run_id TEXT, platform TEXT, items INTEGER, people INTEGER, avg_sentiment REAL,
    positive_pct INTEGER, negative_pct INTEGER, distinctive_themes TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_query ON runs(query);
"""


def _public(d):
    """Drop internal keys (leading underscore) before exporting."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


def build_run(query, stamp, since, items, briefs=None, creators=None, affinities=None,
              footprint=None, reads=None):
    scores = [float(it.get("sentiment_score") or 0) for it in items]
    return {
        "meta": {
            "run_id": f"{stamp}_{query}",
            "query": query,
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "since_utc": since.isoformat() if since else None,
            "n_items": len(items),
            "avg_sentiment": round(sum(scores) / len(scores), 3) if scores else 0.0,
            "sources": sorted({it.get("platform", "") for it in items}),
        },
        "briefs": briefs or {},
        "reads": reads or {},
        "footprint": footprint or [],
        "creators": creators or [],
        "affinities": [_public(e) for e in affinities or []],
        "items": items,
    }


def write_json(run, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(run, f, ensure_ascii=False, indent=1, default=str)


def append_history(run, db_path, json_path=""):
    """Append one run to the SQLite history. Re-running the same run_id replaces it."""
    m = run["meta"]
    rid = m["run_id"]
    con = sqlite3.connect(db_path)
    try:
        con.executescript(SCHEMA)
        for t in ("runs", "items", "creators", "affinities", "platforms"):
            con.execute(f"DELETE FROM {t} WHERE run_id = ?", (rid,))
        con.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)", (
            rid, m["query"], m["generated_utc"], m["since_utc"], m["n_items"],
            m["avg_sentiment"], ",".join(m["sources"]), json_path))
        con.executemany("INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [(
            rid, it.get("platform"), it.get("type"), str(it.get("id")), it.get("author"),
            int(it.get("created_utc") or 0), float(it.get("impact") or 0),
            it.get("sentiment_label"), float(it.get("sentiment_score") or 0),
            "; ".join(it.get("themes") or []),
            "; ".join(m_["name"] for m_ in it.get("mentions") or []),
            it.get("quote"), it.get("takeaway"), it.get("permalink"), it.get("text"),
            it.get("sound_title"),
        ) for it in run["items"]])
        con.executemany("INSERT INTO creators VALUES (?,?,?,?,?,?,?,?,?,?,?)", [(
            rid, i, c["platform"], c["author"], c["role"], c["conversation_score"], c["posts"],
            c["replies_sparked"], c["avg_sentiment"], c["audience_sentiment"], c["top_link"],
        ) for i, c in enumerate(run["creators"], 1)])
        con.executemany("INSERT INTO affinities VALUES (?,?,?,?,?,?,?)", [(
            rid, i, e["name"], e["type"], e["authors"], e["items"], e["avg_sentiment"],
        ) for i, e in enumerate(run["affinities"], 1)])
        con.executemany("INSERT INTO platforms VALUES (?,?,?,?,?,?,?,?)", [(
            rid, f["platform"], f["items"], f["people"], f["avg_sentiment"], f["positive_pct"],
            f["negative_pct"],
            ", ".join(f'{d["theme"]} ({d["index"] / 100:.1f}x)' for d in f["distinctive_themes"]),
        ) for f in run["footprint"]])
        con.commit()
    finally:
        con.close()
