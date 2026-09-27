"""ffmpeg / ffprobe process helpers."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .logutil import log


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool


def require_tools() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            log("ERROR", f"{tool} not found in PATH")
            raise SystemExit(1)


def _parse_fps(value: str | None) -> float:
    if not value or "/" not in value:
        return 0.0
    num, _, den = value.partition("/")
    try:
        den_f = float(den)
        return float(num) / den_f if den_f else 0.0
    except ValueError:
        return 0.0


def probe(path: str | Path) -> MediaInfo:
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_streams", "-show_format", str(path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        log("ERROR", f"ffprobe failed for {path}: {res.stderr.strip()[-500:]}")
        raise SystemExit(1)
    data = json.loads(res.stdout or "{}")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    duration = _first_float(data.get("format", {}).get("duration"))
    if not duration and video:
        duration = _first_float(video.get("duration"))
    if video is None:
        log("ERROR", f"No video stream found in {path}")
        raise SystemExit(1)
    return MediaInfo(
        duration=duration or 0.0,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=_parse_fps(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        has_audio=has_audio,
    )


def _first_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def try_run(args: list[str]) -> tuple[int, str]:
    """Run an ffmpeg command, returning (exit code, stderr) without raising."""
    log("DEBUG", "ffmpeg " + " ".join(args))
    res = subprocess.run(args, capture_output=True, text=True)
    return res.returncode, res.stderr.strip()


def run(args: list[str], *, desc: str, tail: int = 2000) -> None:
    """Run an ffmpeg command, logging and exiting on failure."""
    code, stderr = try_run(args)
    if code != 0:
        log("ERROR", f"{desc} failed with exit code {code}")
        log("ERROR", stderr[-tail:])
        raise SystemExit(1)
    if stderr:
        log("DEBUG", f"{desc} stderr: {stderr[-400:]}")
