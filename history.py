"""
history.py — read the pulse history database (pulse_history.db) from the terminal.

    python3 history.py                              # every run, newest first
    python3 history.py trend 'phoebe bridgers'      # one artist over time
    python3 history.py compare 'phoebe bridgers' 'boygenius'   # latest runs side by side
    python3 history.py sql "SELECT name, SUM(authors) FROM affinities GROUP BY name ORDER BY 2 DESC LIMIT 20"

Queries match loosely: 'phoebe' finds every run whose query contains it.
"""

import argparse
import os
import sqlite3
import sys

from common import PLATFORM_LABELS


CREATORS_ONLY = " AND role = 'creator'"


def _con(path):
    if not os.path.exists(path):
        sys.exit(f"  No history yet at {path}. Run combined_report.py first.")
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _runs(con, q=None):
    sql = "SELECT * FROM runs"
    args = ()
    if q:
        sql += " WHERE lower(query) LIKE ?"
        args = (f"%{q.lower()}%",)
    return con.execute(sql + " ORDER BY generated_utc", args).fetchall()


def _platforms(con, rid):
    rows = con.execute("SELECT * FROM platforms WHERE run_id = ? ORDER BY items DESC", (rid,))
    return ", ".join(f'{PLATFORM_LABELS.get(r["platform"], r["platform"])} {r["avg_sentiment"]:+.2f}'
                     for r in rows)


def _top(con, table, col, rid, n=3, where=""):
    rows = con.execute(f"SELECT {col} FROM {table} WHERE run_id = ? {where} ORDER BY rank LIMIT ?",
                       (rid, n)).fetchall()
    return ", ".join(r[0] for r in rows) or "—"


def cmd_list(con, _):
    rows = _runs(con)
    print(f"  {'date':<17} {'items':>5} {'sent':>6}  query  (sources)")
    for r in reversed(rows):
        print(f"  {r['generated_utc'][:16]:<17} {r['n_items']:>5} {r['avg_sentiment']:>+6.2f}  "
              f"{r['query']}  ({r['sources']})")


def cmd_trend(con, args):
    rows = _runs(con, args.query)
    if not rows:
        sys.exit(f"  No runs matching {args.query!r}.")
    for r in rows:
        rid = r["run_id"]
        print(f"\n  {r['generated_utc'][:16]} · {r['query']} · {r['n_items']} items · "
              f"sentiment {r['avg_sentiment']:+.2f}")
        print(f"    by platform: {_platforms(con, rid) or '—'}")
        print(f"    top names:   {_top(con, 'affinities', 'name', rid)}")
        print(f"    top creators: {_top(con, 'creators', 'author', rid, where=CREATORS_ONLY)}")


def cmd_compare(con, args):
    for q in args.queries:
        rows = _runs(con, q)
        if not rows:
            print(f"\n  {q}: no runs")
            continue
        r = rows[-1]
        rid = r["run_id"]
        print(f"\n  {r['query']} (latest: {r['generated_utc'][:16]})")
        print(f"    {r['n_items']} items · sentiment {r['avg_sentiment']:+.2f}")
        print(f"    by platform: {_platforms(con, rid) or '—'}")
        print(f"    top names:   {_top(con, 'affinities', 'name', rid, n=5)}")
        print(f"    top creators: {_top(con, 'creators', 'author', rid, n=5, where=CREATORS_ONLY)}")


def cmd_sql(con, args):
    cur = con.execute(args.statement)
    cols = [d[0] for d in cur.description or []]
    print("  " + " | ".join(cols))
    for row in cur.fetchall():
        print("  " + " | ".join(str(v) for v in row))


def main():
    p = argparse.ArgumentParser(description="Read the pulse history database.")
    p.add_argument("--db", default="pulse_history.db")
    sub = p.add_subparsers(dest="cmd")
    t = sub.add_parser("trend", help="one query over time")
    t.add_argument("query")
    c = sub.add_parser("compare", help="latest runs of several queries side by side")
    c.add_argument("queries", nargs="+")
    s = sub.add_parser("sql", help="run any SELECT")
    s.add_argument("statement")
    args = p.parse_args()

    con = _con(args.db)
    {"trend": cmd_trend, "compare": cmd_compare, "sql": cmd_sql}.get(args.cmd, cmd_list)(con, args)


if __name__ == "__main__":
    main()
