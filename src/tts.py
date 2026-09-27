"""Narration TTS: one audio file per beat, Chatterbox (local) or silent for dry runs."""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .logutil import log

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
MAX_SEGMENT_CHARS = 220
GAP_SECONDS = 0.28
WORDS_PER_SECOND = 2.6


@dataclass(frozen=True)
class BeatClip:
    text: str
    path: Path
    duration: float


def split_script(script: str) -> list[str]:
    """Split a narration script into speakable sentences."""
    flat = " ".join(script.split())
    if not flat:
        return []
    out: list[str] = []
    for sentence in SENTENCE_RE.split(flat):
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > MAX_SEGMENT_CHARS:
            cut = sentence.rfind(" ", 0, MAX_SEGMENT_CHARS)
            cut = cut if cut > 0 else MAX_SEGMENT_CHARS
            out.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            out.append(sentence)
    return out


def estimate_duration(text: str) -> float:
    return max(0.8, len(text.split()) / WORDS_PER_SECOND + 0.35)


def as_beats(script: str | list[str] | tuple[str, ...]) -> list[str]:
    """A sequence is one element per spoken line, a string is split on sentences."""
    if isinstance(script, str):
        return split_script(script)
    return [s for s in (" ".join(str(x).split()) for x in script) if s]


@dataclass
class _Spoken:
    text: str
    duration: float
    wav: object | None = None


def _load_chatterbox(device: str, ref: Path | None):
    import perth
    from chatterbox.tts import ChatterboxTTS

    class _NoWatermarker:
        def apply_watermark(self, wav, sample_rate=None, **kwargs):
            return wav

    if getattr(perth, "PerthImplicitWatermarker", None) is None:
        perth.PerthImplicitWatermarker = _NoWatermarker
    ref_path = str(ref) if ref else None
    if ref_path and not Path(ref_path).is_file():
        log("ERROR", f"Reference audio not found: {ref_path}")
        raise SystemExit(1)
    log("INFO", f"Loading Chatterbox TTS on device={device}")
    return ChatterboxTTS.from_pretrained(device=device), ref_path


def _speak_chatterbox(sentences, device, ref, exaggeration, temperature, on_progress):
    model, ref_path = _load_chatterbox(device, ref)
    sr = model.sr
    spoken: list[_Spoken] = []
    for i, sentence in enumerate(sentences, start=1):
        wav = model.generate(
            sentence, audio_prompt_path=ref_path,
            exaggeration=exaggeration, temperature=temperature,
        )
        spoken.append(_Spoken(sentence, wav.shape[1] / sr, wav))
        on_progress(i, len(sentences), sum(s.duration for s in spoken))
    return spoken, sr


def _speak_silent(sentences, _device, _ref, _exag, _temp, on_progress):
    spoken: list[_Spoken] = []
    cursor = 0.0
    for i, sentence in enumerate(sentences, start=1):
        duration = estimate_duration(sentence)
        spoken.append(_Spoken(sentence, duration))
        cursor += duration + GAP_SECONDS
        on_progress(i, len(sentences), cursor)
    return spoken, 24000


ENGINES = {"chatterbox": _speak_chatterbox, "silent": _speak_silent}


def synthesize_beats(
    beats: list[str], out_dir: Path, *, engine: str, device: str, ref: Path | None,
    exaggeration: float, temperature: float,
) -> list[BeatClip]:
    """Render every beat to its own MP3 so each can be placed on the timeline."""
    sentences = as_beats(beats)
    if not sentences:
        log("ERROR", "Narration script is empty after cleaning")
        raise SystemExit(1)
    if engine not in ENGINES:
        log("ERROR", f"Unknown TTS engine: {engine}")
        raise SystemExit(1)
    out_dir.mkdir(parents=True, exist_ok=True)

    def on_progress(done: int, total: int, elapsed: float) -> None:
        log("INFO", f"  beat {done}/{total} ({elapsed:.1f}s of speech)")

    log("INFO", f"Synthesizing {len(sentences)} beats with engine={engine}")
    spoken, sr = ENGINES[engine](
        sentences, device, ref, exaggeration, temperature, on_progress
    )
    clips: list[BeatClip] = []
    for i, item in enumerate(spoken, start=1):
        path = out_dir / f"beat_{i:02d}.mp3"
        if item.wav is not None:
            _encode_wav(item.wav, sr, path)
        else:
            _encode_silence(item.duration, path)
        clips.append(BeatClip(text=item.text, path=path, duration=item.duration))
    return clips


def _encode_wav(wav, sr: int, out_mp3: Path) -> None:
    import torchaudio

    tmp = out_mp3.with_suffix(".tmp.wav")
    torchaudio.save(str(tmp), wav.detach().cpu().reshape(1, -1).contiguous(), sr)
    encode_mp3(tmp, out_mp3)
    tmp.unlink(missing_ok=True)


def _encode_silence(duration: float, out_mp3: Path) -> None:
    tmp = out_mp3.with_suffix(".tmp.wav")
    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
           "-t", f"{max(0.5, duration):.3f}", str(tmp)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        log("ERROR", f"ffmpeg silence generation failed: {res.stderr.strip()[-500:]}")
        raise SystemExit(1)
    encode_mp3(tmp, out_mp3)
    tmp.unlink(missing_ok=True)


def encode_mp3(wav_path: Path, out_mp3: Path) -> None:
    if not shutil.which("ffmpeg"):
        log("ERROR", "ffmpeg not found in PATH")
        raise SystemExit(1)
    cmd = ["ffmpeg", "-y", "-i", str(wav_path),
           "-c:a", "libmp3lame", "-q:a", "2", str(out_mp3)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        log("ERROR", f"ffmpeg mp3 encode failed: {res.stderr.strip()[-500:]}")
        raise SystemExit(1)
