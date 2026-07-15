"""
query_utils.py — parse and route Google-style search queries to each platform.

Users type a natural search query, e.g.:
    phoebe bridgers lost boys
    "lost boys" phoebe bridgers
    taylor swift "eras tour" setlist
    chanel beads "your day will come"

Each platform gets the query formatted for its own search syntax.
"""

import re


def parse_query(raw):
    """
    Break a Google-style query into quoted phrases and bare terms.

    Returns:
        phrases  — list of exact-phrase strings (were in quotes)
        terms    — list of individual bare words (not quoted)

    Example:
        '"lost boys" phoebe bridgers'
        → phrases=["lost boys"], terms=["phoebe", "bridgers"]
    """
    phrases = re.findall(r'"([^"]+)"', raw)
    bare = re.sub(r'"[^"]+"', "", raw)
    terms = [t for t in bare.split() if t and not t.startswith("-")]
    return phrases, terms


def for_twitter(raw):
    """
    Twitter search operators:
      "exact phrase"  → required exact match
      word            → required word anywhere in tweet

    Multi-word bare input like 'phoebe bridgers lost boys' becomes
    '"phoebe bridgers" "lost boys"' — we group consecutive bare words
    into a phrase so Twitter doesn't just scatter-match individual words.

    If the user already quoted things, honour them exactly.
    """
    # If user already used quotes, pass through with bare terms as-is
    if '"' in raw:
        return raw.strip()
    # No quotes: treat the whole thing as a required phrase
    # This prevents "lost boys" matching unrelated Lost Boys content
    return f'"{raw.strip()}"'


def for_reddit(raw):
    """
    Reddit search in a scoped subreddit is forgiving — multi-word queries
    work as AND by default. Strip quotes so Reddit doesn't do literal
    punctuation matching, which can miss results.
    """
    return re.sub(r'"', "", raw).strip()


def for_youtube(raw):
    """YouTube search handles natural language well. Pass through as-is."""
    return raw.strip()


def for_tiktok(raw):
    """TikTok search: same as Twitter — quote if no existing quotes."""
    if '"' in raw:
        return raw.strip()
    return f'"{raw.strip()}"'


def for_editorial(raw):
    """RSS keyword matching — strip quotes, match on words."""
    return re.sub(r'"', "", raw).strip()


def relevance_matcher(raw):
    """
    Build a predicate that decides whether a piece of text is on-topic for the
    query. Used to filter YouTube videos and TikTok videos, whose native search
    back-fills with loosely-related content when the query is niche.

    A text is relevant if EITHER:
      • it contains one of the quoted phrases (e.g. the song title), OR
      • it contains ALL of the bare terms (e.g. the full artist name).

    The "all bare terms" rule is what stops generic single-token leakage: for
    'dinosaur jr "several got away"' a Jurassic-Park clip tagged #dinosaur has
    "dinosaur" but not "jr", so it fails — while a real Dinosaur Jr. video has
    both. Short tokens like "jr" are kept (matched on word boundaries) precisely
    because they're the discriminator. If the query has no phrases or terms,
    everything is relevant (no filtering).

    Returns a callable: is_relevant(text) -> bool.
    """
    phrases, terms = parse_query(raw)
    phrases = [p.lower() for p in phrases]
    terms = [t.lower() for t in terms]

    if not phrases and not terms:
        return lambda text: True

    term_patterns = [re.compile(r"\b" + re.escape(t) + r"\b") for t in terms]

    def is_relevant(text):
        low = (text or "").lower()
        if phrases and any(p in low for p in phrases):
            return True
        if term_patterns and all(pat.search(low) for pat in term_patterns):
            return True
        return False

    return is_relevant


def safe_filename(raw, max_len=60):
    """
    Convert a search query to a safe filename fragment.
    Strips quotes and operators, collapses spaces to underscores.
    """
    clean = re.sub(r'["\-+()]', "", raw)
    clean = re.sub(r"\s+", "_", clean.strip()).lower()
    clean = re.sub(r"[^\w]", "", clean)
    return clean[:max_len].strip("_")


def display_query(raw):
    """Human-readable version of the query for report headers."""
    return raw.strip()
