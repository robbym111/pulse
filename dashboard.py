"""
dashboard.py — turn a pulse run into one self-contained HTML dashboard.

Every combined_report run writes pulse_<query>_<stamp>_dashboard.html next to
the brief. It's a single file: no server, no login, no external scripts, so it
opens offline in any browser and can be emailed or dropped into Slack as-is.

    python3 dashboard.py pulse_phoebe_bridgers_20260929_1543.json   # rebuild one
    python3 dashboard.py --latest                                   # newest JSON here

What's on it: the headline and TL;DR, a platform filter scoping the
conversation views (KPIs, volume and mood by day, themes, receipts), then the
whole-pulse views: sentiment mix and footprint by platform, Creator Discovery,
the Audience Affinity Map, TikTok sounds, and the per-platform briefs.

Scraped text is embedded as JSON and rendered with textContent only, never
innerHTML, so a post can't inject markup into the page.
"""

import argparse
import glob
import json
import os
import sys

from common import PLATFORM_LABELS

MAX_TEXT = 320


def _slim_item(it):
    return {
        "p": it.get("platform", ""),
        "t": it.get("type", ""),
        "a": it.get("author", ""),
        "ts": int(it.get("created_utc") or 0),
        "imp": float(it.get("impact") or 0),
        "s": round(float(it.get("sentiment_score") or 0), 2),
        "l": it.get("sentiment_label", "neutral"),
        "th": list(it.get("themes") or [])[:3],
        "q": it.get("quote") or "",
        "tx": (it.get("text") or "")[:MAX_TEXT],
        "u": it.get("permalink", ""),
        "snd": it.get("sound_title") if it.get("tiktok_via") == "sound" else "",
        "sid": it.get("sound_id") if it.get("tiktok_via") == "sound" else "",
        "sn": it.get("sound_video_count") if it.get("tiktok_via") == "sound" else None,
        "vc": int(it.get("view_count") or 0),
    }


def build_payload(run):
    briefs = run.get("briefs") or {}
    top = briefs.get("reddit") or briefs.get("twitter") or briefs.get("tiktok") \
        or briefs.get("youtube") or briefs.get("editorial") or {}
    return {
        "meta": run.get("meta", {}),
        "headline": top.get("headline", ""),
        "tldr": top.get("exec_summary", []),
        "labels": PLATFORM_LABELS,
        "items": [_slim_item(it) for it in run.get("items", [])],
        "briefs": briefs,
        "reads": run.get("reads") or {},
        "footprint": run.get("footprint") or [],
        "creators": (run.get("creators") or [])[:25],
        "affinities": [{k: v for k, v in e.items() if not k.startswith("_")}
                       for e in (run.get("affinities") or [])[:30]],
    }


def _safe_json(obj):
    """JSON that can't close its own <script> tag."""
    s = json.dumps(obj, ensure_ascii=False, default=str)
    return s.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def render(run):
    q = (run.get("meta") or {}).get("query", "Pulse")
    title = f"Pulse · {q}"
    return (TEMPLATE
            .replace("__TITLE__", title.replace("&", "&amp;").replace("<", "&lt;"))
            .replace("__DATA__", _safe_json(build_payload(run))))


def write_dashboard(run, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(render(run))


def main():
    p = argparse.ArgumentParser(description="Build an HTML dashboard from a pulse JSON export.")
    p.add_argument("json", nargs="?", help="pulse_<query>_<stamp>.json")
    p.add_argument("--latest", action="store_true", help="use the newest pulse_*.json here")
    p.add_argument("--out", help="output path (default: <json name>_dashboard.html)")
    args = p.parse_args()

    path = args.json
    if args.latest or not path:
        found = sorted(glob.glob("pulse_*.json"), key=os.path.getmtime)
        if not found:
            sys.exit("  No pulse_*.json here. Run combined_report.py first.")
        path = found[-1]
    with open(path, encoding="utf-8") as f:
        run = json.load(f)
    out = args.out or path[:-5] + "_dashboard.html"
    write_dashboard(run, out)
    print(f"  ✓ {out}")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --pos: #2a78d6; --neg: #e34948; --neutral: #d6d5cf; --wash: rgba(42,120,214,0.10);
  --good-text: #006300; --bad-text: #b32d2d; --chip: #efeee9;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --pos: #3987e5; --neg: #e66767; --neutral: #4a4a46; --wash: rgba(57,135,229,0.14);
    --good-text: #0ca30c; --bad-text: #f08a8a; --chip: #262624;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --pos: #3987e5; --neg: #e66767; --neutral: #4a4a46; --wash: rgba(57,135,229,0.14);
  --good-text: #0ca30c; --bad-text: #f08a8a; --chip: #262624;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 32px 16px 64px; }
header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.eyebrow { color: var(--muted); font-size: 13px; letter-spacing: .02em; text-transform: uppercase; }
h1 { font-size: 34px; line-height: 1.15; margin: 4px 0 6px; font-weight: 700; letter-spacing: -.01em; }
h2 { font-size: 20px; margin: 44px 0 4px; font-weight: 650; }
h3 { font-size: 15px; margin: 0 0 12px; font-weight: 600; }
.sub { color: var(--ink-2); margin: 0; }
.note { color: var(--muted); font-size: 13px; margin: 0 0 14px; }
button.theme { white-space: nowrap; flex-shrink: 0; background: var(--surface); color: var(--ink-2); border: 1px solid var(--border);
  border-radius: 8px; padding: 6px 12px; font: inherit; font-size: 13px; cursor: pointer; }
.headline { margin-top: 22px; background: var(--surface); border: 1px solid var(--border);
  border-radius: 14px; padding: 20px 22px; }
.headline p.big { font-size: 20px; font-weight: 600; margin: 0 0 10px; line-height: 1.35; }
.headline ul { margin: 0; padding-left: 20px; color: var(--ink-2); }
.headline li { margin: 3px 0; }
.filters { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 28px 0 16px; }
.filters .lbl { color: var(--muted); font-size: 13px; margin-right: 4px; }
.chip { border: 1px solid var(--border); background: var(--surface); color: var(--ink-2);
  border-radius: 999px; padding: 5px 14px; font: inherit; font-size: 14px; cursor: pointer; }
.chip[aria-pressed="true"] { background: var(--ink); color: var(--surface); border-color: var(--ink); }
.grid { display: grid; gap: 16px; }
.g2 { grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
.kpis { grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
  padding: 18px 20px; min-width: 0; }
.kpi .v { font-size: 34px; font-weight: 700; line-height: 1.1; margin-top: 4px; }
.kpi .k { color: var(--muted); font-size: 13px; }
.kpi .d { color: var(--ink-2); font-size: 13px; margin-top: 4px; }
.good { color: var(--good-text); } .bad { color: var(--bad-text); }
.chart { width: 100%; position: relative; }
.chart svg { display: block; width: 100%; height: auto; overflow: visible; }
.chart text { fill: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.chart text.lab { fill: var(--ink-2); font-variant-numeric: normal; }
.chart text.val { fill: var(--ink); }
.chart .gl { stroke: var(--grid); stroke-width: 1; }
.chart .ax { stroke: var(--axis); stroke-width: 1; }
.chart .hit { fill: transparent; cursor: default; }
.chart .hit:hover + .m, .chart .hit:focus + .m { opacity: .78; }
.legend { display: flex; gap: 16px; flex-wrap: wrap; color: var(--ink-2); font-size: 13px; margin: 0 0 10px; }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }
#tip { position: fixed; pointer-events: none; z-index: 10; background: var(--surface); color: var(--ink);
  border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; font-size: 13px;
  box-shadow: 0 6px 24px rgba(0,0,0,.14); max-width: 280px; display: none; }
#tip b { display: block; font-size: 15px; }
#tip span { color: var(--ink-2); }
details.tv { margin-top: 10px; }
details.tv summary { color: var(--muted); font-size: 13px; cursor: pointer; }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th { text-align: left; color: var(--muted); font-weight: 500; font-size: 12px; padding: 6px 8px;
  border-bottom: 1px solid var(--grid); }
td { padding: 8px; border-bottom: 1px solid var(--grid); vertical-align: top; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.scroll { overflow-x: auto; }
a { color: var(--pos); text-decoration: none; } a:hover { text-decoration: underline; }
.tag { display: inline-block; font-size: 12px; padding: 1px 8px; border-radius: 999px;
  background: var(--chip); color: var(--ink-2); white-space: nowrap; }
.inbar { height: 8px; border-radius: 0 4px 4px 0; background: var(--pos); min-width: 2px; }
.quotes { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }
.quote { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 16px 18px;
  display: flex; flex-direction: column; gap: 10px; }
.quote p { margin: 0; font-size: 15px; }
.quote .meta { color: var(--muted); font-size: 13px; display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.list { margin: 0; padding-left: 18px; } .list li { margin: 6px 0; }
.list .why { color: var(--ink-2); }
.more { margin-top: 12px; }
section.hide { display: none; }
footer { margin-top: 56px; color: var(--muted); font-size: 13px; }
@media (max-width: 560px) { h1 { font-size: 27px; } .kpi .v { font-size: 28px; } }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <div class="eyebrow">Pulse dashboard</div>
      <h1 id="q"></h1>
      <p class="sub" id="metaLine"></p>
    </div>
    <button class="theme" id="themeBtn" type="button">Dark mode</button>
  </header>
  <div class="headline" id="headline"></div>

  <div class="filters" id="filters"><span class="lbl">Platform</span></div>
  <div class="grid kpis" id="kpis"></div>

  <div class="grid g2" style="margin-top:16px">
    <div class="card"><h3>Volume by day</h3><div class="chart" id="volume"></div></div>
    <div class="card"><h3>Mood by day</h3><p class="note">Average sentiment, −1 to +1</p><div class="chart" id="mood"></div></div>
  </div>
  <div class="grid g2" style="margin-top:16px">
    <div class="card"><h3>What people are talking about</h3><p class="note">Top themes by number of posts</p><div class="chart" id="themes"></div></div>
    <div class="card"><h3>Sentiment mix</h3><p class="note">Share of posts, centered on neutral</p><div class="chart" id="mix"></div></div>
  </div>

  <h2>Receipts</h2>
  <p class="note">The most-engaged posts with a quotable line, for the current filter.</p>
  <div class="quotes" id="quotes"></div>
  <button class="chip more" id="moreQuotes" type="button">Show more</button>

  <section id="secFoot">
    <h2>Across platforms</h2>
    <p class="note">Whole pulse. "2.6×" = talked about 2.6 times as much on that platform as across the pulse. Shares depend on fetch limits.</p>
    <div class="card scroll" id="footTable"></div>
    <div class="grid g2" style="margin-top:16px" id="plays"></div>
  </section>

  <section id="secCreators">
    <h2>Creator Discovery</h2>
    <p class="note">Accounts ranked by the engagement they generated in this pulse, not followers.</p>
    <div class="card scroll" id="creatorTable"></div>
    <div class="grid g2" style="margin-top:16px" id="creatorReads"></div>
  </section>

  <section id="secAffinity">
    <h2>Audience Affinity Map</h2>
    <p class="note">Other artists, brands, shows and places the audience names. Co-mention, not a population index.</p>
    <div class="grid g2">
      <div class="card"><h3>Mentioned by the most people</h3><div class="chart" id="affinity"></div></div>
      <div class="card" id="affinityReads"></div>
    </div>
  </section>

  <section id="secSounds">
    <h2>TikTok sounds</h2>
    <div class="card scroll" id="soundTable"></div>
  </section>

  <section id="secBriefs">
    <h2>Platform briefs</h2>
    <div class="grid" id="briefs"></div>
  </section>

  <footer id="foot"></footer>
</div>
<div id="tip" role="status"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
(function () {
  "use strict";
  const D = JSON.parse(document.getElementById("data").textContent);
  const $ = (id) => document.getElementById(id);
  const NS = "http://www.w3.org/2000/svg";
  const label = (p) => D.labels[p] || p;
  const fmt = (n) => Math.round(n).toLocaleString();
  const sgn = (n) => (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(n).toFixed(2);
  const pct = (a, b) => (b ? Math.round(100 * a / b) : 0);
  // Model reads sometimes return a bullet as an object ({label, detail}); flatten to text.
  const txt = (v) => v == null ? "" : typeof v === "object" ? Object.values(v).filter((x) => typeof x !== "object").join(" — ") : String(v);
  const unquote = (s) => s.trim().replace(/^["“”']+|["“”']+$/g, "");

  // DOM helpers: all scraped text goes through textContent.
  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") n.className = v; else if (k === "style") n.style.cssText = v; else n.setAttribute(k, v);
    }
    for (const k of kids.flat(Infinity)) if (k != null && k !== false) n.append(k.nodeType ? k : document.createTextNode(String(k)));
    return n;
  }
  function svg(tag, attrs) {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
    return n;
  }
  function link(href, text) {
    return /^https?:\/\//.test(href || "") ? el("a", { href, target: "_blank", rel: "noopener" }, text) : el("span", {}, text);
  }

  // Theme toggle (remembered per viewer; storage may be unavailable).
  const root = document.documentElement;
  function isDark() { const t = root.dataset.theme; return t ? t === "dark" : matchMedia("(prefers-color-scheme: dark)").matches; }
  function syncBtn() { $("themeBtn").textContent = isDark() ? "Light mode" : "Dark mode"; }
  try { const t = localStorage.getItem("pulse-theme"); if (t) root.dataset.theme = t; } catch (e) {}
  $("themeBtn").onclick = () => {
    root.dataset.theme = isDark() ? "light" : "dark";
    try { localStorage.setItem("pulse-theme", root.dataset.theme); } catch (e) {}
    syncBtn(); drawAll();
  };
  syncBtn();

  // Tooltip
  const tip = $("tip");
  function showTip(evt, value, lab) {
    tip.replaceChildren(el("b", {}, value), el("span", {}, lab));
    tip.style.display = "block";
    const r = evt.target.getBoundingClientRect ? evt.target.getBoundingClientRect() : null;
    const x = evt.clientX || (r ? r.left + r.width / 2 : 0), y = evt.clientY || (r ? r.top : 0);
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.min(window.innerWidth - w - 8, Math.max(8, x + 12)) + "px";
    tip.style.top = Math.max(8, y - h - 12) + "px";
  }
  function hideTip() { tip.style.display = "none"; }
  function hover(node, value, lab) {
    node.setAttribute("tabindex", "0");
    node.setAttribute("aria-label", lab + ": " + value);
    node.addEventListener("pointermove", (e) => showTip(e, value, lab));
    node.addEventListener("focus", (e) => showTip(e, value, lab));
    node.addEventListener("pointerleave", hideTip);
    node.addEventListener("blur", hideTip);
  }
  const css = (v) => getComputedStyle(root).getPropertyValue(v).trim();

  function tableView(host, head, rows) {
    const t = el("table", {}, el("thead", {}, el("tr", {}, head.map((h, i) => el("th", i ? { class: "n" } : {}, h)))),
      el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c, i) => el("td", i ? { class: "n" } : {}, c))))));
    host.append(el("details", { class: "tv" }, el("summary", {}, "View as table"), el("div", { class: "scroll" }, t)));
  }

  // ---- charts ----------------------------------------------------------
  // Horizontal bars, one series (slot 1). rows: {label, value, tip}
  function hbar(host, rows, opts) {
    host.replaceChildren();
    if (!rows.length) { host.append(el("p", { class: "note" }, "Nothing to show for this filter.")); return; }
    const W = Math.max(280, host.clientWidth), labW = Math.min(170, W * 0.36), valW = 44, rowH = 30, bar = 14;
    const H = rows.length * rowH + 6, max = Math.max(...rows.map((r) => r.value)) || 1;
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.title });
    const x0 = labW + 8, span = W - x0 - valW;
    s.append(svg("line", { x1: x0, x2: x0, y1: 0, y2: H, class: "ax" }));
    rows.forEach((r, i) => {
      const y = i * rowH + (rowH - bar) / 2, w = Math.max(2, span * r.value / max);
      const t = svg("text", { x: labW, y: y + bar / 2 + 4, "text-anchor": "end", class: "lab" });
      t.textContent = r.label.length > 26 ? r.label.slice(0, 25) + "…" : r.label;
      const hit = svg("rect", { x: 0, y: i * rowH, width: W, height: rowH, class: "hit" });
      const m = svg("path", { class: "m", fill: css("--pos"),
        d: w < 6 ? `M${x0},${y}h${w}v${bar}h${-w}z`
                 : `M${x0},${y}h${w - 4}a4,4 0 0 1 4,4v${bar - 8}a4,4 0 0 1 -4,4h${-(w - 4)}z` });
      const v = svg("text", { x: x0 + w + 6, y: y + bar / 2 + 4, class: "val" });
      v.textContent = fmt(r.value);
      hover(hit, r.tip || fmt(r.value), r.label);
      s.append(t, hit, m, v);
    });
    host.append(s);
    tableView(host, [opts.labelHead || "Name", opts.valueHead || "Posts"], rows.map((r) => [r.label, fmt(r.value)]));
  }

  // Columns over days (one series). pts: {x: Date, value}
  function columns(host, pts, opts) {
    host.replaceChildren();
    if (pts.length < 2) { host.append(el("p", { class: "note" }, "Not enough dated posts to chart by day.")); return; }
    const W = Math.max(280, host.clientWidth), H = 190, L = 40, B = 24, T = 8;
    const max = niceMax(Math.max(...pts.map((p) => p.value)));
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.title });
    gridY(s, W, H, L, B, T, max, (v) => fmt(v));
    const band = (W - L) / pts.length, bw = Math.min(24, band - 2);
    pts.forEach((p, i) => {
      const h = (H - B - T) * p.value / max, x = L + i * band + (band - bw) / 2, y = H - B - h;
      const hit = svg("rect", { x: L + i * band, y: T, width: band, height: H - B - T, class: "hit" });
      const m = svg("path", { class: "m", fill: css("--pos"),
        d: h < 4 ? `M${x},${H - B}h${bw}v${-h}h${-bw}z`
                 : `M${x},${H - B}v${-(h - 4)}a4,4 0 0 1 4,-4h${bw - 8}a4,4 0 0 1 4,4v${h - 4}z` });
      hover(hit, fmt(p.value) + " posts", dayLabel(p.x));
      s.append(hit, m);
    });
    xLabels(s, pts, L, band, H);
    host.append(s);
    tableView(host, ["Day", "Posts"], pts.map((p) => [dayLabel(p.x), fmt(p.value)]));
  }

  // Line over days on a fixed −1..+1 scale with a zero baseline.
  function line(host, pts, opts) {
    host.replaceChildren();
    if (pts.length < 2) { host.append(el("p", { class: "note" }, "Not enough dated posts to chart by day.")); return; }
    const W = Math.max(280, host.clientWidth), H = 190, L = 40, B = 24, T = 8;
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.title });
    const y = (v) => T + (H - B - T) * (1 - (v + 1) / 2);
    [-1, -0.5, 0, 0.5, 1].forEach((v) => {
      s.append(svg("line", { x1: L, x2: W, y1: y(v), y2: y(v), class: v === 0 ? "ax" : "gl" }));
      const t = svg("text", { x: L - 6, y: y(v) + 4, "text-anchor": "end" }); t.textContent = v === 0 ? "0" : sgn(v).replace(".00", ".0"); s.append(t);
    });
    const band = (W - L) / pts.length, cx = (i) => L + i * band + band / 2;
    const d = pts.map((p, i) => (i ? "L" : "M") + cx(i) + "," + y(p.value)).join("");
    s.append(svg("path", { d: d + `L${cx(pts.length - 1)},${y(0)}L${cx(0)},${y(0)}Z`, fill: css("--wash"), stroke: "none" }));
    s.append(svg("path", { d, fill: "none", stroke: css("--pos"), "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    const last = pts.length - 1;
    s.append(svg("circle", { cx: cx(last), cy: y(pts[last].value), r: 4, fill: css("--pos"), stroke: css("--surface"), "stroke-width": 2 }));
    const lt = svg("text", { x: cx(last), y: y(pts[last].value) - 10, "text-anchor": "end", class: "val" });
    lt.textContent = sgn(pts[last].value); s.append(lt);
    pts.forEach((p, i) => {
      const hit = svg("rect", { x: L + i * band, y: T, width: band, height: H - B - T, class: "hit" });
      hover(hit, sgn(p.value) + " avg · " + fmt(p.n) + " posts", dayLabel(p.x));
      s.append(hit);
    });
    xLabels(s, pts, L, band, H);
    host.append(s);
    tableView(host, ["Day", "Avg sentiment", "Posts"], pts.map((p) => [dayLabel(p.x), sgn(p.value), fmt(p.n)]));
  }

  // Diverging stacked bars: negative left of center, neutral/mixed straddling it, positive right.
  function mix(host, rows) {
    host.replaceChildren();
    if (!rows.length) { host.append(el("p", { class: "note" }, "Nothing to show.")); return; }
    host.append(el("div", { class: "legend" },
      el("span", {}, el("i", { style: "background:var(--neg)" }), "Negative"),
      el("span", {}, el("i", { style: "background:var(--neutral)" }), "Neutral / mixed"),
      el("span", {}, el("i", { style: "background:var(--pos)" }), "Positive")));
    const W = Math.max(280, host.clientWidth), labW = 84, rowH = 34, bar = 16, H = rows.length * rowH + 22;
    const s = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Sentiment mix by platform" });
    const x0 = labW + 8, span = W - x0 - 4, mid = x0 + span / 2, k = span / 200;
    s.append(svg("line", { x1: mid, x2: mid, y1: 0, y2: H - 18, class: "ax" }));
    [["100%", x0], ["50%", x0 + span / 4], ["50%", mid + span / 4], ["100%", x0 + span]].forEach(([t, x]) => {
      const n = svg("text", { x, y: H - 4, "text-anchor": "middle" }); n.textContent = t; s.append(n);
    });
    rows.forEach((r, i) => {
      const y = i * rowH + (rowH - bar) / 2;
      const t = svg("text", { x: labW, y: y + bar / 2 + 4, "text-anchor": "end", class: "lab" }); t.textContent = r.label; s.append(t);
      const neuW = r.neu * k, negW = r.neg * k, posW = r.pos * k;
      const segs = [
        ["--neg", mid - neuW / 2 - negW, negW, r.neg + "% negative"],
        ["--neutral", mid - neuW / 2, neuW, r.neu + "% neutral / mixed"],
        ["--pos", mid + neuW / 2, posW, r.pos + "% positive"],
      ];
      segs.forEach(([c, x, w, lab], j) => {
        if (w <= 0) return;
        const gap = j < 2 && w > 3 ? 2 : 0;
        const m = svg("rect", { x, y, width: Math.max(1, w - gap), height: bar, fill: css(c), class: "m",
          rx: j === 1 ? 0 : 4 });
        const hit = svg("rect", { x, y: i * rowH, width: Math.max(8, w), height: rowH, class: "hit" });
        hover(hit, lab, r.label + " · " + fmt(r.n) + " posts");
        s.append(hit, m);
      });
    });
    host.append(s);
    tableView(host, ["Platform", "Negative", "Neutral / mixed", "Positive", "Posts"],
      rows.map((r) => [r.label, r.neg + "%", r.neu + "%", r.pos + "%", fmt(r.n)]));
  }

  function niceMax(v) { if (v <= 0) return 1; const p = Math.pow(10, Math.floor(Math.log10(v))); for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p; return 10 * p; }
  function gridY(s, W, H, L, B, T, max, f) {
    [0, 0.5, 1].forEach((fr) => {
      const y = T + (H - B - T) * (1 - fr);
      s.append(svg("line", { x1: L, x2: W, y1: y, y2: y, class: fr === 0 ? "ax" : "gl" }));
      const t = svg("text", { x: L - 6, y: y + 4, "text-anchor": "end" }); t.textContent = f(max * fr); s.append(t);
    });
  }
  function dayLabel(d) { return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }); }
  function xLabels(s, pts, L, band, H) {
    const every = Math.ceil(pts.length / Math.max(2, Math.floor((band * pts.length) / 64)));
    pts.forEach((p, i) => {
      if (i % every && i !== pts.length - 1) return;
      const t = svg("text", { x: L + i * band + band / 2, y: H - 6, "text-anchor": "middle" });
      t.textContent = dayLabel(p.x); s.append(t);
    });
  }

  // ---- data shaping ------------------------------------------------------
  const platforms = [...new Set(D.items.map((i) => i.p))].sort((a, b) =>
    D.items.filter((i) => i.p === b).length - D.items.filter((i) => i.p === a).length);
  let current = "all", quoteLimit = 9;
  const scoped = () => current === "all" ? D.items : D.items.filter((i) => i.p === current);

  function byDay(items) {
    const m = new Map();
    for (const it of items) {
      if (!it.ts) continue;
      const d = new Date(it.ts * 1000); d.setHours(0, 0, 0, 0);
      const k = +d; const e = m.get(k) || { x: d, value: 0, sum: 0 }; e.value++; e.sum += it.s; m.set(k, e);
    }
    const days = [...m.values()].sort((a, b) => a.x - b.x);
    if (!days.length) return [];
    const out = [], end = days[days.length - 1].x;
    for (let d = new Date(days[0].x); d <= end && out.length < 120; d.setDate(d.getDate() + 1)) {
      const e = m.get(+d); out.push({ x: new Date(d), value: e ? e.value : 0, sum: e ? e.sum : 0 });
    }
    return out;
  }

  function mixRow(lab, its) {
    const n = its.length, neg = its.filter((i) => i.l === "negative").length, pos = its.filter((i) => i.l === "positive").length;
    const p = pct(pos, n), q = pct(neg, n);
    return { label: lab, n, pos: p, neg: q, neu: Math.max(0, 100 - p - q) };
  }

  // ---- static sections -----------------------------------------------------
  function header() {
    const m = D.meta;
    $("q").textContent = m.query || "Pulse";
    const when = m.generated_utc ? new Date(m.generated_utc).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "";
    const since = m.since_utc ? " · since " + new Date(m.since_utc).toLocaleDateString(undefined, { dateStyle: "medium" }) : "";
    $("metaLine").textContent = `${fmt(m.n_items || D.items.length)} posts & comments · ${(m.sources || []).map(label).join(", ")}${since} · generated ${when}`;
    const h = $("headline");
    if (D.headline) h.append(el("p", { class: "big" }, D.headline));
    if (D.tldr && D.tldr.length) h.append(el("ul", {}, D.tldr.map((b) => el("li", {}, txt(b)))));
    if (!D.headline && !(D.tldr || []).length) h.remove();
    $("foot").textContent = "Built by pulse from public posts. Sentiment and synthesis by Claude. Indexes compare platforms within this pulse, not the whole internet.";
  }

  function filters() {
    const f = $("filters");
    ["all", ...platforms].forEach((p) => {
      const b = el("button", { class: "chip", type: "button", "aria-pressed": String(p === current) }, p === "all" ? "All" : label(p));
      b.onclick = () => { current = p; quoteLimit = 9; f.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", String(c === b))); drawScoped(); };
      f.append(b);
    });
    if (platforms.length < 2) f.style.display = "none";
  }

  function kpis(items) {
    const n = items.length, people = new Set(items.map((i) => i.p + "|" + i.a)).size;
    const avg = n ? items.reduce((a, i) => a + i.s, 0) / n : 0;
    const pos = pct(items.filter((i) => i.l === "positive").length, n), neg = pct(items.filter((i) => i.l === "negative").length, n);
    const tile = (k, v, d, cls) => el("div", { class: "card kpi" }, el("div", { class: "k" }, k), el("div", { class: "v " + (cls || "") }, v), d ? el("div", { class: "d" }, d) : null);
    $("kpis").replaceChildren(
      tile("Posts & comments", fmt(n), current === "all" ? platforms.length + " platform" + (platforms.length === 1 ? "" : "s") : label(current)),
      tile("People", fmt(people), "distinct authors"),
      tile("Avg sentiment", sgn(avg), avg >= 0.3 ? "▲ warm" : avg <= -0.2 ? "▼ sour" : "● mixed", avg >= 0.3 ? "good" : avg <= -0.2 ? "bad" : ""),
      tile("Positive", pos + "%", fmt(items.filter((i) => i.l === "positive").length) + " posts"),
      tile("Negative", neg + "%", fmt(items.filter((i) => i.l === "negative").length) + " posts", neg >= 25 ? "bad" : ""));
  }

  function quotes(items) {
    const host = $("quotes"); host.replaceChildren();
    const pool = items.filter((i) => i.q || i.tx).sort((a, b) => b.imp - a.imp || Math.abs(b.s) - Math.abs(a.s));
    const seen = new Set(), picks = [];
    for (const it of pool) { const k = (it.q || it.tx).slice(0, 80); if (seen.has(k)) continue; seen.add(k); picks.push(it); }
    picks.slice(0, quoteLimit).forEach((it) => {
      const tone = it.l === "negative" ? "var(--neg)" : it.l === "positive" ? "var(--pos)" : "var(--neutral)";
      host.append(el("div", { class: "quote" },
        el("p", {}, "“" + unquote(it.q || it.tx.slice(0, 220)) + "”"),
        el("div", { class: "meta" },
          el("span", { class: "dot", style: "background:" + tone, "aria-hidden": "true" }),
          el("span", {}, it.l + " " + sgn(it.s)), el("span", { class: "tag" }, label(it.p)),
          el("span", {}, it.a || ""), it.u ? link(it.u, "open ↗") : null)));
    });
    $("moreQuotes").style.display = picks.length > quoteLimit ? "" : "none";
  }
  $("moreQuotes").onclick = () => { quoteLimit += 9; quotes(scoped()); };

  function footprint() {
    const fp = D.footprint;
    if (fp.length < 2) { $("secFoot").classList.add("hide"); return; }
    const x = (i) => (i / 100).toFixed(1) + "×";
    const t = el("table", {}, el("thead", {}, el("tr", {}, ["Platform", "Posts", "People", "Sentiment", "Pos / Neg", "Over-indexes on", "Names it brings up"].map((h, i) => el("th", i && i < 5 ? { class: "n" } : {}, h)))),
      el("tbody", {}, fp.map((f) => el("tr", {},
        el("td", {}, label(f.platform)), el("td", { class: "n" }, fmt(f.items) + " (" + f.item_share + "%)"),
        el("td", { class: "n" }, fmt(f.people) + " (" + f.people_share + "%)"), el("td", { class: "n" }, sgn(f.avg_sentiment)),
        el("td", { class: "n" }, f.positive_pct + "% / " + f.negative_pct + "%"),
        el("td", {}, f.distinctive_themes.length ? f.distinctive_themes.map((d) => d.theme + " " + x(d.index)).join(", ") : "—"),
        el("td", {}, (f.top_mentions || []).map((m) => m.name).join(", ") || "—")))));
    $("footTable").replaceChildren(el("h3", {}, "Platform footprint"), t);
    const r = D.reads.footprint;
    if (r) {
      if (r.summary) $("plays").append(el("div", { class: "card" }, el("h3", {}, "Where the conversation is"), el("p", { class: "sub" }, r.summary)));
      if (r.platform_plays && r.platform_plays.length) $("plays").append(el("div", { class: "card" }, el("h3", {}, "Platform plays"),
        el("ul", { class: "list" }, r.platform_plays.map((p) => el("li", {}, el("b", {}, p.platform + " — "), el("span", { class: "why" }, p.play))))));
      if (r.gaps && r.gaps.length) $("plays").append(el("div", { class: "card" }, el("h3", {}, "Gaps to act on"), el("ul", { class: "list" }, r.gaps.map((g) => el("li", {}, txt(g))))));
    }
  }

  function creators() {
    const cs = D.creators.filter((c) => c.role !== "voice").slice(0, 15);
    if (!cs.length) { $("secCreators").classList.add("hide"); return; }
    const max = Math.max(...cs.map((c) => c.conversation_score)) || 1;
    const t = el("table", {}, el("thead", {}, el("tr", {}, ["#", "Account", "Platform", "Engagement generated", "Replies drawn", "Audience mood", "Themes"].map((h, i) => el("th", [0, 4, 5].includes(i) ? { class: "n" } : {}, h)))),
      el("tbody", {}, cs.map((c, i) => el("tr", {},
        el("td", { class: "n" }, i + 1),
        el("td", {}, link(c.top_link, c.author), c.role === "official" ? el("span", { class: "tag", style: "margin-left:6px" }, "official") : null),
        el("td", {}, label(c.platform)),
        el("td", { style: "min-width:160px" }, el("div", { style: "display:flex;align-items:center;gap:8px" },
          el("div", { class: "inbar", style: "width:" + Math.max(2, 110 * c.conversation_score / max) + "px" }),
          el("span", { style: "font-variant-numeric:tabular-nums;color:var(--ink-2)" }, fmt(c.conversation_score)))),
        el("td", { class: "n" }, fmt(c.replies_sparked)),
        el("td", { class: "n" }, c.audience_sentiment == null ? "—" : sgn(c.audience_sentiment)),
        el("td", {}, (c.top_themes || []).join(", ") || "—")))));
    $("creatorTable").replaceChildren(t);
    const r = D.reads.creators, host = $("creatorReads");
    if (r && r.partner_shortlist && r.partner_shortlist.length) host.append(el("div", { class: "card" }, el("h3", {}, "Partner shortlist"),
      el("ul", { class: "list" }, r.partner_shortlist.map((p) => el("li", {}, el("b", {}, p.account), " (" + (p.platform || "") + ") ", el("span", { class: "why" }, p.why), p.approach ? el("div", {}, "→ " + p.approach) : null)))));
    if (r && r.watch_list && r.watch_list.length) host.append(el("div", { class: "card" }, el("h3", {}, "Watch list"),
      el("ul", { class: "list" }, r.watch_list.map((w) => el("li", {}, el("b", {}, w.account), " (" + (w.platform || "") + ") ", el("span", { class: "why" }, w.why), w.how_to_react ? el("div", {}, "→ " + w.how_to_react) : null)))));
  }

  function affinityReads() {
    const r = D.reads.affinity, host = $("affinityReads");
    if (!r) { host.remove(); return; }
    if (r.summary) host.append(el("h3", {}, "Their cultural world"), el("p", { class: "sub" }, r.summary));
    if (r.positioning && r.positioning.length) host.append(el("h3", { style: "margin-top:16px" }, "How fans position the artist"), el("ul", { class: "list" }, r.positioning.map((p) => el("li", {}, txt(p)))));
    if (r.partnership_angles && r.partnership_angles.length) host.append(el("h3", { style: "margin-top:16px" }, "Partnership angles"),
      el("ul", { class: "list" }, r.partnership_angles.map((a) => el("li", {}, el("b", {}, a.entity + " — "), a.angle, a.why ? el("div", { class: "why" }, a.why) : null))));
    if (r.cautions && r.cautions.length) host.append(el("h3", { style: "margin-top:16px" }, "Cautions"), el("ul", { class: "list" }, r.cautions.map((c) => el("li", {}, txt(c)))));
  }

  function sounds() {
    const by = new Map();
    D.items.filter((i) => i.sid).forEach((i) => { const e = by.get(i.sid) || []; e.push(i); by.set(i.sid, e); });
    if (!by.size) { $("secSounds").classList.add("hide"); return; }
    const rows = [...by.entries()].sort((a, b) => b[1].length - a[1].length).map(([sid, its]) => {
      const vids = its.filter((i) => i.t === "post"), f = vids[0] || its[0];
      const top = vids.sort((a, b) => b.imp - a.imp).slice(0, 3);
      return el("tr", {}, el("td", {}, f.snd || sid), el("td", { class: "n" }, f.sn != null ? fmt(f.sn) : "—"),
        el("td", { class: "n" }, fmt(vids.length)), el("td", { class: "n" }, fmt(vids.reduce((a, v) => a + v.vc, 0))),
        el("td", { class: "n" }, sgn(its.reduce((a, v) => a + v.s, 0) / its.length)),
        el("td", {}, top.map((v, k) => [k ? ", " : "", link(v.u, v.a)])));
    });
    $("soundTable").replaceChildren(el("table", {}, el("thead", {}, el("tr", {}, ["Sound", "Videos on TikTok", "Pulled", "Views (pulled)", "Mood", "Top creators on it"].map((h, i) => el("th", i && i < 5 ? { class: "n" } : {}, h)))), el("tbody", {}, rows)));
  }

  function briefs() {
    const order = ["reddit", "twitter", "tiktok", "youtube", "editorial"];
    const host = $("briefs"), names = { editorial: "Music press" };
    const keys = order.filter((k) => D.briefs[k]);
    if (!keys.length) { $("secBriefs").classList.add("hide"); return; }
    keys.forEach((k, i) => {
      const b = D.briefs[k];
      const body = el("div", { style: "padding-top:8px" });
      if (b.narrative) body.append(el("p", { class: "sub" }, b.narrative));
      if (b.whats_exciting && b.whats_exciting.length) body.append(el("h3", { style: "margin-top:14px" }, "What's resonating"),
        el("ul", { class: "list" }, b.whats_exciting.map((h) => el("li", {}, el("b", {}, h.hook), h.evidence ? el("span", { class: "why" }, " — “" + h.evidence + "”") : null))));
      if (b.creative_ideas && b.creative_ideas.length) body.append(el("h3", { style: "margin-top:14px" }, "Ideas"), el("ul", { class: "list" }, b.creative_ideas.map((x) => el("li", {}, txt(x)))));
      if (b.watch_outs && b.watch_outs.length) body.append(el("h3", { style: "margin-top:14px" }, "Watch-outs"),
        el("ul", { class: "list" }, b.watch_outs.map((w) => el("li", {}, el("b", {}, w.concern), w.how_to_react ? el("div", { class: "why" }, "→ " + w.how_to_react) : null))));
      const d = el("details", i ? {} : { open: "" }, el("summary", { style: "cursor:pointer;font-weight:600" }, (names[k] || label(k)) + (b.headline ? " — " + b.headline : "")), body);
      host.append(el("div", { class: "card" }, d));
    });
  }

  // ---- render --------------------------------------------------------------
  function drawScoped() {
    const items = scoped();
    kpis(items);
    const days = byDay(items);
    columns($("volume"), days, { title: "Posts per day" });
    line($("mood"), days.filter((d) => d.value).map((d) => ({ x: d.x, value: d.sum / d.value, n: d.value })), { title: "Average sentiment per day" });
    const th = new Map();
    items.forEach((i) => i.th.forEach((t) => { const e = th.get(t) || { n: 0, s: 0 }; e.n++; e.s += i.s; th.set(t, e); }));
    hbar($("themes"), [...th.entries()].sort((a, b) => b[1].n - a[1].n).slice(0, 10)
      .map(([t, e]) => ({ label: t, value: e.n, tip: fmt(e.n) + " posts · mood " + sgn(e.s / e.n) })), { title: "Top themes", labelHead: "Theme" });
    const rows = current === "all" ? platforms.map((p) => mixRow(label(p), D.items.filter((i) => i.p === p))) : [mixRow(label(current), items)];
    if (current === "all" && platforms.length > 1) rows.unshift(mixRow("All", D.items));
    mix($("mix"), rows);
    quotes(items);
  }
  function drawWhole() {
    const aff = D.affinities.slice(0, 12);
    if (!aff.length) $("secAffinity").classList.add("hide");
    else hbar($("affinity"), aff.map((e) => ({ label: e.name, value: e.authors,
      tip: fmt(e.authors) + " people · " + fmt(e.items) + " posts · mood " + sgn(e.avg_sentiment) })), { title: "Most-mentioned names", labelHead: "Name", valueHead: "People" });
  }
  function drawAll() { drawScoped(); drawWhole(); }

  header(); filters(); footprint(); creators(); affinityReads(); sounds(); briefs(); drawAll();
  let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(drawAll, 150); });
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
