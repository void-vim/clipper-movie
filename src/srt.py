"""SRT parsing, formatting, slicing and timestamp snapping."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .logutil import log

CUE_RE = re.compile(
    r"(?P<h>\d{1,3}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{1,3})\s*-->"
    r"\s*(?P<h2>\d{1,3}):(?P<m2>\d{2}):(?P<s2>\d{2})[,.](?P<ms2>\d{1,3})"
)
SHORT_RE = re.compile(r"^(?P<m>\d{1,3}):(?P<s>\d{2})(?:[,.](?P<ms>\d{1,3}))?$")
TAG_RE = re.compile(r"<[^>]+>|\{\\[^}]*\}")


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


class SrtError(ValueError):
    pass


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", TAG_RE.sub("", text)).strip()


def _hms(h: str, m: str, s: str, ms: str | None) -> float:
    frac = int(((ms or "0") + "000")[:3])
    return int(h) * 3600 + int(m) * 60 + int(s) + frac / 1000.0


def parse_timestamp(value: str) -> float:
    """Parse `HH:MM:SS,mmm`, `HH:MM:SS.mmm`, `MM:SS` or bare seconds."""
    raw = str(value).strip().strip("[]")
    if "-->" in raw:
        m = CUE_RE.search(raw)
        if m:
            return _hms(m["h"], m["m"], m["s"], m["ms"])
    if re.fullmatch(r"\d+(\.\d+)?", raw):
        return float(raw)
    hm = re.fullmatch(r"(\d{1,3}):(\d{2}):(\d{2})(?:[,.](\d{1,3}))?", raw)
    if hm:
        return _hms(hm[1], hm[2], hm[3], hm[4])
    sm = SHORT_RE.match(raw)
    if sm:
        return _hms("0", sm["m"], sm["s"], sm["ms"])
    raise SrtError(f"[ERROR] Cannot parse timestamp: {value!r}")


def format_timestamp(seconds: float) -> str:
    sec = max(0.0, float(seconds))
    total_ms = int(round(sec * 1000))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(path: str | Path) -> list[Cue]:
    raw = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        idx = next((i for i, ln in enumerate(lines) if CUE_RE.search(ln)), None)
        if idx is None:
            log("WARN", f"Skipping malformed SRT block: {lines[0][:60]}")
            continue
        m = CUE_RE.search(lines[idx])
        if m is None:
            continue
        start = _hms(m["h"], m["m"], m["s"], m["ms"])
        end = _hms(m["h2"], m["m2"], m["s2"], m["ms2"])
        text = clean_text(" ".join(lines[idx + 1:]))
        if not text or end <= start:
            continue
        cues.append(Cue(start, end, text))
    cues.sort(key=lambda c: c.start)
    if not cues:
        raise SrtError(f"[ERROR] No valid cues parsed from {path}")
    return cues


def dump_srt(cues: list[Cue]) -> str:
    blocks = [
        f"{i}\n{format_timestamp(c.start)} --> {format_timestamp(c.end)}\n{c.text}"
        for i, c in enumerate(cues, start=1)
    ]
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def slice_cues(cues: list[Cue], start: float, end: float) -> list[Cue]:
    """Clip cues to [start, end] and rebase their times to zero."""
    out: list[Cue] = []
    for cue in cues:
        if cue.end <= start or cue.start >= end:
            continue
        s = max(cue.start, start) - start
        e = min(cue.end, end) - start
        if e - s < 0.05:
            continue
        out.append(Cue(round(s, 3), round(e, 3), cue.text))
    return out


def nearest(value: float, candidates: list[float], tolerance: float,
             prefer: str = "nearest") -> float | None:
    """Closest candidate within tolerance, else None.

    `prefer` biases the choice: "ceil" snaps forward, "floor" snaps backward.
    """
    inside = [c for c in candidates if abs(c - value) <= tolerance]
    if not inside:
        return None
    if prefer == "ceil":
        forward = [c for c in inside if c >= value - 0.001]
        return min(forward) if forward else max(inside)
    if prefer == "floor":
        back = [c for c in inside if c <= value + 0.001]
        return max(back) if back else min(inside)
    return min(inside, key=lambda c: abs(c - value))


def next_cue_start(cues: list[Cue], after: float) -> float | None:
    for c in cues:
        if c.start >= after - 0.001:
            return c.start
    return None
