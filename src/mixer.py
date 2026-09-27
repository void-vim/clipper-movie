"""Stage 4: put the narration on a part, with the movie audio dropped.

The montage carries no audio, so the track is built from a silent base plus one delayed
copy of every narration beat.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .logutil import log
from .media import run

SAMPLE_RATE = 48000
LAYOUT = f"sample_fmts=fltp:sample_rates={SAMPLE_RATE}:channel_layouts=stereo"


@dataclass
class PlacedBeat:
    text: str
    path: Path
    start: float
    duration: float

    @property
    def end(self) -> float:
        return self.start + self.duration


def _graph(duration: float, clips: list[tuple[Path, float]], base: int) -> str:
    """Mix the delayed beats into a silent track; beat k comes from input base + k."""
    parts = [f"anullsrc=r={SAMPLE_RATE}:cl=stereo:d={duration:.3f}[silence]"]
    for i, (_, offset) in enumerate(clips):
        label = f"b{i + 1}"
        # adelay needs `all=1`: a bare value only delays the first channel, which
        # would leave the beat audible undelayed in the other one.
        parts.append(f"[{base + i}:a]aformat={LAYOUT},"
                     f"adelay={int(offset * 1000)}:all=1[{label}]")
    feeds = "".join(f"[b{i + 1}]" for i in range(len(clips)))
    parts.append(f"[silence]{feeds}amix=inputs={len(clips) + 1}"
                 f":duration=first:dropout_transition=0:normalize=0[aout]")
    return ";".join(parts)


def mux_narration(video: Path, placed: list[PlacedBeat], out: Path, *,
                  duration: float) -> Path:
    """Attach the scheduled narration to a silent part, copying the video stream."""
    if not placed:
        log("ERROR", f"No narration to attach to {out.name}")
        raise SystemExit(1)
    clips = [(p.path, p.start) for p in placed]
    log("INFO", f"Muxing {len(clips)} narration beats into a {duration:.1f}s part")
    cmd = ["ffmpeg", "-y", "-i", str(video)]
    for path, _ in clips:
        cmd += ["-i", str(path)]
    cmd += [
        "-filter_complex", _graph(duration, clips, 1),
        "-map", "0:v:0", "-map", "[aout]", "-map_metadata", "-1",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", str(SAMPLE_RATE),
        "-ac", "2", "-t", f"{duration:.3f}", "-movflags", "+faststart", str(out),
    ]
    run(cmd, desc=f"Narration mix {out.name}")
    return out


def write_narration_audio(placed: list[PlacedBeat], out_mp3: Path,
                          duration: float) -> Path:
    """Standalone MP3 of the scheduled narration, for listening on its own."""
    cmd = ["ffmpeg", "-y"]
    for p in placed:
        cmd += ["-i", str(p.path)]
    cmd += ["-filter_complex",
            _graph(duration, [(p.path, p.start) for p in placed], 0),
            "-map", "[aout]", "-c:a", "libmp3lame", "-q:a", "2", str(out_mp3)]
    run(cmd, desc=f"Narration track {out_mp3.name}")
    return out_mp3
