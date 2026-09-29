"""
claude_sentiment.py — batched sentiment scoring via the Anthropic API.

We send ~15 items per call and ask for a JSON array back. Each item gets:
  - label: positive | negative | neutral | mixed
  - score: -1.0 (most negative) to 1.0 (most positive)
  - themes: 1-3 short tags (e.g. "antonoff-production", "nostalgia", "video-praise")
  - mentions: other public artists/brands/shows/places named (feeds affinity_map)

Batching is the whole cost game. 300 comments at 1 call each is 300 calls;
batched at 15, it's 20 calls. Same tokens in, far less overhead.
"""

import json
import os
import re

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

_client = None


def client():
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("Missing ANTHROPIC_API_KEY. Add it to your .env file.")
        _client = Anthropic()
    return _client


SYSTEM = (
    "You are a precise sentiment analyst for music/social-media discourse. "
    "You read Reddit posts and comments and judge the author's sentiment toward "
    "the SUBJECT of discussion (a song, artist, release). You account for sarcasm, "
    "irony, fandom in-jokes, and faint praise. You return strict JSON only."
)

PROMPT_TEMPLATE = """Score each numbered item below for sentiment toward "{keyword}".

For each item return:
- "id": the item number (integer)
- "label": one of "positive", "negative", "neutral", "mixed"
- "score": float from -1.0 (most negative) to 1.0 (most positive)
- "themes": array of 1-3 lowercase-hyphenated theme tags capturing what the comment is ABOUT (e.g. "production-criticism", "nostalgia", "video-praise", "lyric-quality", "excitement-for-album"). Keep tags reusable across items.
- "quote": the single most quotable, specific sentence from the text that best captures the author's reaction. Must be an actual verbatim excerpt (≤180 chars). If the text has no quotable sentence, return null.
- "takeaway": one crisp sentence summarizing the key insight or opinion expressed. Write it as a third-person observation, e.g. "Fan draws parallels between Lost Boys and Stranger Things aesthetic."
- "mentions": array of other named things the text refers to, besides "{keyword}" itself: each {{"name": canonical public name (e.g. "Taylor Swift", not "tswift"), "type": one of "artist", "brand", "film_tv", "place", "event", "other"}}. Only public entities: artists, bands, albums, brands, products, films, shows, games, venues, festivals, cities. Never private people or usernames. Empty array if none.

Sarcasm and faint praise matter: "wow another masterpiece /s" is negative; "it's fine I guess" is mildly negative; "this is growing on me" is mildly positive.

Return ONLY a JSON array, no prose, no markdown fences.

Items:
{items}"""


def _extract_json(raw):
    """Pull a JSON array out of the model response, tolerating stray fences."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON array in response: {raw[:200]}")
    return json.loads(raw[start : end + 1])


def _score_batch(batch, keyword, model):
    numbered = "\n".join(
        f'{i}. [{it["type"]} | {it.get("venue") or "r/" + it.get("subreddit", "")}] {it["text"]}'
        for i, it in enumerate(batch)
    )
    msg = client().messages.create(
        model=model,
        max_tokens=4000,
        system=SYSTEM,
        messages=[{"role": "user", "content": PROMPT_TEMPLATE.format(keyword=keyword, items=numbered)}],
    )
    raw = "".join(block.text for block in msg.content if getattr(block, "type", None) == "text")
    results = _extract_json(raw)

    by_id = {r["id"]: r for r in results if isinstance(r, dict) and "id" in r}
    for i, it in enumerate(batch):
        r = by_id.get(i, {})
        it["sentiment_label"] = r.get("label", "neutral")
        try:
            it["sentiment_score"] = float(r.get("score", 0.0))
        except (TypeError, ValueError):
            it["sentiment_score"] = 0.0
        themes = r.get("themes", [])
        it["themes"] = themes if isinstance(themes, list) else []
        it["quote"] = r.get("quote") or None
        it["takeaway"] = r.get("takeaway") or None
        it["mentions"] = _clean_mentions(r.get("mentions"))
    return batch


MENTION_TYPES = {"artist", "brand", "film_tv", "place", "event", "other"}


def _clean_mentions(raw):
    out = []
    for m in raw if isinstance(raw, list) else []:
        if isinstance(m, dict) and str(m.get("name") or "").strip():
            t = m.get("type") if m.get("type") in MENTION_TYPES else "other"
            out.append({"name": str(m["name"]).strip()[:80], "type": t})
    return out


def score_items(items, model, batch_size=15, keyword=""):
    scored = []
    total_batches = (len(items) + batch_size - 1) // batch_size
    for b in range(0, len(items), batch_size):
        batch = items[b : b + batch_size]
        n = b // batch_size + 1
        print(f"    Scoring batch {n}/{total_batches} ({len(batch)} items)...")
        try:
            scored.extend(_score_batch(batch, keyword, model))
        except Exception as e:
            print(f"    (batch {n} failed: {e} — marking neutral)")
            for it in batch:
                it.setdefault("sentiment_label", "neutral")
                it.setdefault("sentiment_score", 0.0)
                it.setdefault("themes", [])
                it.setdefault("mentions", [])
            scored.extend(batch)
    return scored
