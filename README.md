# clipper-movie

Split a movie into recap parts using subtitle structure, local TTS, and ffmpeg. Every
part is a montage of a few seconds of the film, cut to run exactly as long as its recap,
with the movie audio dropped.

Everything runs locally: no API key, no LLM, no network.

## Setup

```bash
nix develop          # creates .venv, installs Chatterbox, ffmpeg, espeak-ng
```

## Usage

```bash
# Parts plus a 9:16 vertical short.mp4 (fit + black padding, hook, burned-in subtitles)
python main.py movie.mp4 movie.srt
python main.py --video movie.mp4 --subtitle movie.srt
```

Those two inputs are the only arguments. Everything else is hardcoded in
`src/config.py` (output directory, part lengths, TTS engine and voice, scene length,
narration delay, caption font).

## Plan file

`plan.json` in the project root is read when it exists, and segmentation is skipped:

```json
[
  {
    "part_index": 1,
    "start_timestamp": "00:00:00,000",
    "end_timestamp": "00:03:15,420",
    "narration_script": [
      "Here is what happens next.",
      "Mara refuses to stay in the harbour a night longer.",
      "Voss admits he killed the man who betrayed him."
    ],
    "scenes": [
      {"start_timestamp": "00:00:10,000", "end_timestamp": "00:00:13,000"},
      {"start_timestamp": "00:01:04,300", "end_timestamp": "00:01:07,300"},
      {"start_timestamp": "00:02:31,700", "end_timestamp": "00:02:34,700"}
    ]
  }
]
```

- `part_index` is ignored, parts are renumbered in start order.
- `start_seconds` / `end_seconds` work as an alternative to the timestamps.
- The part range is the story segment: it gives the narrator its lines and the dialogue
  to quote. The video is built only from `scenes`, so the range can be much longer than
  the finished part.
- Timestamps snap to the nearest subtitle cue (starts forward, ends backward) so a clip
  never cuts a sentence in half.
- Every usable item of the plan becomes a part, sorted by start time and renumbered.
  Nothing is merged, trimmed or dropped for overlapping or for leaving film unused: each
  part renders its own montage, so two parts may cover the same stretch of film. An item
  is only dropped when it has no usable range or no usable scene, and the run says how
  many were dropped.
- `scenes` is an **array of short clips** (2 to 4 s each) that the part shows as a
  montage. List enough of them to cover the recap: a 15 s recap needs 5 clips of 3 s. When
  the plan falls short, the tool first adds other clips from the same segment and only then
  repeats.
- `narration_script` is an **array of beats** (one spoken line and one caption each); a
  plain string is also accepted and split into sentences.
- `narration_timestamps` is optional, one timestamp per beat. Omit it and the tool finds
  the right subtitle line by matching the words of each beat.
- `narration_script` and `hook` are optional: anything missing is generated
  from the dialogue of that part.

## Pipeline

```
[1/5] Analyzing story and generating cuts with dialogue boundaries...
[2/5] Generating TTS audio for narrations...
[3/5] Editing and slicing videos...
[4/5] Mixing audio and handling subtitles...
[5/5] Exporting final parts...
```

1. `src/planner.py` either reads the project `plan.json` or falls back to `src/heuristic.py`,
   which scores every subtitle cue start as a possible
   cut: silence before the cue, whether the previous line finished a sentence, and how
   close the cut lands to the target part length. Scene changes can cut below the minimum
   length; short tails are merged back into the previous part.
2. `src/narrator.py` writes the recap by ranking the part's own dialogue (action verbs,
   proper nouns, questions, informative length) and gluing the best lines together in
   chronological order with fixed connectives, so nothing can be invented. Style and
   length targets live in `PROMPT.md`.
3. `src/tts.py` speaks each beat separately with Chatterbox (optionally cloning a
   reference voice) and records its timing, so every beat becomes one subtitle caption.
4. `src/scenes.py` decides the clips a part shows: the `scenes` array of the plan, or one
   clip of `scene_seconds` around the line each beat quotes. `src/schedule.py` starts
   beat i on scene i, repeats clips when the recap outlasts them, and drops the clips the
   recap never reaches.
5. `src/render.py` concatenates the clips into one silent montage, `src/mixer.py` drops
   the movie audio and lays the beats on that timeline, and `src/shortform.py` renders
   the vertical versions. `src/pipeline.py` writes the subtitles and the manifest.

## Output

```
output/            (output_root in src/config.py, default ./output)
├── manifest.json
├── plan.json
├── part_01/
│   ├── short.mp4
│   ├── narration.mp3
│   ├── narration.srt
│   └── subtitle.srt
└── part_02/ ...
```

The output directory is used as it is, with no folder per movie inside it: set
`output_root` in `src/config.py` (for example `result/hobbit`) when you want one
directory per film. Writing a second movie into the same directory overwrites the part
folders, and the tool says so before it starts.

`video.mp4` is an intermediate: the montage in the source aspect, used as the input of
`short.mp4`. It is deleted once `short.mp4` is rendered.

## Options

Only the video and the subtitle are arguments. The rest is hardcoded in `src/config.py`:

| Setting | Value | Description |
|---------|-------|-------------|
| `plan_file` | `plan.json` if it exists | renders those parts instead of segmenting automatically |
| `output_root` | `./output` | where the part folders are written |
| `min_part` / `max_part` | 60 / 300 | story segment length in seconds, before trimming |
| `narration_words` | 200 | upper bound on recap length in words (see `PROMPT.md`) |
| `tts_engine` | `chatterbox` | set to `silent` for pipeline testing only |
| `ref_audio` | none | reference wav to clone the narrator voice |
| `device` | `cpu` | TTS device (`cuda` is much faster) |
| `scene_seconds` | 3.0 | length of a scene clip when the plan does not list them |
| `narration_delay` | 1.0 | earliest a beat may start, the rest follow their scenes |
| `font_dir` | `input/font` | caption font directory |

## Notes

- Chatterbox on CPU is slow (roughly a minute of narration per minute generated). Use
  `device` in `src/config.py` set to `cuda` when a GPU is available. Chatterbox also prints
  its own sampling progress bars, which are not part of this tool's log format.
- The narration is a digest of the real dialogue, so it can only be as interesting as the
  lines the script picks.
- Longer recaps come from `narration_words`, and are limited by how many distinct lines
  a segment actually contains.
- A plan whose `scenes` do not cover the recap ends up with repeated clips, which is
  visible; list roughly `recap seconds / 3` scenes instead.
- `manifest.json` lists `montage_scenes` (the clips actually rendered, with the source
  range and the position inside the montage) and `narration_beats` with exact start
  times.
