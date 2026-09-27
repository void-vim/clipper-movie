"""Runtime configuration: paths and pipeline settings."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "output"
DEFAULT_FONT_DIR = PROJECT_DIR / "input" / "font"

STAGE_TOTAL = 5


@dataclass
class Settings:
    video: Path
    subtitle: Path
    output_root: Path = DEFAULT_OUTPUT_DIR
    plan_file: Path | None = None
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
    dry_run: bool = False
    debug: bool = False
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_args(cls, args) -> "Settings":
        font_dir = Path(args.font_dir) if args.font_dir else None
        if font_dir is None and DEFAULT_FONT_DIR.is_dir():
            font_dir = DEFAULT_FONT_DIR
        return cls(
            video=Path(args.video).expanduser().resolve(),
            subtitle=Path(args.subtitle).expanduser().resolve(),
            output_root=Path(args.output).expanduser().resolve(),
            plan_file=Path(args.plan).expanduser().resolve() if args.plan else None,
            min_part=args.min_part,
            max_part=args.max_part,
            device=args.device,
            tts_engine=args.tts_engine,
            ref_audio=Path(args.ref).expanduser().resolve() if args.ref else None,
            exaggeration=args.exaggeration,
            temperature=args.temperature,
            narration_delay=args.narration_delay,
            narration_words=args.narration_words,
            scene_seconds=args.scene_seconds,
            font_dir=font_dir,
            keep_going=args.keep_going,
            dry_run=args.dry_run,
            debug=args.debug,
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
