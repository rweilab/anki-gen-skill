# Video and local-media sources

Opt-in. Use when the user provides a YouTube video/playlist, a local recording, or asks to find one.

## Pipeline runs

`pipeline.py --sources "<url-or-local-path>" --out "$WORK" [--images auto|yes|no] [--model auto]
[--whole-playlist | --items 2-5] [--title "..."]` is the preferred path; `extract_video.py` is the
single-source diagnosis path. Long runs print `[media i/n]` and `[video i/n]` progress, keep
`video_meta.json` current after each video, and write `$WORK/pipeline_state.json`; rerun with
`--resume` and use `--status` to see completed, partial, failed, and interrupted work.
Confirmation is card-driven **after** the card text exists: confirm only a frame you are about to
attach, not the corpus. Prefer `direct` frames; if many candidates need confirmation, prioritize
front/answer-critical diagrams and leave decorative backs unconfirmed. There is no image mode and no
fixed image count. `pipeline.py --vision` is an advanced diagnosis pass, not the normal path.

## Local recordings

`extract_video.py "<file-or-directory>" --work "$WORK" [--images auto|yes|no]`
accepts `.mp4`, `.mkv`, `.mov`, `.webm`, `.m4v`, `.avi`, and audio-only
`.m4a`, `.mp3`, `.wav`, `.flac` (transcript only).

- A sidecar `.vtt` or `.srt` beside the media wins; no Whisper call.
- Otherwise faster-whisper runs locally when importable, with `--model auto`
  (one cached benchmark per machine), `--language`, `--device`, and an optional
  `--initial-prompt` for course terms. If faster-whisper is unavailable,
  `whisper-cli` runs the same audio through whisper.cpp; its model downloads on
  first use. YouTube does not use either backend.
- A directory is processed as a batch. Unsupported files are skipped and reported.
- Local IDs are hashes of path + size + mtime; transcripts are cached by file,
  model, and language.
- Source labels are `<filename or title> @ mm:ss`; `source_url` is intentionally
  empty for local files. Never fabricate a URL.
- Media never leaves the machine. The first run downloads a model once into
  `~/.cache/anki-gen/models`; later runs use `local_files_only` and never check
  the Hub. No cloud transcription.
- Frames use `frames.py --video-file`; no download path. Video sources default to
  `--images auto`; audio-only inputs skip frames; `--images no` disables them.
- `pipeline.py --sources <local-file-or-directory> --out "$WORK"` is the preferred one-call path.

## Questions, once

Answers go in `$WORK/intake.md`; stages 4b/7/10 read them instead of re-asking.

- Local: which file/directory, title, language, and whether a sidecar caption exists?
- YouTube: whole playlist, or videos x–z?
- Pull still frames when a diagram appears? yes/no/auto (video defaults to auto).
  - yes: automatic scoring; ambiguous frames are confirmed through the separate
    `image-vision` skill when a key is available. The main model never reads a
    frame by default; the bounded ≤6-image fallback in `SKILL.md` is the only
    exception. A shared diagram may be reused on multiple cards;
  - no: transcript-only.
- If “find it”: search, prefer the official channel/playlist, and state the choice.
  Ask one confirmation if the match is not strong.

## Transcripts

`extract_video.py "<url-or-local-path>" --work "$WORK" [--whole-playlist] [--items 2-5] [--images auto|yes|no]`

- Manual captions first; auto captions fallback with a warning.
- No captions and local transcription unavailable → report the failure; do not
  invent timestamps. YouTube does not use Whisper.
- Transcript chunks are written to the work tree and `source_index.sqlite`; `transcripts.md`
  (and per-video `transcripts/<id>.compact.md`) is the compact, deduplicated read: timestamped
  paragraphs plus a token estimate. Read that once; use the index only for a narrow lookup.
  A full series can exceed 100 KB, so the read tool may return it in sequential chunks; that is
  not duplication. Do not split it further; per-video files are for a narrow check.
- A video with missing or rate-limited captions is still registered and frame-scanned; `video_toc.md`
  marks `no_captions`/`rate_limited` instead of discarding the video. Do not retry a hard 429 for
  minutes; mark it and recover frames.
- Video dependencies come from `requirements-optional.txt`: `yt-dlp[default,deno]`
  includes the EJS solver and Deno runtime, so no system Node install is needed. The scripts
  call `python -m yt_dlp`, not whichever `yt-dlp` is on PATH. The scripts retry
  transient failures briefly (seconds, not 90/120) and skip/report permanent ones.
  Do not sleep, background, or poll yt-dlp. If a video still fails, reuse a cached
  VTT, use the companion slides, or report it; never invent a timestamp.
- Back reference format:
  - single: `<channel> - <video title> @ mm:ss`
  - series: `<channel> - <playlist> NN - <video title> @ mm:ss`
  - full title, never truncated.
- `source_url` is plain text, not a hyperlink: `https://www.youtube.com/watch?v=ID&t=SECONDS`
  (series adds `&list=PLAYLIST_ID`). `source` is the canonical short label
  (`DigiKey · RTOS 04 · Memory Management @ 01:32`); copy it, do not rebuild it from the title.
- The URL is copyable in Anki and the review page.
- Do not dump a whole playlist transcript into the conversation.

## Frames

Frames are 720p stills. `frames.jsonl` logs every candidate with its metrics; `frames.md` lists
only the best frame per cue plus genuinely ambiguous `confirm` candidates. `frames.py --at mm:ss`
is the manual override. Copy the exact backticked path from `frames.md`; never build a filename
from a timestamp. `direct` frames are attachable without a vision call; only `confirm` needs it.

The picker is two-stage:
- one cheap probe per cue; shortlist cues with visual structure or an explicit
  visual phrase;
- sample `-2s, 0, +2s, +4s, +6s` around those cues; run OCR only on the shortlist;
- score edge focus, colour, and background. A text wall requires **both** many
  words and flat structure; word count alone must never reject a labelled
  diagram. Good image-only diagrams often have few or zero OCR words.
- keep one best frame per cue; prefer the latest high/confirm frame inside that
  shot (a dHash cut guard stops it crossing a hard scene change);
- if a video has no useful cues or no attachable frames, run a coarse visual-only
  scan and keep one best frame per visual cluster;
- collapse near-identical frames only inside that cue, never across different
  cues or cards;
- `direct` → attach. `confirm` → confirm through `image-vision` or explicit
  caller approval; a cue naming a visual is not approval. `skip` stays in
  `frames.jsonl`.
- `frames.py --sweep 00:00-02:30 --every 10` is the bounded chapter scan; use it
  instead of a long series of manual `--at` calls. `frames.md` lists canonical
  frames; alternates stay in `frames.jsonl`.
- For a missing/rate-limited transcript, seed one official companion-article or
  slides search from the video title/description; register the URL as a second
  source and cite it. Do not invent diagrams or use a random mirror.
- `--max` is a safety cap, not a per-video target.
- **Never read an image with the main model by default.** No `read` on `media/*.png`, no
  scan/contact-sheet review, no vision on the model's own stream; the bounded ≤6-image fallback in
  `SKILL.md` is the only exception. These are the expensive, low-yield calls this pipeline exists
  to avoid.

Stop a background `vision_check` with the PID you started (`$!`) or a bracket
pattern such as `pkill -f '[v]ision_check.py'`; never `pgrep -f` the literal name.

`image-vision` is card-driven and sparing: confirm only a frame you are about to
attach, only when it is `confirm`/`needs_vision`. If it has no key or its one
bounded retry fails, the ≤6-image main-model fallback from `SKILL.md` is allowed
only for necessary frames and must be labeled unverified. Use
`image-vision/scripts/vision_check.py --max N` for the fast accept/reject pass;
it resolves the model, retries 503/429 briefly, caches by SHA, and stops on a
quota error. One call per unique frame. Use the full `image-vision` pipeline for
labels, relationships, handwriting, and ambiguous figures only. For long dense
series, process by chapter/topic and confirm only the candidates needed by
cards; there is no fixed per-video confirmation count.

Attach frames only when they illustrate the card. Title/outline/agenda slides are
not images: `frames.py` marks them `skip`, and a frame whose caption is only
"Lecture: ..." needs a real recaption or removal. A `confirm` frame needs
`image-vision` or explicit approval; "more pictures" is not approval. If no good
frame exists, leave the card without one. Each media entry carries `source` and
the frame's `source_url`; those become the one-line footer, so do not repeat the
full source in the card text. A canonical diagram may be attached to several
related cards; media reuse is expected, not duplication.
Review serves image cards as a bounded cross-section; a wrong frame is a review
comment.

## Legal

Personal study only. Respect YouTube’s terms and the video’s copyright. Do not
bypass DRM, logins, age gates, or region restrictions; do not redistribute
frames. Keep the video URL and timestamp on every frame card. Local recordings
stay local; never upload them, and cite the filename/timestamp without inventing
a URL.
