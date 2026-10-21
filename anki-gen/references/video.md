# Video sources

Opt-in. Use when the user provides a YouTube video/playlist or asks to find one.

## Questions, once

Answers go in `$WORK/intake.md`; stages 4b/7/10 read them instead of re-asking.

- Whole playlist, or videos x–z?
- Pull still frames when a diagram appears? yes/no.
  - yes: automatic selection, one image per card, no per-frame verification;
  - no: transcript-only.
- If “find it”: search, prefer the official channel/playlist, and state the choice.
  Ask one confirmation if the match is not strong.

## Transcripts

`extract_video.py "<url>" --work "$WORK" [--whole-playlist] [--items 2-5] [--images yes|no]`

- Manual captions first; auto captions fallback with a warning.
- No captions → skip that video and report it. No Whisper in v1.3.
- Transcript chunks are indexed for `page.py`; read only the chunks a card needs.
- Back reference format:
  - single: `<channel> - <video title> @ mm:ss`
  - series: `<channel> - <playlist> NN - <video title> @ mm:ss`
  - full title, never truncated.
- `source_url` is plain text, not a hyperlink: `https://www.youtube.com/watch?v=ID&t=SECONDS`
  (series adds `&list=PLAYLIST_ID`).
- The URL is copyable in Anki and the review page.
- Do not dump a whole playlist transcript into the conversation.

## Frames

`frames.jsonl` / `frames.md` list candidate frames with `confidence`, OCR word
count, edge score, caption, timestamp and source. `frames.py --at mm:ss` is the
manual override.

Automatic selection:
- transcript cues: diagram, figure, state machine, block/timing diagram,
  schematic, architecture, chart, graph, table, “this slide”, “as you can see”;
- sample around the cue, 720p, OCR + edge/slide score;
- one `BEST` frame is marked per cue; high confidence can attach directly;
- **low/medium confidence:** hand the listed frame path (or `BEST` frame) to the
  separate `image-vision` skill, which reads one image with Gemini. Attach only
  if it confirms a diagram/slide with relevant labels; otherwise leave it in
  `frames.md`. Do not use main-model vision or attach on OCR/edge alone.
- low-confidence candidates may appear in the review media cross-section;
- one image per card; no per-frame questions.

Attach frames only when they illustrate the card. Caption and source are
required. Review serves the image and samples image cards as a bounded
cross-section; a wrong frame is a review comment.

## Legal

Personal study only. Respect YouTube’s terms and the video’s copyright. Do not
bypass DRM, logins, age gates, or region restrictions; do not redistribute
frames. Keep the video URL and timestamp on every frame card.
