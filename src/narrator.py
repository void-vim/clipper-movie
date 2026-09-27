"""Recap writing without a language model.

Follows PROMPT.md: the narrator only ever reuses lines that are actually spoken in
the part, glued together with fixed connective phrases, so nothing can be invented.
"""
from __future__ import annotations

import re

from .srt import Cue

# Length targets from PROMPT.md: 110-220 words, 6-12 quotes, 45-90 seconds of speech.
DEFAULT_WORDS = 200
MIN_LINES = 3
WORDS_PER_LINE = 18
MAX_QUOTE_WORDS = 26

OPENERS = (
    "Here is what happens next.",
    "Now things start to move.",
    "This is where it turns.",
    "Let us see how it unfolds.",
    "And now the next stretch.",
)
CONNECTORS = (
    "Then:", "Right after that:", "Meanwhile:", "But then:", "And so:", "From there:",
    "And just after that:", "On top of that:", "Even so:", "Then again:",
)
CLOSERS = (
    "And that is where we leave it.",
    "Which sets up everything that follows.",
    "And that is where our story picks up.",
    "And it leaves things wide open.",
    "And that is only the beginning of what comes next.",
    "Which is where the next part of this story begins.",
    "And from here, everything changes again.",
)
MAX_LINES = 6
MAX_WORDS = 100
MAX_QUOTE_WORDS = 26
SPEAKER_TAG_RE = re.compile(r"^\s*(?:[-–—\[\(]?\s*[A-Z][A-Z0-9 .'\-]{1,20}\s*[:\]\)]\s*)+")
ACTION_WORDS = frozenset(
    "dies dead death killed kills runs runs fled fights fight attacks attacks reveals "
    "revealed tells told asks asked explains explained confronts confronted decides "
    "decided discovers discovered admits admitted refuses refused promises promised "
    "threatens threatened warns warned returns returned leaves left arrives arrived "
    "opens closed breaks broke saves saved takes took gives gave loses lost wins won".split()
)
PRONOUN_START = frozenset(
    "i you he she it we they me him her us them my your his its our their this that".split()
)


def clean_line(text: str) -> str:
    line = SPEAKER_TAG_RE.sub("", text).strip()
    return re.sub(r"\s+", " ", line)


def trim_words(text: str, limit: int) -> str:
    words = text.split()
    if len(words) <= limit:
        return text
    return " ".join(words[:limit]).rstrip(",;:") + "."


def _named(cue: Cue) -> bool:
    body = clean_line(cue.text).split()
    return any(w[:1].isupper() and w.lower() not in PRONOUN_START and len(w) > 2 for w in body[1:])


def score(cue: Cue) -> float:
    text = clean_line(cue.text)
    if not text:
        return 0.0
    words = text.split()
    points = min(len(words), 20) * 0.12
    if any(w.lower().strip(".,!?") in ACTION_WORDS for w in words):
        points += 1.5
    if text.endswith(("!", "?")):
        points += 0.6
    if _named(cue):
        points += 0.8
    if len(words) >= 8:
        points += 0.3
    return points


def max_lines_for(budget: int) -> int:
    return max(MIN_LINES, round(budget / WORDS_PER_LINE))


def _pick_lines(window: list[Cue], limit: int, budget: int) -> list[Cue]:
    """Best lines of the segment, in chronological order."""
    ranked = sorted(window, key=score, reverse=True)
    chosen: list[Cue] = []
    seen: set[str] = set()
    total = 0
    for cue in ranked:
        text = trim_words(clean_line(cue.text), MAX_QUOTE_WORDS)
        count = len(text.split())
        if count < 4 or text in seen:
            continue
        if chosen and total + count > budget:
            continue
        seen.add(text)
        chosen.append(cue)
        total += count
        if len(chosen) >= limit or total >= budget:
            break
    return sorted(chosen, key=lambda c: c.start)


def write_recap(window: list[Cue], index: int,
                budget: int = DEFAULT_WORDS) -> list[tuple[str, float | None]]:
    """Return the beats, built only from the part's own dialogue.

    Each beat is (text, anchor) where anchor is the timestamp of the subtitle cue
    the beat talks about, so the recap plays while that scene is on screen.
    """
    if not window:
        return []
    lines = _pick_lines(window, max_lines_for(budget), budget)
    if not lines:
        lines = window[:2]
    beats: list[tuple[str, float | None]] = [
        (OPENERS[(index - 1) % len(OPENERS)], window[0].start)
    ]
    for i, cue in enumerate(lines):
        text = trim_words(clean_line(cue.text), MAX_QUOTE_WORDS)
        if not text:
            continue
        if i == 0:
            beats.append((text, cue.start))
        else:
            connector = CONNECTORS[(index + i) % len(CONNECTORS)]
            beats.append((f"{connector} {text}", cue.start))
    beats.append((CLOSERS[(index - 1) % len(CLOSERS)], None))
    return beats
