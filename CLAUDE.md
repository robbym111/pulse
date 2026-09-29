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
  needs no credentials. The README and `.env.example` still mention PRAW
  and the `REDDIT_*` variables; that's out of date.
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

## Conventions

- Default models: `--model` (per-item scoring) is Haiku; `--brief-model`
  (synthesis) is Opus. Scoring runs on every item, so keep it on a cheap model.
- The argparse defaults in the code are the source of truth. The flag table
  in the README has drifted from them (e.g. `--post-limit`).
- Match the existing style: module docstring explaining the "why", small
  top-level functions, stdlib where practical.
