"""Stage 3: build each part as a montage of short scene clips.

Only a few seconds of the film is used per scene, so a part is a sequence of highlights
that runs exactly as long as the narration needs.
"""
from __future__ import annotations

from pathlib import Path

from .logutil import log
from .media import run


def _video_inputs(video: Path, scenes: list[tuple[float, float]]) -> list[str]:
    args: list[str] = []
    for start, end in scenes:
        args += ["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(video)]
    return args


def _video_filter(scenes: list[tuple[float, float]]) -> str:
    parts: list[str] = []
    feeds: list[str] = []
    for i in range(len(scenes)):
        parts.append(f"[{i}:v]setpts=PTS-STARTPTS[v{i}]")
        feeds.append(f"[v{i}]")
    parts.append(f"{''.join(feeds)}concat=n={len(scenes)}:v=1:a=0[vout]")
    return ";".join(parts)


def render_montage(video: Path, scenes: list[tuple[float, float]], out: Path,
                   fps: float) -> Path:
    """Concatenate the scene clips into one silent video."""
    if not scenes:
        log("ERROR", "No scenes to render")
        raise SystemExit(1)
    total = sum(end - start for start, end in scenes)
    log("INFO", f"Montage of {len(scenes)} scene(s), {total:.1f}s total")
    cmd = ["ffmpeg", "-y", *_video_inputs(video, scenes),
           "-filter_complex", _video_filter(scenes),
           "-map", "[vout]", "-an",
           "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
           "-r", f"{fps:.3f}" if fps > 0 else "30", "-movflags", "+faststart", str(out)]
    run(cmd, desc=f"Montage {out.name}")
    return out
