"""The part model and small helpers shared by the planner and pipeline."""
from __future__ import annotations

from dataclasses import dataclass, replace

from .srt import format_timestamp


@dataclass(frozen=True)
class Part:
    index: int
    start: float
    end: float
    narration: str
    hook: str = ""
    beats: tuple[str, ...] = ()
    anchors: tuple[float, ...] = ()
    scenes: tuple[tuple[float, float], ...] = ()

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        data = {
            "part_index": self.index,
            "start_timestamp": format_timestamp(self.start),
            "end_timestamp": format_timestamp(self.end),
            "start_seconds": round(self.start, 3),
            "end_seconds": round(self.end, 3),
            "duration_seconds": round(self.duration, 3),
            "narration_script": list(self.beats) if self.beats else self.narration,
            "hook": self.hook,
            "scenes": [
                {"start_timestamp": format_timestamp(s), "end_timestamp": format_timestamp(e)}
                for s, e in self.scenes
            ],
        }
        if self.anchors and len(self.anchors) == len(self.beats) and all(
            t >= 0 for t in self.anchors
        ):
            data["narration_timestamps"] = [format_timestamp(t) for t in self.anchors]
        return data


def derive_hook(narration: str) -> str:
    """First sentence of the narration, used as the short-form hook."""
    text = " ".join(narration.split())
    for stop in (". ", "? ", "! "):
        if stop in text:
            text = text.split(stop)[0]
            break
    else:
        text = text.split(".")[0]
    return text.strip(" .,;:-—")[:120]


def renumber(parts: list[Part]) -> list[Part]:
    return [replace(p, index=i) for i, p in enumerate(parts, start=1)]
