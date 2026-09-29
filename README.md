# reddit-pulse

Cross-platform sentiment monitoring for music releases and any other keyword.
Pulls from Reddit, Twitter/X, YouTube, TikTok, and music press, scores
everything with the Claude API, and produces a terminal summary, per-source
CSVs, and a marketer's brief in Markdown.

---

## What's in the box

| File | What it does |
|---|---|
| `combined_report.py` | Main runner — all five sources, produces the brief |
| `main.py` | Quick runner — Reddit + Twitter only |
| `common.py` | Shared item schema, text cleaning, junk filter |
| `reddit_source.py` | Reddit via public RSS feeds (no credentials) |
| `twitter_source.py` | Twitter/X via twscrape |
| `youtube_source.py` | YouTube via Data API v3 |
| `tiktok_source.py` | TikTok via TikTokApi (scraper, flaky) |
| `editorial_source.py` | Music press via RSS (no key needed) |
| `claude_sentiment.py` | Batched sentiment scoring — Claude API |
| `brief.py` | Second-pass synthesis — marketer's brief |
| `output.py` | Terminal summary + CSV export |
| `twitter_setup.py` | One-time Twitter cookie setup |
| `tiktok_setup.py` | One-time TikTok ms_token setup |

---

## Setup

### 1. Install dependencies

```bash
cd reddit-pulse
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install chromium   # for TikTok only
```

### 2. Copy and fill in your .env

```bash
cp .env.example .env
```

Open `.env` and add your keys. Full list below.

### 3. One-time source setup

**Reddit** — no setup needed. Uses Reddit's public RSS feeds (API app
registration is gated behind a manual approval form, so we don't use it).
Post scores are fetched best-effort from the public JSON endpoint.

**Twitter/X** — run the cookie setup script once:
```bash
python3 twitter_setup.py
```
Go to x.com, open DevTools → Application → Cookies → https://x.com,
copy `auth_token` and `ct0`, paste when prompted. Sessions are stored
locally and reused. If it stops working, re-run this script.

**YouTube** — create a free API key at console.cloud.google.com.
Enable "YouTube Data API v3", create an API key, add to `.env`.
Free quota is 10,000 units/day — plenty.

**TikTok** — run the ms_token setup once:
```bash
python3 tiktok_setup.py
```
Go to tiktok.com, open DevTools → Application → Cookies → https://www.tiktok.com,
copy `msToken`, paste when prompted. Token expires — re-run if TikTok
stops returning results. TikTok is the flakiest source; it works but
breaks when they update their anti-bot measures.

**Editorial** — no setup needed. Uses public music-press RSS feeds.
Outlets: Pitchfork, Stereogum, Rolling Stone, NME, Consequence, The Guardian,
Billboard, Paste, DIY, Clash. Edit the `FEEDS` dict in `editorial_source.py`
to add or remove outlets.

**Anthropic** — get an API key at console.anthropic.com and add to `.env`.

---

## Credentials (.env)

```bash
# Twitter/X (set by twitter_setup.py — don't edit manually)
# stored in .twscrape/accounts.db

# YouTube
YOUTUBE_API_KEY=your_youtube_key

# TikTok (set by tiktok_setup.py)
TIKTOK_MS_TOKEN=your_ms_token

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Running a pulse

### Full cross-platform report (all 5 sources)

```bash
python3 combined_report.py "Lost Boys" \
  --subreddits indieheads,popheads,phoebebridgers,BoyGenius,fantanoforever,folk \
  --time week
```

Produces:
- `pulse_combined_lost_boys_TIMESTAMP_brief.md` — the unified marketer's brief
- `pulse_reddit_...csv`, `pulse_youtube_...csv`, etc. — per-source CSVs

### Quick Reddit + Twitter pulse

```bash
python3 main.py "Lost Boys" \
  --sources reddit,twitter \
  --subreddits indieheads,popheads,phoebebridgers,BoyGenius,fantanoforever,folk
```

---

## Key flags — combined_report.py

| Flag | Default | What it does |
|---|---|---|
| `--subreddits` | `indieheads,popheads` | Comma-separated, no `r/` |
| `--time` | `week` | hour / day / week / month / year / all |
| `--post-limit` | `10` | Posts/videos per source |
| `--comments-per-post` | `15` | Comments per post/video |
| `--editorial-days` | `30` | How far back to scan press |
| `--model` | `claude-haiku-4-5` | Per-item scoring model |
| `--brief-model` | `claude-opus-4-8` | Synthesis model for the brief |
| `--skip-reddit` | — | Skip that source |
| `--skip-youtube` | — | Skip that source |
| `--skip-editorial` | — | Skip that source |
| `--skip-twitter` | — | Skip that source |
| `--skip-tiktok` | — | Skip that source |
| `--tiktok-videos` | `10` | TikTok videos to scrape |
| `--tiktok-comments` | `20` | Comments per TikTok video |

---

## Cost

The only thing that costs money is the Anthropic API.

**Per-item scoring** uses Haiku by default — roughly $0.001–0.003 per run
depending on volume. A typical full-source pull of 400 items runs under $0.10.

**Brief synthesis** uses Opus by default — one call per source, so 5 calls per
full run. Each call is roughly $0.05–0.15 depending on corpus size. A full
5-source run costs roughly $0.25–$0.75 total, dominated by the brief.

To cut costs: use `--skip-tiktok --skip-youtube` for a cheaper quick read,
or set `--brief-model claude-sonnet-4-6` if Opus feels like overkill.

---

## How data quality works

All source text goes through `common.py` before scoring:

- HTML entities decoded (`&#32;`, `&amp;`, etc.)
- Bare URLs stripped
- Boilerplate filtered (mod messages, RSS scaffolding, link-only posts)
- Empty and sub-3-character items dropped

Stickied/mod posts are skipped at the Reddit source level, not the filter level,
so they never hit the scorer.

This was verified against a real 451-row CSV — the filter correctly dropped 6
genuine junk rows while preserving fan posts that happened to contain boilerplate
phrases in context (e.g. a post mentioning "submitted by" in the body text).

---

## How impact scoring works

```
Reddit/YouTube:  (upvotes + 2 × comments) × (0.5 + upvote_ratio)
Twitter/TikTok:  likes + 3 × replies + 2 × retweets + 2.5 × quotes
Editorial:       tier-based (Pitchfork/Rolling Stone = 100, mid-tier = 60, others = 30)
```

Comments and replies are weighted higher than passive signals (likes/upvotes)
because they represent higher-effort engagement. Tune weights in each source
module's `_impact()` function.

---

## Architecture

Every source module's `fetch_items()` returns a list of items built through
`common.make_item()` — a single shared schema. This means `output.py`,
`brief.py`, and `combined_report.py` can safely read any field from any source
without guessing whether it exists. If you add a new source, build items through
`make_item()` and everything downstream works automatically.

```
fetch_items()           →   list of make_item() dicts
  ↓
common.clean_text()     →   HTML decoded, URLs stripped
common.is_junk()        →   boilerplate filtered
  ↓
claude_sentiment.py     →   label, score (-1 to +1), themes
  ↓
brief.py                →   narrative synthesis, hooks, ideas, watch-outs
  ↓
output.py               →   terminal summary + CSV
combined_report.py      →   unified .md brief
```

---

## Troubleshooting

**Twitter returns 0 tweets** — cookies expired. Re-run `python3 twitter_setup.py`.

**TikTok returns 0 videos** — ms_token expired. Re-run `python3 tiktok_setup.py`.
If it still fails, TikTok may have updated their anti-bot measures — check the
TikTokApi GitHub for updates.

**YouTube raises 403** — API key missing or quota exceeded (10k units/day free).
Check console.cloud.google.com for quota status.

**Editorial returns 0 articles** — some RSS feed URLs may have changed. Check
the `FEEDS` dict in `editorial_source.py` and verify URLs work in a browser.
The source fails gracefully (logs and skips), so it won't crash the run.

**Sentiment batch fails** — check your `ANTHROPIC_API_KEY` in `.env`. If the
key is valid and it's still failing, the model name may be wrong — check the
current model strings at console.anthropic.com.

**"No active accounts"** — run the relevant setup script (`twitter_setup.py`
or `tiktok_setup.py`). Sessions are stored in `.twscrape/` and `.env` locally.
