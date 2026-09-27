#!/usr/bin/env python3
"""Automated movie splitter: AI segmentation, narration TTS, ffmpeg cutting.

Output is always 9:16 vertical (fit + black padding).

Usage:
    python main.py --video movie.mp4 --subtitle movie.srt
    python main.py movie.mp4 movie.srt
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from src import pipeline
from src.config import STAGE_TOTAL, Settings
from src.logutil import log, set_debug, stage
from src.media import MediaInfo, probe, require_tools
from src.parts import Part
from src.planner import plan as plan_parts
from src.srt import Cue, parse_srt


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="main.py", description="Split a movie into narrated short parts",
    )
    p.add_argument("positional", nargs="*", metavar="VIDEO SUBTITLE",
                   help="shorthand: `main.py movie.mp4 movie.srt`")
    p.add_argument("--video", help="source movie/video file")
    p.add_argument("--subtitle", help="source .srt subtitle file")
    p.add_argument("--output", default=None, help="output root (default: ./output)")
    p.add_argument("--plan", default=None,
                   help="JSON file with the parts to render, skips automatic segmentation")
    p.add_argument("--min-part", type=float, default=60.0, help="min part length in seconds")
    p.add_argument("--max-part", type=float, default=300.0, help="max part length in seconds")
    p.add_argument("--device", default="cpu", help="TTS device (cpu/cuda)")
    p.add_argument("--tts-engine", choices=["chatterbox", "silent"], default="chatterbox",
                   help="silent = placeholder audio, for pipeline testing only")
    p.add_argument("--ref", default=None, help="reference wav to clone the narrator voice")
    p.add_argument("--exaggeration", type=float, default=0.5)
    p.add_argument("--temperature", type=float, default=0.8)
    p.add_argument("--narration-delay", type=float, default=1.0,
                   help="seconds of movie audio before the narrator starts")
    p.add_argument("--scene-seconds", type=float, default=3.0,
                   help="length of every scene clip in a part (default 3)")
    p.add_argument("--narration-words", type=int, default=200,
                   help="upper bound on recap length in words (see PROMPT.md)")
    p.add_argument("--font-dir", default=None, help="directory with caption font files")
    p.add_argument("--dry-run", action="store_true", help="only plan, write plan.json and exit")
    p.add_argument("--keep-going", action="store_true", help="continue after a part fails")
    p.add_argument("--debug", action="store_true", help="verbose ffmpeg logging")
    return p


def resolve_args(args: argparse.Namespace) -> argparse.Namespace:
    if args.positional and not (args.video and args.subtitle):
        if len(args.positional) != 2:
            log("ERROR", "Positional form needs exactly two values: VIDEO SUBTITLE")
            raise SystemExit(2)
        args.video, args.subtitle = args.positional
    if not args.video or not args.subtitle:
        log("ERROR", "Both --video and --subtitle are required")
        raise SystemExit(2)
    return args


def make_settings(args: argparse.Namespace) -> Settings:
    if args.output is None:
        args.output = str(Path(__file__).resolve().parent / "output")
    return Settings.from_args(args)


def validate_inputs(settings: Settings) -> MediaInfo:
    if not settings.video.is_file():
        log("ERROR", f"Video not found: {settings.video}")
        raise SystemExit(1)
    if not settings.subtitle.is_file():
        log("ERROR", f"Subtitle not found: {settings.subtitle}")
        raise SystemExit(1)
    if settings.plan_file and not settings.plan_file.is_file():
        log("ERROR", f"Plan file not found: {settings.plan_file}")
        raise SystemExit(1)
    info = probe(settings.video)
    if info.duration <= 0:
        log("ERROR", f"Could not read the duration of {settings.video}")
        raise SystemExit(1)
    log("INFO", f"Source: {info.width}x{info.height} @ {info.fps:.3f} fps, "
                f"{info.duration / 60:.1f} min, audio={'yes' if info.has_audio else 'no'}")
    if settings.min_part >= settings.max_part:
        log("ERROR", "--min-part must be smaller than --max-part")
        raise SystemExit(1)
    return info


def write_plan(settings: Settings, plan: list[Part]) -> Path:
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    path = settings.work_dir / "plan.json"
    path.write_text(json.dumps([p.to_dict() for p in plan], indent=2) + "\n", encoding="utf-8")
    return path


def run_pipeline(settings: Settings, plan: list[Part], cues: list[Cue],
                  info: MediaInfo) -> list[pipeline.PartResult]:
    results = pipeline.new_results(plan, settings.work_dir)
    stage(2, STAGE_TOTAL, "Generating TTS audio for narrations...")
    pipeline.generate_narrations(results, cues, settings)

    stage(3, STAGE_TOTAL, "Editing and slicing videos...")
    pipeline.render_parts(results, settings, info)

    stage(4, STAGE_TOTAL, "Mixing audio and handling subtitles...")
    pipeline.mix_parts(results, settings)
    pipeline.write_subtitles(results, cues)

    stage(5, STAGE_TOTAL, "Exporting final parts...")
    pipeline.render_shorts(results, settings)
    pipeline.verify(results)
    manifest = pipeline.write_manifest(settings, results, info)
    log("INFO", f"Manifest written: {manifest}")
    return results


def summarize(results: list[pipeline.PartResult], work_dir: Path) -> None:
    ok = [r for r in results if not r.failed]
    total = sum(r.part.duration for r in ok)
    log("INFO", f"Done: {len(ok)}/{len(results)} parts, {total / 60:.1f} min of video")
    for r in ok:
        names = ", ".join(sorted(p.name for p in r.folder.iterdir()))
        log("INFO", f"  {r.folder} -> {names}")
    log("INFO", f"Output root: {work_dir}")


def main() -> int:
    args = build_parser().parse_args()
    set_debug(args.debug)
    require_tools()
    settings = make_settings(resolve_args(args))
    other = settings.other_movie_in_output()
    if other:
        log("WARN", f"{settings.output_root} already holds the output of {Path(other).name}, "
                    f"its part folders are overwritten by this run")
    info = validate_inputs(settings)
    started = time.time()

    stage(1, STAGE_TOTAL, f"Generating cuts from {settings.plan_file.name}..."
           if settings.plan_file
           else "Analyzing story and generating cuts with dialogue boundaries...")
    plan = plan_parts(settings, info.duration)
    log("INFO", f"Plan written: {write_plan(settings, plan)}")
    if settings.dry_run:
        log("INFO", "--dry-run: stopping before TTS and rendering")
        return 0
    cues = parse_srt(settings.subtitle)

    try:
        results = run_pipeline(settings, plan, cues, info)
    except SystemExit as exc:
        log("ERROR", f"Pipeline aborted: {exc}")
        return 1
    failed = [r for r in results if r.failed]
    if failed:
        log("ERROR", f"{len(failed)} part(s) did not finish: "
                     f"{', '.join(f'part_{r.part.index:02d}' for r in failed)}")
    summarize(results, settings.work_dir)
    log("INFO", f"Elapsed: {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
