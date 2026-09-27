"""Runtime configuration: paths and pipeline settings."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "output"
DEFAULT_FONT_DIR = PROJECT_DIR / "input" / "font"
PLAN_FILE = PROJECT_DIR / "plan.json"

STAGE_TOTAL = 5


@dataclass
class Settings:
    video: Path
    subtitle: Path
    output_root: Path = DEFAULT_OUTPUT_DIR
    plan_file: Path | None = PLAN_FILE if PLAN_FILE.is_file() else None
    min_part: float = 60.0
    max_part: float = 300.0
    device: str = "cpu"
    tts_engine: str = "chatterbox"
    ref_audio: Path | None = None
    exaggeration: float = 0.5
    temperature: float = 0.8
    narration_delay: float = 1.0
    narration_words: int = 200
    scene_seconds: float = 3.0
    font_dir: Path | None = None
    keep_going: bool = False
    debug: bool = False
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_args(cls, args) -> "Settings":
        return cls(
            video=Path(args.video).expanduser().resolve(),
            subtitle=Path(args.subtitle).expanduser().resolve(),
            font_dir=DEFAULT_FONT_DIR if DEFAULT_FONT_DIR.is_dir() else None,
        )

    @property
    def work_dir(self) -> Path:
        """Where the parts are written: the output directory itself, no extra level."""
        return self.output_root

    def other_movie_in_output(self) -> str | None:
        """The video a manifest already in the output directory belongs to, if any."""
        path = self.output_root / "manifest.json"
        if not path.is_file():
            return None
        try:
            source = json.loads(path.read_text(encoding="utf-8")).get("source", {})
        except (OSError, ValueError):
            return None
        video = source.get("video")
        if not video or Path(video) == self.video:
            return None
        return video
