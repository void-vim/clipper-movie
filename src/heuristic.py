"""Deterministic story segmentation from subtitle structure alone.

No model is involved: cuts land on dialogue boundaries that score highest for
silence gaps, sentence completion and proximity to the target part length.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .narrator import DEFAULT_WORDS, write_recap
from .scenes import UNANCHORED, from_anchors
from .parts import Part, derive_hook, renumber
from .srt import Cue

HARD_SCENE_GAP = 2.5
STRONG_SCENE_GAP = 1.5
SHORT_PART_RATIO = 0.6
SCENE_FLOOR_RATIO = 0.75
SENTENCE_END = ".!?"
SOFT_END = ",;:—"
GAP_CAP = 1.5
SCENE_SECONDS = 3.0
GAP_WEIGHT = 1.0
STRONG_GAP_BONUS = 1.5
TARGET_BONUS = 4.0
TARGET_SPREAD = 0.25


@dataclass(frozen=True)
class Boundary:
    index: int
    time: float
    base: float
    hard: bool

    def score_at(self, cursor: float, target: float) -> float:
        return self.base + _target_bonus(self.time - cursor, target)


def _gap_before(cue: Cue, prev: Cue | None) -> float:
    return max(0.0, cue.start - prev.end) if prev else 0.0


def _punctuation_bonus(prev: Cue | None) -> float:
    if prev is None:
        return 0.0
    text = prev.text.rstrip()
    if not text:
        return 0.0
    if text[-1] in SENTENCE_END:
        return 1.0
    return 0.4 if text[-1] in SOFT_END else 0.0


def _target_bonus(offset: float, target: float) -> float:
    """Peaks when the candidate sits `target` seconds after the current cursor."""
    spread = max(1.0, TARGET_SPREAD * target)
    return TARGET_BONUS * math.exp(-pow((offset - target) / spread, 2))


def build_boundaries(cues: list[Cue], target: float) -> list[Boundary]:
    """Score every cue start as a possible cut, relative to each part's cursor."""
    out: list[Boundary] = []
    prev: Cue | None = None
    for i, cue in enumerate(cues):
        if i == 0:
            prev = cue
            continue
        gap = _gap_before(cue, prev)
        base = min(gap, GAP_CAP) * GAP_WEIGHT + _punctuation_bonus(prev)
        if gap >= STRONG_SCENE_GAP:
            base += STRONG_GAP_BONUS
        out.append(Boundary(index=i, time=cue.start, base=base, hard=gap >= HARD_SCENE_GAP))
        prev = cue
    return out


def _pick(candidates: list[Boundary], cursor: float, target: float) -> Boundary | None:
    if not candidates:
        return None
    return max(candidates, key=lambda b: (b.score_at(cursor, target), -abs(b.time - cursor - target)))


def _cut_times(cues: list[Cue], duration: float, lo: float, hi: float,
               target: float) -> list[float]:
    boundaries = build_boundaries(cues, target)
    cuts: list[float] = []
    cursor = cues[0].start
    while duration - cursor > lo:
        pick = _choose(boundaries, cursor, duration, lo, hi, target)
        if pick is None or pick.time <= cursor:
            break
        cuts.append(pick.time)
        cursor = pick.time
    return cuts


def _choose(boundaries: list[Boundary], cursor: float, duration: float,
            lo: float, hi: float, target: float) -> Boundary | None:
    """Best boundary for the next cut: near the target, else a real scene change."""
    upper = min(cursor + hi, duration)
    window = [b for b in boundaries if cursor + lo <= b.time <= upper]
    if window:
        return _pick(window, cursor, target)
    scenes = [b for b in boundaries
              if cursor + lo * SCENE_FLOOR_RATIO <= b.time < cursor + lo and b.hard]
    if scenes:
        return _pick(scenes, cursor, target)
    rest = [b for b in boundaries if b.time > cursor + lo * SHORT_PART_RATIO]
    return rest[0] if rest else None


def _merge_short_tail(cuts: list[float], duration: float, lo: float) -> list[float]:
    if cuts and duration - cuts[-1] < lo * SHORT_PART_RATIO:
        return cuts[:-1]
    return cuts


def segment(cues: list[Cue], duration: float, lo: float, hi: float, target: float) -> list[float]:
    """Return the part start/end cut times covering the film."""
    end = max(duration, cues[-1].end)
    start = cues[0].start
    cuts = _cut_times(cues, end, lo, hi, target)
    cuts = _merge_short_tail(cuts, end, lo)
    points = [start, *cuts, end]
    return [(round(a, 3), round(b, 3)) for a, b in zip(points, points[1:]) if b - a > 0.5]


def to_parts(cues: list[Cue], duration: float, lo: float, hi: float, target: float,
             budget: int = DEFAULT_WORDS, scene_seconds: float = SCENE_SECONDS) -> list[Part]:
    """Segment the film and attach a written recap plus scene clips to every part."""
    parts: list[Part] = []
    for index, (start, end) in enumerate(segment(cues, duration, lo, hi, target), start=1):
        window = [c for c in cues if c.end > start and c.start < end]
        beats = write_recap(window, index, budget)
        anchors = [UNANCHORED if t is None else t for _, t in beats]
        clips = from_anchors(anchors, [t for t, _ in beats], window, start, end, scene_seconds)
        narration = " ".join(t for t, _ in beats)
        parts.append(Part(
            index=index, start=start, end=end, narration=narration,
            beats=tuple(t for t, _ in beats),
            anchors=tuple(anchors),
            hook=derive_hook(narration),
            scenes=tuple(clips),
        ))
    return renumber(parts)
