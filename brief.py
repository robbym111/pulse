"""
brief.py — second-pass synthesis that turns scored items into a marketer's brief.

The per-item pass (claude_sentiment.py) tells you *what each post says*.
This pass reads the whole corpus at once and tells you *what to do about it*:
a narrative pulse, the creative hooks fans are reacting to, ideas to build on,
and an honest read of the criticism so you can react to it.
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
    "You are a sharp creative strategist at a music marketing agency. You read raw fan "
    "discourse from Reddit and turn it into an honest, actionable brief for the artist's "
    "marketing team. You are NOT a hype machine — you celebrate what's genuinely resonating "
    "AND you flag criticism clearly so the team can make informed decisions. You think in "
    "terms of creative hooks, world-building, shareable moments, and campaign ideas. You "
    "ground every claim in what fans actually said. You return strict JSON only."
)

PROMPT_TEMPLATE = """You're briefing the marketing team for "{keyword}". Below is {framing},
each item with its sentiment score and the verbatim text.

Read ALL of it, then return a JSON object with these fields:

- "headline": one punchy sentence capturing the overall fan pulse (≤120 chars).
- "exec_summary": array of exactly 3 bullet strings a busy executive reads in 10 seconds.
  Bullet 1 = the overall reception in plain terms. Bullet 2 = the single biggest opportunity to
  act on. Bullet 3 = the single biggest risk/watch-out. Each ≤140 chars, no fluff.
- "narrative": a 3-5 sentence paragraph synthesizing how fans are reacting. Be specific and
  honest — name the dominant emotion, what's driving it, and any tension. Write like a strategist,
  not a press release.
- "whats_exciting": array of 3-6 objects, each {{"hook": short phrase for the creative angle fans
  are latching onto (e.g. world-building element, aesthetic, lyric, video moment), "why_it_works":
  one sentence on the fan psychology, "evidence": a short verbatim quote from the data that proves it}}.
  Prioritize world-building, aesthetics, and the moments fans are spontaneously creating content around.
- "creative_ideas": array of 4-6 concrete, campaign-ready ideas the team could execute, each a single
  actionable sentence directly inspired by what fans are doing/saying (e.g. UGC angles, merch, content
  series, community activations). Be specific, not generic.
- "watch_outs": array of 1-4 objects, each {{"concern": the criticism or risk in one clear sentence,
  "evidence": verbatim quote or paraphrase, "how_to_react": one sentence of honest strategic advice}}.
  If sentiment is overwhelmingly positive, still surface the sharpest critical or lukewarm notes —
  do not invent problems, but do not sugarcoat. If there is genuinely no criticism, say so in one entry.

Return ONLY the JSON object, no prose, no markdown fences.

Fan discourse:
{items}"""


def _extract_json_object(raw):
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in response: {raw[:200]}")
    return json.loads(raw[start : end + 1])


SOURCE_FRAMING = {
    "reddit": "fan discourse pulled from Reddit",
    "youtube": "fan comments pulled from YouTube videos",
    "twitter": (
        "public tweets from Twitter/X, retrieved via search index. "
        "These are short-form hot takes — treat them as real-time signal for trending opinions, "
        "memes, and emotional reactions. Quote verbatim where punchy."
    ),
    "editorial": (
        "professional music-press criticism (reviews and opinionated features). "
        "These are critics, not fans — weigh their craft assessments, comparisons to the "
        "artist's past work, and verdicts. 'whats_exciting' should capture what critics "
        "praise and the narrative hooks they're amplifying; 'watch_outs' should capture "
        "genuine critical reservations"
    ),
    "tiktok": (
        "TikTok video descriptions and comments. These skew younger and more visceral than "
        "Reddit or Twitter — short, emotional, trend-driven. Video descriptions tell you what "
        "creators are making; comments tell you how audiences react in real time. "
        "Look for sounds/audio trends, duet behaviour, aesthetic hooks, and meme formats "
        "that are forming around the music. Quote verbatim — the voice matters as much as the sentiment."
    ),
}


def synthesize_brief(items, keyword, model="claude-opus-4-8", max_items=80, source="reddit"):
    """Run one synthesis call over the corpus. Returns a dict (or None on failure)."""
    # Rank by sentiment magnitude so the most opinionated items survive the cap
    ranked = sorted(items, key=lambda x: abs(x.get("sentiment_score", 0)), reverse=True)
    sample = ranked[:max_items]

    numbered = "\n".join(
        f'[{it.get("sentiment_score", 0):+.2f} | {it.get("venue") or "r/" + it.get("subreddit","")}] {it.get("text","")[:400]}'
        for it in sample
    )

    framing = SOURCE_FRAMING.get(source, SOURCE_FRAMING["reddit"])
    prompt = PROMPT_TEMPLATE.format(keyword=keyword, items=numbered, framing=framing)

    print(f"  Synthesizing brief from {len(sample)} items...")
    msg = client().messages.create(
        model=model,
        max_tokens=4000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(block.text for block in msg.content if getattr(block, "type", None) == "text")
    try:
        return _extract_json_object(raw)
    except Exception as e:
        print(f"  (brief synthesis failed: {e})")
        return None
