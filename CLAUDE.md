# CLAUDE.md

Guidance for Claude Code when working in this repo.

## What this is

reddit-pulse: cross-platform sentiment monitoring for music releases (or any
keyword). It pulls from Reddit, Twitter/X, YouTube, TikTok, and music-press RSS,
scores each item with the Claude API, and writes a terminal summary, per-source
CSVs, and a Markdown marketer's brief. Plain Python scripts, no package or
build step.

## Running

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python3 -m playwright install chromium   # TikTok only

python3 combined_report.py "Lost Boys" --subreddits indieheads,popheads --time week
python3 main.py "Lost Boys" --sources reddit,twitter
```

There's no test suite. To check a change, do a small real run with cheap
settings (e.g. `--post-limit 3 --skip-tiktok --skip-twitter`), or call the
module function directly. `editorial_source` and `reddit_source` need no keys.

## Architecture

```
<source>_source.fetch_items()  -> list of common.make_item() dicts
common.clean_text / is_junk    -> HTML decoded, URLs stripped, boilerplate dropped
claude_sentiment.score_items() -> label, score (-1..+1), themes (batched)
brief.synthesize_brief()       -> per-source narrative brief (one call per source)
creator_discovery              -> rank accounts by engagement generated (+1 call)
affinity_map                   -> co-mentioned artists/brands/shows/places (+1 call)
footprint                      -> per-platform share, mood, over-indexed themes (+1 call)
export                         -> pulse_*.json per run + append to pulse_history.db
history.py                     -> CLI over pulse_history.db (trend / compare / sql)
dashboard                      -> pulse_*_dashboard.html, self-contained, from the run JSON
output.py                      -> terminal summary + CSV
combined_report.py             -> unified .md brief
```

- **Every source must build its items through `common.make_item()`.** Downstream
  code reads fields without checking whether they exist, so the schema can't
  be allowed to drift.
- Each source defines its own `_impact()` engagement score.
- `query_utils.py` turns one raw query into each platform's search syntax
  (`for_twitter`, `for_reddit`, ...) and provides `relevance_matcher`.
- Sources fail gracefully: they log the problem and return what they have,
  so one broken source doesn't kill the run. Keep it that way.
- `reddit_source.py` uses Reddit's public RSS/JSON feeds, not PRAW, so it
  needs no credentials. Reddit gates API app registration behind a manual
  approval form, which is why.
- `social_search_source.py` is a Brave Search fallback for social content.

## Config / secrets

These are read from `.env` via python-dotenv, or from environment variables:

| Var | Used by | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | `claude_sentiment.py`, `brief.py` | required |
| `YOUTUBE_API_KEY` | `youtube_source.py` | YouTube Data API v3 |
| `TIKTOK_MS_TOKEN` | `tiktok_source.py` | set by `tiktok_setup.py`, expires |
| `BRAVE_API_KEY` | `social_search_source.py` | optional |
| `TWSCRAPE_DB` | twitter | default `.twscrape/accounts.db`, set by `twitter_setup.py` |

Never commit `.env`, `.twscrape/`, cookies, or tokens (all gitignored).
Generated `pulse_*.csv` and `pulse_*_brief.md` files are gitignored too.

## Who uses this and what they want

The user is a creative marketer in music, not an engineer. They're comfortable
running CLI commands once things are set up.

- The primary deliverable is the `_brief.md`. CSVs and terminal output are
  secondary. Briefs go into decks and get shared with teams.
- Brief structure that works: TL;DR (3 bullets) → narrative paragraph →
  what's exciting fans (hooks + evidence quotes) → ideas to build on
  (concrete campaign ideas) → watch-outs (honest criticism + how to react)
  → receipts (verbatim quotes with links).
- Never sugarcoat. Flag negative sentiment clearly so they can make decisions.
- Queries can be any artist, song, album, or tour, written like a Google
  search (e.g. `phoebe bridgers "lost boys"`). Irrelevant matches (other
  "Lost Boys") are a known problem; `query_utils.relevance_matcher` handles it.
- Typical run: `combined_report.py '<query>' --since 3d --post-limit 50
  --tweet-limit 300 --tiktok-videos 30 --tiktok-comments 30`. Full runs take
  30+ minutes, so run them in the background and check the log.

## Known issues

- **X/Twitter returns 0 tweets with no error:** upgrade twscrape first
  (`pip install -U twscrape`), then re-test with a 5-tweet search. This fixed
  it twice (0.19.1→0.20.0, 0.20.0→0.20.1). Check whether the account is
  locked next. Refresh cookies via `twitter_setup.py` only as a last resort.
- `twitter_setup.py`'s add-account silently no-ops if the username is already
  in the pool. Delete the account first so new cookies actually get written.
- TikTok is the flakiest source (ms_token expires, anti-bot changes). It's
  often skipped with `--skip-tiktok`. TikTokApi has no keyword video search,
  so `tiktok_source` combines hashtags, the artist's account (found via user
  search on the query's bare terms) and sound feeds (`api.sound(id).videos()`).
  Each item records `tiktok_via` (hashtag / artist_account / sound) and its sound.
- Instagram: no source. Scraping it isn't viable; the official Graph API
  needs admin access to the artist's business account, which the user
  doesn't have.

## Audience intelligence (StatSocial-style)

The direction is audience intelligence, always from public content already in
the pulse. It never profiles identifiable individuals, never links handles
across platforms, and never uses personal disclosures (health, trauma,
politics, etc.) as a reason to target someone.

- **Built: Creator Discovery** (`creator_discovery.py`). Ranks each
  (platform, author) by own impact + the impact of replies it drew, plus
  2 points per reply. Replies are credited to the parent post's author via
  permalink (Reddit, TikTok) or to the video's channel (`video_channel`,
  YouTube). Roles: creator / official (handle ≈ artist in the query) /
  voice (commenter only). Only creators go to the partner/watch-list read.
- **Built: Audience Affinity Map** (`affinity_map.py`). The scoring pass
  returns `mentions` per item (public entities only, typed artist / brand /
  film_tv / place / event / other). The map counts distinct authors and posts
  per entity (once per item, the query's own artist/song excluded, min 2
  posts), with platform split, avg sentiment and an example. One read adds
  positioning, partnership angles and cautions. There's no population
  baseline, so it's co-mention, not a true affinity index.
- **Built: Cross-Platform Footprint** (`footprint.py`). Per platform: share
  of items and distinct authors, mood, median engagement (never summed
  across platforms, since the currencies differ), and themes/mentions indexed
  against the pulse average (shown as multiples, e.g. 2.6×). Brief section
  only when 2+ platforms. The read gives a play per platform and gaps.
- **Built: export layer** (`export.py`, `history.py`). One JSON per run, plus
  a SQLite history (runs, items, creators, affinities, platforms). Re-appending
  a run_id replaces it. Both files are gitignored.

## Dashboard

`dashboard.py` renders the run dict (same shape as the JSON export) into one
HTML file: inline CSS/JS, hand-built SVG charts, no external requests. Scraped
text is embedded as JSON and only ever inserted with textContent. Colors are
tokens on :root with light/dark variants (palette validated for CVD).
Strategist reads sometimes return bullets as objects rather than strings;
both the dashboard (`txt`) and the Markdown sections flatten them.

## Conventions

- Default models: `--model` (per-item scoring) is Haiku; `--brief-model`
  (synthesis) is Opus. Scoring runs on every item, so keep it on a cheap model.
- The argparse defaults in the code are the source of truth. The flag table
  in the README has drifted from them (e.g. `--post-limit`).
- Match the existing style: module docstring explaining the "why", small
  top-level functions, stdlib where practical.
