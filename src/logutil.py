"""Uniform console logging: every line is `[LEVEL] message`."""
from __future__ import annotations

import sys

LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")

_debug_on = False


def set_debug(enabled: bool) -> None:
    global _debug_on
    _debug_on = enabled


def log(level: str, msg: str) -> None:
    tag = level if level in LEVELS else "INFO"
    if tag == "DEBUG" and not _debug_on:
        return
    stream = sys.stderr if tag == "ERROR" else sys.stdout
    print(f"[{tag}] {msg}", file=stream, flush=True)


def stage(index: int, total: int, message: str) -> None:
    """Print a pipeline stage banner, e.g. `[INFO] [2/5] Generating TTS ...`."""
    log("INFO", f"[{index}/{total}] {message}")
