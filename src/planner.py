"""Stage 1: build the part plan, either from a JSON file or from subtitle structure."""
from __future__ import annotations

import json
from pathlib import Path

from . import heuristic, scenes
from .scenes import UNANCHORED
from .config import Settings
from .logutil import log
from .narrator import write_recap
from .parts import Part, derive_hook, renumber
from .srt import Cue, format_timestamp, nearest, parse_srt, parse_timestamp
from .tts import split_script

GAP_TOLERANCE = 0.2
MAX_CLOSE_GAP = 20.0
SNAP_TOLERANCE = 2.0


def target_length(settings: Settings) -> float:
    return max(settings.min_part, min(settings.max_part, (settings.min_part + settings.max_part) / 2))


def _warn(settings: Settings, message: str) -> None:
    settings.warnings.append(message)
    log("WARN", message)


MIN_PLAN_PART = 10.0


def _report_drift(parts: list[Part], settings: Settings, automatic: bool) -> None:
    """Length only matters for the automatic segmentation; a plan decides for itself."""
    for p in parts:
        if not automatic:
            if p.duration < MIN_PLAN_PART:
                _warn(settings, f"Part {p.index} is only {p.duration:.0f}s long")
            continue
        if p.duration < settings.min_part or p.duration > settings.max_part:
            _warn(settings, f"Part {p.index} is {p.duration:.0f}s, outside "
                            f"{settings.min_part:.0f}-{settings.max_part:.0f}s (scene-change cut)")


def _report(parts: list[Part]) -> None:
    total = sum(p.duration for p in parts)
    log("INFO", f"Planned {len(parts)} parts, total {total / 60:.1f} min")
    for p in parts:
        log("INFO", (
            f"  part_{p.index:02d} {format_timestamp(p.start)} -> {format_timestamp(p.end)} "
            f"({p.duration:.0f}s, {len(p.narration.split())} narration words) | {p.summary[:70]}"
        ))


def plan(settings: Settings, duration: float) -> list[Part]:
    """Cut the film on dialogue boundaries and write a recap for every part."""
    cues = parse_srt(settings.subtitle)
    if duration <= 0:
        duration = cues[-1].end
    log("INFO", f"Parsed {len(cues)} subtitle cues spanning {duration / 60:.1f} minutes")
    if settings.plan_file:
        parts = load_plan(settings.plan_file, cues, duration, settings)
    else:
        target = target_length(settings)
        log("INFO", f"Segmenting on dialogue boundaries, target {target:.0f}s per part")
        parts = heuristic.to_parts(
            cues, duration, settings.min_part, settings.max_part, target,
            settings.narration_words, settings.scene_seconds,
        )
    if not parts:
        log("ERROR", "Subtitles are too sparse to build any part")
        raise SystemExit(1)
    _report_drift(parts, settings, automatic=not settings.plan_file)
    _report(parts)
    return parts


def _read_plan(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        log("ERROR", f"Cannot read plan file: {exc}")
        raise SystemExit(1)
    except json.JSONDecodeError as exc:
        log("ERROR", f"Invalid JSON in {path}: {exc}")
        raise SystemExit(1)
    if isinstance(data, dict):
        data = data.get("parts", [])
    if not isinstance(data, list) or not data:
        log("ERROR", f"Plan file must hold a non-empty JSON array of parts: {path}")
        raise SystemExit(1)
    return [d for d in data if isinstance(d, dict)]


def _time(item: dict, key: str, seconds_key: str) -> float | None:
    raw = item.get(key, item.get(seconds_key))
    if raw is None or str(raw).strip() == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    return parse_timestamp(str(raw))


def _snap(value: float, targets: list[float], label: str, prefer: str, warn) -> float:
    hit = nearest(value, targets, SNAP_TOLERANCE, prefer)
    if hit is None:
        warn(f"{label} {format_timestamp(value)} has no subtitle cue within "
             f"{SNAP_TOLERANCE:g}s, using it as given")
        return round(value, 3)
    return round(hit, 3)


def _beats(item: dict, position: int, window: list[Cue],
           settings: Settings) -> tuple[list[str], str, list[float | None] | None]:
    """Read narration_script as an array of beats; a plain string is split up."""
    raw = item.get("narration_script")
    if isinstance(raw, list):
        beats = [" ".join(str(b).split()) for b in raw]
        beats = [b for b in beats if b]
        if beats:
            return beats, " ".join(beats), _timestamps(item, len(beats))
        warn_msg = f"Part {position} has an empty narration_script array, rewriting it"
        log("WARN", warn_msg)
    elif isinstance(raw, str) and raw.strip():
        beats = split_script(raw)
        return beats, " ".join(beats), _timestamps(item, len(beats))
    summary, generated = write_recap(window, position, settings.narration_words)
    texts = [t for t, _ in generated]
    return texts, summary or " ".join(texts), [a for _, a in generated]


def _timestamps(item: dict, count: int) -> list[float | None] | None:
    """Read the optional narration_timestamps array."""
    raw = item.get("narration_timestamps")
    if not isinstance(raw, list) or not raw:
        return None
    values = [_value(r) for r in raw[:count]]
    if len(values) < count:
        return None
    log("INFO", f"Read {len(values)} narration timestamps from the plan")
    return values


def _value(raw: object) -> float | None:
    if raw is None or str(raw).strip() == "":
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    try:
        return parse_timestamp(str(raw))
    except ValueError:
        return None


def _scenes(item: dict, position: int, cues: list[Cue], start: float, end: float,
            beats: list[str], anchors: list[float | None] | None,
            settings: Settings, warn) -> list[tuple[float, float]]:
    """The short clips this part shows: from the plan, or from the narration lines."""
    window = [c for c in cues if c.end > start and c.start < end]
    if isinstance(item.get("scenes"), list) and item["scenes"]:
        listed = scenes.parse(item["scenes"], cues, start, end, warn)
        if listed:
            return listed
    lines = anchors if anchors is not None else [None] * len(beats)
    return scenes.from_anchors(lines, beats, window, start, end, settings.scene_seconds)


def _stage(item: dict, position: int, cues: list[Cue], duration: float,
           settings: Settings, warn) -> Part | None:
    start = _time(item, "start_timestamp", "start_seconds")
    end = _time(item, "end_timestamp", "end_seconds")
    if start is None or end is None:
        warn(f"Part {position} has no start/end timestamp, dropped")
        return None
    if end <= start:
        warn(f"Part {position} ends before it starts, dropped")
        return None
    start = _snap(max(0.0, min(start, duration)), [c.start for c in cues], "start", "ceil", warn)
    end = _snap(min(end, duration), [c.end for c in cues], "end", "floor", warn)
    if end - start <= 0.05:
        warn(f"Part {position} has a zero length after snapping, dropped")
        return None
    window = [c for c in cues if c.end > start and c.start < end]
    beats, narration, anchors = _beats(item, position, window, settings)
    summary = str(item.get("summary", "")).strip() or narration.split(".")[0].strip()
    hook = str(item.get("hook", "")).strip() or derive_hook(summary)
    clips = _scenes(item, position, cues, start, end, beats, anchors, settings, warn)
    if not clips:
        warn(f"Part {position} has no scene to show, dropped")
        return None
    return Part(index=position, start=start, end=end, summary=summary,
                narration=narration, hook=hook, beats=tuple(beats),
                anchors=tuple(UNANCHORED if a is None else a for a in (anchors or [])),
                scenes=tuple(clips))


def _order(parts: list[Part]) -> list[Part]:
    """Sort by start time and renumber. Nothing else: parts render on their own."""
    return renumber(sorted(parts, key=lambda p: (p.start, p.end)))


def _report_overlaps(parts: list[Part], settings: Settings) -> None:
    for prev, cur in zip(parts, parts[1:]):
        if cur.start < prev.end - 0.001:
            log("INFO", f"Part {cur.index} starts at {format_timestamp(cur.start)}, inside "
                        f"part {prev.index}; both are rendered separately")
        elif cur.start - prev.end > MAX_CLOSE_GAP:
            log("INFO", f"Part {prev.index} to {cur.index} leaves "
                        f"{(cur.start - prev.end) / 60:.1f} min of film unused, "
                        f"which is allowed")


def load_plan(path: Path, cues: list[Cue], duration: float, settings: Settings) -> list[Part]:
    """Build the plan from a user-supplied JSON array of parts."""
    def warn(message: str) -> None:
        _warn(settings, message)

    entries = _read_plan(path)
    log("INFO", f"Reading {len(entries)} parts from {path}")
    staged: list[Part] = []
    for i, entry in enumerate(entries, start=1):
        part = _stage(entry, i, cues, duration, settings, warn)
        if part is not None:
            staged.append(part)
    if len(staged) < len(entries):
        _warn(settings, f"{len(entries) - len(staged)} of {len(entries)} plan items were "
                        f"unusable and are not in the output")
    parts = _order(staged)
    if not parts:
        log("ERROR", f"Plan file produced no usable parts: {path}")
        raise SystemExit(1)
    _report_overlaps(parts, settings)
    return parts
