"""Stage 7: 9:16 vertical reframe with a hook and large burned-in subtitles."""
from __future__ import annotations

from pathlib import Path

from .ass import ShortStyle, build_short_ass
from .logutil import log
from .media import run
from .srt import Cue

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
# Fraction of the source width kept, taken from the center.
CROP_FRACTION = 0.5


def escape_filter_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def build_chain(ass_path: Path, font_dir: Path | None, style: ShortStyle) -> str:
    # Keep the center half of the frame, then fit it into 9:16 and pad with black
    # whatever is left, so the picture stays centered and never gets distorted.
    crop = f"crop=iw*{CROP_FRACTION}:ih:(iw-ow)/2:0"
    scale = (f"scale={style.width}:{style.height}"
             f":force_original_aspect_ratio=decrease:flags=lanczos")
    pad = f"pad={style.width}:{style.height}:(ow-iw)/2:(oh-ih)/2:color=black"
    chain = f"[0:v]{crop},{scale},{pad}"
    ass = escape_filter_path(ass_path)
    if font_dir and font_dir.is_dir():
        chain += f",ass={ass}:fontsdir={escape_filter_path(font_dir)}"
    else:
        if font_dir:
            log("WARN", f"Font directory not found ({font_dir}); using system fonts")
        chain += f",ass={ass}"
    return chain + ",format=yuv420p[v]"


def render_vertical(
    source: Path, out: Path, cues: list[Cue], hook: str, *, duration: float,
    font_dir: Path | None, style: ShortStyle | None = None,
) -> Path:
    """Re-render a finished part as a vertical short with burned-in captions."""
    style = style or ShortStyle()
    ass_path = out.with_suffix(".short.ass")
    build_short_ass(ass_path, cues, hook, duration, style)
    cmd = [
        "ffmpeg", "-y", "-i", str(source),
        "-filter_complex", build_chain(ass_path, font_dir, style),
        "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-crf", "20",
        "-preset", "medium", "-r", "30", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(out),
    ]
    run(cmd, desc=f"Vertical render {out.name}")
    ass_path.unlink(missing_ok=True)
    log("INFO", f"Short-form video ready: {out}")
    return out
