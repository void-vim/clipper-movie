"""Pipeline stages 2-5: narration, montage, mixing, export.

Every part is a montage of a few seconds of the film, cut so the montage is long enough
for the narration. The movie audio is never used: the part only carries the recap.
"""
from __future__ import annotations

import json
import math
import shutil
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from . import schedule
from .ass import ShortStyle
from .config import Settings
from .logutil import log
from .media import MediaInfo, probe
from .mixer import PlacedBeat, mux_narration, write_narration_audio
from .parts import Part
from .render import render_montage
from .scenes import UNANCHORED, from_anchors, spread
from .schedule import scene_offsets
from .shortform import render_vertical
from .srt import Cue, dump_srt, format_timestamp as srt_stamp
from .tts import BeatClip, synthesize_beats

TAIL = 0.8


@dataclass
class PartResult:
    part: Part
    folder: Path
    montage: Path
    beats_dir: Path
    narration: Path
    clips: list[BeatClip] = field(default_factory=list)
    placed: list[PlacedBeat] = field(default_factory=list)
    scenes: list[tuple[float, float]] = field(default_factory=list)
    video: Path | None = None
    short: Path | None = None
    failed: bool = False

    @property
    def duration(self) -> float:
        return max(self.scenes_total(), self.narration_end())

    def scenes_total(self) -> float:
        return sum(e - s for s, e in self.scenes)

    def narration_end(self) -> float:
        return max((p.start + p.duration for p in self.placed), default=0.0)

    def to_dict(self) -> dict:
        data = self.part.to_dict()
        data["montage_seconds"] = round(self.scenes_total(), 3)
        offsets = scene_offsets(self.scenes)
        data["montage_scenes"] = [
            {
                "source_start": srt_stamp(s),
                "source_end": srt_stamp(e),
                "montage_start": round(off, 3),
            }
            for (s, e), off in zip(self.scenes, offsets)
        ]
        data["narration_beats"] = [
            {"start_seconds": round(p.start, 3), "duration_seconds": round(p.duration, 3),
             "text": p.text}
            for p in self.placed
        ]
        files = {
            "video": self.video,
            "narration": self.narration,
            "narration_srt": self.folder / "narration.srt",
            "subtitle_srt": self.folder / "subtitle.srt",
        }
        if self.short:
            files["short"] = self.short
        data["files"] = {k: Path(v).name for k, v in files.items()}
        return data


def part_folder(work_dir: Path, index: int) -> Path:
    folder = work_dir / f"part_{index:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@contextmanager
def tolerate(settings: Settings, label: str):
    """Swallow a per-part failure only when --keep-going is set."""
    try:
        yield
    except SystemExit:
        if not settings.keep_going:
            raise
        log("ERROR", f"{label} failed; skipping it because --keep-going is set")


def new_results(plan: list[Part], work_dir: Path) -> list[PartResult]:
    out: list[PartResult] = []
    tmp = work_dir / ".tmp"
    for p in plan:
        folder = part_folder(work_dir, p.index)
        out.append(PartResult(
            part=p, folder=folder, montage=tmp / f"montage_{p.index:02d}.mp4",
            beats_dir=tmp / f"beats_{p.index:02d}",
            narration=folder / "narration.mp3",
        ))
    return out


def generate_narrations(results: list[PartResult], cues: list[Cue],
                          settings: Settings) -> None:
    """Stage 2: one audio file per beat, then fit the montage around the narration."""
    for i, r in enumerate(results, start=1):
        log("INFO", f"Part {i}/{len(results)}: part_{r.part.index:02d} narration")
        with tolerate(settings, f"part_{r.part.index:02d} narration"):
            beats = list(r.part.beats) or [r.part.narration]
            r.clips = synthesize_beats(
                beats, r.beats_dir, engine=settings.tts_engine, device=settings.device,
                ref=settings.ref_audio, exaggeration=settings.exaggeration,
                temperature=settings.temperature,
            )
            _fit_scenes(r, cues, settings)
            write_narration_audio(r.placed, r.narration, r.duration)
        r.failed = not r.clips
        if not r.failed:
            _report(r)


def _fit_scenes(result: PartResult, cues: list[Cue], settings: Settings) -> None:
    """Line up the beats with the scene clips, adding or repeating clips to fill."""
    beats = [c.text for c in result.clips]
    durations = [c.duration for c in result.clips]
    listed = list(result.part.scenes)
    placed = schedule.place(beats, durations, listed, settings.narration_delay)
    needed = schedule.total_length(placed, settings.narration_delay, TAIL)
    have = sum(e - s for s, e in listed)
    if have < needed:
        listed = _add_scenes(result, cues, listed, settings, needed)
    scenes = schedule.fit(listed, needed)
    if scenes != result.part.scenes:
        placed = schedule.place(beats, durations, scenes, settings.narration_delay)
    result.scenes = scenes
    result.placed = [PlacedBeat(p.text, c.path, p.start, p.duration)
                     for p, c in zip(placed, result.clips)]


def _add_scenes(result: PartResult, cues: list[Cue], listed: list[tuple[float, float]],
                settings: Settings, needed: float) -> list[tuple[float, float]]:
    """Add unused scene clips from the part until the montage can hold the narration."""
    part = result.part
    window = [c for c in cues if c.end > part.start and c.start < part.end]
    anchors = list(part.anchors) if len(part.anchors) == len(part.beats) else []
    if not anchors:
        anchors = [UNANCHORED] * len(part.beats)
    out = list(listed)
    for _ in range(4):
        have = sum(e - s for s, e in out)
        if have >= needed:
            break
        # Snapped clips are often a little shorter than asked for, so ask for extra.
        want = math.ceil((needed - have) / max(0.5, settings.scene_seconds)) + 2
        pool = from_anchors(anchors, list(part.beats), window, part.start, part.end,
                            settings.scene_seconds)
        pool += spread(window, want, settings.scene_seconds, part.start, part.end)
        fresh = [s for s in pool if s not in out]
        if not fresh:
            break
        out.extend(fresh)
    log("INFO", f"  part_{part.index:02d} scenes: {len(listed)} listed, "
                f"{len(out)} used for a {needed:.0f}s narration")
    return out


def _report(result: PartResult) -> None:
    starts = ", ".join(f"{p.start:.0f}s" for p in result.placed)
    log("INFO", f"  part_{result.part.index:02d}: {len(result.scenes)} scene(s) "
                f"({result.scenes_total():.0f}s), {len(result.placed)} beats at {starts}")


def render_parts(results: list[PartResult], settings: Settings, info: MediaInfo) -> None:
    """Stage 3: build the montage of every part."""
    for i, r in enumerate(results, start=1):
        if r.failed:
            continue
        log("INFO", f"Part {i}/{len(results)}: {len(r.scenes)} scene clip(s) "
                    f"-> {r.scenes_total():.1f}s")
        with tolerate(settings, f"part_{r.part.index:02d} montage"):
            r.montage.parent.mkdir(parents=True, exist_ok=True)
            render_montage(settings.video, r.scenes, r.montage, info.fps)
        r.failed = r.failed or not r.montage.is_file()


def mix_parts(results: list[PartResult], settings: Settings) -> None:
    """Stage 4: drop the movie audio and lay the beats on the montage."""
    for r in results:
        if r.failed:
            continue
        video = r.folder / "video.mp4"
        with tolerate(settings, f"part_{r.part.index:02d} mix"):
            mux_narration(r.montage, r.placed, video, duration=r.duration)
            r.video = video
        r.failed = r.failed or r.video is None
    for r in results:
        shutil.rmtree(r.beats_dir, ignore_errors=True)
        r.montage.unlink(missing_ok=True)
    if results:
        shutil.rmtree(results[0].montage.parent, ignore_errors=True)


def write_subtitles(results: list[PartResult], cues: list[Cue]) -> None:
    """Stage 4b: the scene subtitles, rebased, plus one caption per narration beat."""
    for r in results:
        if r.failed:
            continue
        movie = schedule.cues_for_scenes(cues, r.scenes)
        (r.folder / "subtitle.srt").write_text(dump_srt(movie), encoding="utf-8")
        captions = [Cue(p.start, min(r.duration, p.start + p.duration), p.text)
                    for p in r.placed]
        captions = [c for c in captions if c.end - c.start > 0.05]
        (r.folder / "narration.srt").write_text(dump_srt(captions), encoding="utf-8")
        log("INFO", f"  part_{r.part.index:02d} subtitles: {len(movie)} movie, "
                    f"{len(captions)} narration")


def render_shorts(results: list[PartResult], settings: Settings) -> None:
    """Stage 5: 9:16 versions with a hook and large subtitles."""
    for r in results:
        if r.failed:
            continue
        assert r.video is not None
        captions = [Cue(p.start, p.start + p.duration, p.text) for p in r.placed]
        with tolerate(settings, f"part_{r.part.index:02d} vertical render"):
            r.short = render_vertical(
                r.video, r.folder / "short.mp4", captions, r.part.hook,
                duration=r.duration, font_dir=settings.font_dir, style=ShortStyle(),
            )


def write_manifest(settings: Settings, results: list[PartResult], info: MediaInfo) -> Path:
    payload = {
        "source": {
            "video": str(settings.video), "subtitle": str(settings.subtitle),
            "duration_seconds": round(info.duration, 3), "width": info.width,
            "height": info.height, "fps": round(info.fps, 3),
        },
        "mode": "short",
        "tts_engine": settings.tts_engine,
        "narration_delay_seconds": settings.narration_delay,
        "scene_seconds": settings.scene_seconds,
        "parts": [r.to_dict() for r in results],
        "warnings": settings.warnings,
    }
    path = settings.work_dir / "manifest.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def verify(results: list[PartResult]) -> None:
    failed = [r for r in results if r.failed]
    if failed:
        names = ", ".join(f"part_{r.part.index:02d}" for r in failed)
        log("ERROR", f"{len(failed)} part(s) failed: {names}")
    for r in results:
        if r.failed or r.video is None:
            continue
        if not r.video.is_file() or r.video.stat().st_size == 0:
            log("ERROR", f"Missing or empty output video: {r.video}")
            raise SystemExit(1)
        got = probe(r.video).duration
        if abs(got - r.duration) > 1.5:
            log("WARN", f"{r.video.name} is {got:.1f}s, expected {r.duration:.1f}s")
