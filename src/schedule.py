"""Lay narration beats on a part's montage timeline.

A part is a sequence of short scene clips, so the narration runs over the montage and
each beat starts on the scene it describes. Beats never overlap.
"""
from __future__ import annotations

from dataclasses import dataclass

from .logutil import log
from .srt import Cue

BEAT_GAP = 0.6
LEAD = 0.4
# Clips and placements are rounded to milliseconds, so a hair of slack is not a gap.
SLACK = 0.2


@dataclass(frozen=True)
class Placement:
    text: str
    start: float
    duration: float


def scene_offsets(scenes: list[tuple[float, float]]) -> list[float]:
    """Where each scene starts inside the montage, in seconds."""
    offsets: list[float] = []
    cursor = 0.0
    for start, end in scenes:
        offsets.append(cursor)
        cursor += max(0.0, end - start)
    return offsets


def cover(scenes: list[tuple[float, float]], needed: float) -> list[tuple[float, float]]:
    """Repeat the scene list until the montage is at least `needed` seconds long."""
    if not scenes or needed <= 0:
        return list(scenes)
    out = list(scenes)
    one = sum(e - s for s, e in scenes)
    total = one
    while total < needed - SLACK:
        out.extend(scenes)
        total += one
    if len(out) > len(scenes):
        log("WARN", f"montage stretched to {total:.0f}s by repeating {len(scenes)} scene(s)")
    return out


def fit(scenes: list[tuple[float, float]], needed: float) -> list[tuple[float, float]]:
    """Montage long enough for the narration, without unused clips at the end."""
    out = cover(scenes, needed)
    while len(out) > 1 and scene_offsets(out)[-1] >= needed - SLACK:
        out = out[:-1]
    return out


def place(beats: list[str], durations: list[float], scenes: list[tuple[float, float]],
          delay: float, gap: float = BEAT_GAP) -> list[Placement]:
    """Start every beat on its scene when there is one, otherwise keep the order."""
    offsets = scene_offsets(scenes)
    placed: list[Placement] = []
    cursor = delay
    for i, (beat, duration) in enumerate(zip(beats, durations)):
        target = offsets[i] if i < len(offsets) else cursor
        start = max(delay, target, cursor)
        placed.append(Placement(text=beat, start=round(start, 3),
                                duration=round(duration, 3)))
        cursor = start + duration + gap
    return placed


def total_length(placed: list[Placement], delay: float, tail: float) -> float:
    if not placed:
        return delay
    return max(p.start + p.duration for p in placed) + tail


def cues_for_scenes(cues: list[Cue], scenes: list[tuple[float, float]],
                    ) -> list[Cue]:
    """Rebase the movie subtitles of every scene onto the montage timeline."""
    offsets = scene_offsets(scenes)
    out: list[Cue] = []
    for (start, end), offset in zip(scenes, offsets):
        for cue in cues:
            if cue.start >= start and cue.end <= end:
                out.append(Cue(cue.start - start + offset,
                               cue.end - start + offset, cue.text))
    out.sort(key=lambda c: c.start)
    return out
