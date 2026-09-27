"""Pick the short scene clips a part shows.

Every part is a montage of a few seconds of the film, so the footage is only a sample of
the segment while the narration can be much longer. The plan may list the scenes itself;
otherwise they are taken from the lines the narration is built on.
"""
from __future__ import annotations

from .logutil import log
from .srt import Cue, format_timestamp, nearest, parse_timestamp

SNAP_TOLERANCE = 2.0
MIN_SCENE = 0.8
LEAD = 0.3
UNANCHORED = -1.0


def _warn(message: str) -> None:
    log("WARN", message)


def _snap(value: float, targets: list[float], prefer: str) -> float:
    hit = nearest(value, targets, SNAP_TOLERANCE, prefer)
    return round(value if hit is None else hit, 3)


def _pair(entry: object) -> tuple[str | float | None, str | float | None]:
    if isinstance(entry, dict):
        return (entry.get("start_timestamp", entry.get("start")),
                entry.get("end_timestamp", entry.get("end")))
    if isinstance(entry, str) and "-->" in entry:
        left, right = entry.split("-->", 1)
        return left.strip(), right.strip()
    if isinstance(entry, (list, tuple)) and len(entry) >= 2:
        return entry[0], entry[1]
    return None, None


def _value(raw: object) -> float | None:
    if raw is None or str(raw).strip() == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return parse_timestamp(str(raw))
    except ValueError:
        return None


def _clean(start: float, end: float, cues: list[Cue], lo: float, hi: float,
           label: str, warn) -> tuple[float, float] | None:
    starts = [c.start for c in cues]
    ends = [c.end for c in cues]
    start = _snap(max(lo, min(start, hi)), starts, "ceil")
    end = _snap(min(hi, max(end, lo)), ends, "floor")
    if end <= start:
        warn(f"{label} {format_timestamp(start)} is empty after snapping, dropped")
        return None
    if end - start < MIN_SCENE:
        warn(f"{label} is only {end - start:.1f}s after snapping, dropped")
        return None
    return start, end


def parse(items: object, cues: list[Cue], lo: float, hi: float, warn) -> list[tuple[float, float]]:
    """Read the `scenes` array of a plan item, keeping only usable clips."""
    if not isinstance(items, list):
        warn("scenes must be an array of start/end pairs, the plan scenes were ignored")
        return []
    out: list[tuple[float, float]] = []
    for i, entry in enumerate(items, start=1):
        raw_start, raw_end = _pair(entry)
        start, end = _value(raw_start), _value(raw_end)
        if start is None or end is None:
            warn(f"scene {i} has no readable start/end, dropped")
            continue
        if end <= start:
            warn(f"scene {i} ends before it starts, dropped")
            continue
        if start < lo - 0.5 or end > hi + 0.5:
            warn(f"scene {i} is outside the part, clamped to the part range")
        got = _clean(start, end, cues, lo, hi, f"scene {i}", warn)
        if got:
            out.append(got)
    if not out:
        warn("the plan item listed no usable scenes")
    return out


def from_anchors(anchors: list[float | None], beats: list[str], cues: list[Cue],
                 lo: float, hi: float, scene_seconds: float) -> list[tuple[float, float]]:
    """One clip per beat, taken around the line the beat is built on."""
    out: list[tuple[float, float]] = []
    fallback = _bases(len(beats), scene_seconds, lo, hi)
    for i, beat in enumerate(beats):
        anchor = anchors[i] if i < len(anchors) else None
        base = anchor if anchor is not None and anchor >= 0 else fallback[i]
        got = _clean(base - LEAD, base - LEAD + scene_seconds, cues, lo, hi, "scene", _warn)
        if got:
            out.append(got)
    return out


def spread(cues: list[Cue], count: int, scene_seconds: float,
           lo: float, hi: float) -> list[tuple[float, float]]:
    """`count` usable clips spread evenly across the segment."""
    if count <= 0:
        return []
    got = (_clean(b, b + scene_seconds, cues, lo, hi, "scene", _warn)
           for b in _bases(count, scene_seconds, lo, hi))
    return [g for g in got if g]


def _bases(count: int, scene_seconds: float, lo: float, hi: float) -> list[float]:
    """Start times of `count` evenly spaced clips; the last ones may repeat."""
    step = max(scene_seconds, (hi - lo) / count)
    return [min(lo + i * step, max(lo, hi - scene_seconds)) for i in range(count)]
