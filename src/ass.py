"""ASS subtitle builder for the 9:16 short-form render."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .logutil import log
from .srt import Cue

FONT_NAME = "Coolvetica"
SUB_SIZE = 55
HOOK_SIZE = 60
HOOK_TOP_MARGIN = 140
SUB_BOTTOM_MARGIN = 520
MAX_LINE_CHARS = 30

HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font},{sub_size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H64000000,-1,0,0,0,100,100,0,0,1,7,2,2,90,90,{sub_margin},1
Style: Hook,{font},{hook_size},&H0000FFFF,&H0000FFFF,&H00101010,&H00000000,-1,0,0,0,100,100,0,0,1,11,3,8,60,60,{hook_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


@dataclass(frozen=True)
class ShortStyle:
    width: int = 1080
    height: int = 1920
    sub_size: int = SUB_SIZE
    hook_size: int = HOOK_SIZE
    # How long one hook card stays on screen; the next one takes over right after.
    hook_seconds: float = 4.0
    hook_top_margin: int = HOOK_TOP_MARGIN
    sub_bottom_margin: int = SUB_BOTTOM_MARGIN
    max_line_chars: int = MAX_LINE_CHARS


def ass_time(seconds: float) -> str:
    sec = max(0.0, float(seconds))
    cs = int(round((sec - int(sec)) * 100))
    if cs >= 100:
        cs = 99
    return f"{int(sec // 3600):d}:{int(sec % 3600 // 60):02d}:{int(sec % 60):02d}.{cs:02d}"


def escape(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")).strip()


def wrap_text(text: str, max_chars: int) -> str:
    lines, current = [], ""
    for word in escape(text).split():
        while len(word) > max_chars:
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:max_chars])
            word = word[max_chars:]
        if current and len(current) + 1 + len(word) > max_chars:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return r"\N".join(lines[:3])


def _hook_events(hook: str, style: ShortStyle, duration: float) -> list[str]:
    """The hook as a chain of events, each one repeating for the whole video."""
    text = wrap_text(hook.upper(), style.max_line_chars + 4)
    step = max(0.5, style.hook_seconds)
    if duration <= 0:
        return [f"Dialogue: 1,0:00:00.00,{ass_time(step)},Hook,,0,0,0,,{text}"]
    events: list[str] = []
    start = 0.0
    while start < duration:
        end = min(duration, start + step)
        events.append(
            f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Hook,,0,0,0,,{text}"
        )
        start += step
    return events


def _sub_events(cues: list[Cue], style: ShortStyle) -> list[str]:
    events: list[str] = []
    for cue in cues:
        if cue.end <= 0 or cue.start < 0:
            continue
        text = wrap_text(cue.text, style.max_line_chars)
        events.append(
            f"Dialogue: 0,{ass_time(cue.start)},{ass_time(cue.end)},"
            f"Sub,,0,0,0,,{text}"
        )
    return events


def build_short_ass(
    path: Path, cues: list[Cue], hook: str, duration: float,
    style: ShortStyle | None = None,
) -> Path:
    """Write an ASS file with a hook banner plus large narration subtitles."""
    style = style or ShortStyle()
    header = HEADER.format(
        width=style.width, height=style.height, font=FONT_NAME,
        sub_size=style.sub_size, hook_size=style.hook_size,
        sub_margin=style.sub_bottom_margin, hook_margin=style.hook_top_margin,
    )
    events: list[str] = []
    if hook:
        events.extend(_hook_events(hook, style, duration))
    events.extend(_sub_events(cues, style))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    log("INFO", f"Wrote {path.name} with {len(events)} events")
    return path
