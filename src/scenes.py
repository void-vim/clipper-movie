"""Pick the scene clips a part shows.

One clip per narration beat, and the clip is cut as long as its beat takes to speak, so
the picture always changes on the line the narrator is saying. The plan says where a
clip starts; the length is decided here, after the beat timings are known.
"""
from __future__ import annotations

from .logutil import log
from .srt import Cue, nearest, parse_timestamp

SNAP_TOLERANCE = 2.0
MIN_SCENE = 0.8
# Placeholder for a plan scene that lists no end; the real length comes from the beat.
HINT_LENGTH = 3.0
LEAD = 0.3
UNANCHORED = -1.0
WORDS_PER_SECOND = 2.6


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


def _sizes(lengths: float | list[float], count: int) -> list[float]:
    """One clip length per beat; a single number is used for all of them."""
    if count <= 0:
        return []
    if isinstance(lengths, (int, float)):
        return [max(MIN_SCENE, float(lengths))] * count
    values = [max(MIN_SCENE, float(x)) for x in list(lengths)[:count]]
    return values + [values[-1] if values else MIN_SCENE] * (count - len(values))


def _clip(start: float, length: float, cues: list[Cue], lo: float, hi: float) -> tuple[float, float]:
    """Snap a clip start to a subtitle line, then cut it exactly `length` long.

    The end is never snapped: a clip that loses a fraction of a second pushes every
    later beat off its scene, which is exactly what must not happen.
    """
    start = _snap(max(lo, min(start, hi)), [c.start for c in cues], "ceil")
    if start + length > hi and hi - lo >= length:
        start = max(lo, hi - length)  # the part ends first: pull the clip earlier
    end = round(min(hi, start + length), 3)
    if end - start < MIN_SCENE:
        end = min(hi, round(start + max(length, MIN_SCENE), 3))
        start = max(lo, round(end - max(length, MIN_SCENE), 3))
    return start, end


def beat_lengths(durations: list[float], pad: float, min_len: float, max_len: float,
                 tail: float = 0.0) -> list[float]:
    """Clip length per beat: as long as the beat speaks, plus a little air after it.

    `tail` is the silence the part needs after the last beat, added to the last clip so
    the montage can hold the whole narration without a repeated clip.
    """
    out: list[float] = []
    for i, duration in enumerate(durations):
        want = max(0.0, duration) + pad
        if i == len(durations) - 1:
            want += max(0.0, tail - pad)
        out.append(round(min(max(want, min_len), max_len), 3))
    return out


def estimate_lengths(beats: list[str], pad: float, min_len: float,
                     max_len: float) -> list[float]:
    """Clip length per beat before any audio exists, guessed from the words of the beat."""
    guess = [len(b.split()) / WORDS_PER_SECOND for b in beats]
    return beat_lengths(guess, pad, min_len, max_len)


def parse(items: object, cues: list[Cue], lo: float, hi: float, warn) -> list[tuple[float, float]]:
    """Read the `scenes` array of a plan item, keeping only usable clips.

    Only the start of a scene matters: the end is a hint, and the clip is cut to the
    length of the beat it carries once the beat timings are known.
    """
    if not isinstance(items, list):
        warn("scenes must be an array of start/end pairs, the plan scenes were ignored")
        return []
    out: list[tuple[float, float]] = []
    for i, entry in enumerate(items, start=1):
        raw_start, raw_end = _pair(entry)
        start = _value(raw_start)
        if start is None:
            warn(f"scene {i} has no readable start, dropped")
            continue
        end = _value(raw_end)
        if end is None:
            end = start + HINT_LENGTH
        elif end <= start:
            warn(f"scene {i} ends before it starts, dropped")
            continue
        if start < lo - 0.5 or end > hi + 0.5:
            warn(f"scene {i} is outside the part, clamped to the part range")
        got = _clip(start, end - start, cues, lo, hi)
        if got[1] - got[0] < MIN_SCENE:
            warn(f"scene {i} is only {got[1] - got[0]:.1f}s inside the part, dropped")
            continue
        out.append(got)
    if not out:
        warn("the plan item listed no usable scenes")
    return out


def from_anchors(anchors: list[float | None], beats: list[str], cues: list[Cue],
                 lo: float, hi: float, lengths: float | list[float],
                 starts: list[tuple[float, float]] | None = None) -> list[tuple[float, float]]:
    """One clip per beat, so beat i keeps landing on clip i.

    The clip starts at the listed scene when the plan gave one, otherwise just before
    the line the beat is built on, otherwise spread evenly over the part.
    """
    sizes = _sizes(lengths, len(beats))
    listed = list(starts or [])
    fallback = _bases(len(beats), sizes, lo, hi)
    out: list[tuple[float, float]] = []
    for i, size in enumerate(sizes):
        base = listed[i][0] if i < len(listed) else None
        if base is None:
            anchor = anchors[i] if i < len(anchors) else None
            base = anchor if anchor is not None and anchor >= 0 else fallback[i]
        start, end = _clip(base - LEAD, size, cues, lo, hi)
        if end - start < MIN_SCENE:
            start, end = round(lo, 3), round(lo + size, 3)
            _warn(f"scene {i + 1} had no room in the part, taken from its start")
        out.append((start, end))
    return out


def spread(cues: list[Cue], count: int, lengths: float | list[float],
           lo: float, hi: float) -> list[tuple[float, float]]:
    """`count` usable clips spread evenly across the segment."""
    sizes = _sizes(lengths, count)
    if not sizes:
        return []
    return [_clip(base, size, cues, lo, hi)
            for base, size in zip(_bases(count, sizes, lo, hi), sizes)]


def _bases(count: int, sizes: list[float], lo: float, hi: float) -> list[float]:
    """Start times of `count` evenly spaced clips; the last ones may repeat."""
    step = max(max(sizes), (hi - lo) / count) if sizes else 0.0
    return [min(lo + i * step, max(lo, hi - sizes[i])) for i in range(count)]
