# Source survey

## Source survey — propose, then stop

The user is told **which material will be used, and why, before any cards exist.** Never start
extracting on the strength of a directory name. Report:

| State | Why it earns a line |
|---|---|
| Each candidate source — lecture deck, homework, answer key, textbook, notes | the user may not remember what is in the folder |
| What it covers | so a scope mismatch surfaces now, not after the deck is built |
| **Use / use with caveats / skip, and the reason** | the user is approving a judgement, not a file listing |
| Extraction quality — text layer vs scanned | a scan needs OCR and degrades; say so |
| Anything that would leak answers onto fronts | an answer key puts worked numbers where a front must not have them |

**Name the material shape** — single PDF, PowerPoint, nest of directories, mixed formats,
conflicting answer keys, scan with no text layer, video URL/playlist — and say what you will do
about it. PPTX is read as text/notes/embedded images; vector slides are cited, not rendered.

**Video or local media.** If the request contains a YouTube video/playlist or a local recording:
for local media, confirm the file/directory, title, language, and whether sidecar captions exist; skip the playlist/range questions.
- report title/channel/duration and whether captions are manual or auto;
- ask **whole playlist or videos x–z**;
- ask **pull still frames when the video shows a diagram?** yes/no (automatic
  scoring; ambiguous frames may be confirmed with image-vision; the main model
  never reads frames by default; the bounded kernel fallback is the only exception);
- if the caller supplied a URL, extract it first; search only around a missing/incomplete source;
- if the user gave a description rather than a URL, use it as the seed for **one** bounded search,
  prefer the official channel/playlist/course page, and record the URL and why in `intake.md`;
- if the user said “find it,” search and prefer the official channel/playlist; proceed only when
  the match is strong, otherwise ask one confirmation;
- if captions fail or a visual topic has no images, use the video title/description for one
  official companion article/slides search; register it as a source, do not auto-attach its images;
- if the recording is audio-only and the caller asked for diagrams, say so: audio-only files cannot
  supply frames; use PDF figures or skip the image request;
- YouTube: no Whisper; if no captions exist, skip that video and say so.
- Local: sidecar captions first; otherwise faster-whisper or whisper.cpp locally.
  No cloud upload. The whisper.cpp model downloads on first use.

**Write the answers to `$WORK/intake.md` before leaving the survey.** Stages 4b,
7 and 10 read this instead of re-asking:

```markdown
# Intake
- deck: <caller's deck name>
- learner: beginner | power
- goal: recall | reasoning | problem-solving
- minutes/day: <number, or unknown>
- calibration: cold | attended | strong
- reference: none | given | memorized
- sources: <chosen files/videos/playlists>
- video: none | <url> | playlist | items x-z
- images: yes | no
- review: default | no review
- assumed: <one line per assumption>
```

These are prose context, not new parser fields. `goal` and `minutes/day` help the scope gate and
run report; `calibration` and `reference` prevent guessing. For document sources, images default
no unless the caller asks; when images are yes, confirm only images the cards actually need.

**Read the course's own learner context and say what you found.** For a long `STUDY-LOG.md`, read
the header and calibration section, not the whole file. A directory carries files written
for whoever works in it — `AGENTS.md`, `CLAUDE.md`, `STUDY-LOG.md`, `README`, notes-to-self.
Nothing else in the pipeline opens them, and they are the cheapest source of the two signals that
decide what a deck is *for*: what has already caused a recurring error (rule 21's second
criterion), and the learner's level (the calibration table). A `STUDY-LOG.md` saying "I keep mixing
up wt% and at%" is worth more than another lecture deck. Report anything that changes scope or
scaffolding — or say plainly that none were found.

## Extraction (stages 4–4b)

Use **one synchronous** `pipeline.py --sources <...> --out .anki-gen-temp/<topic>` call with all
chosen PDFs, text, PowerPoint, URLs, directories, and media. A directory containing both documents
and media is split by file type, so the PDF is not silently skipped. Do not start a second
background extractor. For a single-source diagnosis use `extract_pdf.py`; `--date-filter` limits
directory sources. PPTX text, notes, and embedded images are parsed without Office.

Never pass the course root when `$WORK` is inside it: directory extraction recurses and can ingest
the generated transcript/source files. Pass explicit source subdirectories.

Single-source extraction prints `content`, `source_type`, `source_path`, `images_count`, a 3-name
sample, and the `.md` path; batch prints a manifest with counts, samples of `<tag>` dirs, and `.md`
paths, and writes `sources.md` with the chosen texts. Read `sources.md` **once after extraction completes**, when classifying; use a per-source `.md` only
for a narrow check. Cite the file the text came from ("Lec 04 · p.12"), not the topic directory.

Video and local media are owned by `references/video.md`: the preferred path is
`pipeline.py --sources "<url-or-local-path>" --out "$WORK" [--images auto|yes|no] [--model auto]
[--whole-playlist | --items 2-5] [--title "..."]`; `extract_video.py` is the single-source
diagnosis path.

**The deck audit is opt-in; do not offer it.** Run stage 3 only when the request asks ("is there a
deck for this", "check online", "merge with what exists", or `audit_web: true`). The modal outcome
is "generate your own"; a real Callister deck audited at 58/100. It pays off only when a good deck
already exists for a popular course — rare enough to be a sentence in the request, not a question
every run.

**Deck naming is the caller's.** Ask for it here too, suggesting a shape:
`SCHOOL::CIRCUITS::TOPIC`. Their answer is the name, flat included (rule 23); `--deck-name` is
required at build. Impose no convention. A silent `"Default"` fallback once let a valid deck land
somewhere nobody finds. A `::` nests; Anki matches deck names case-insensitively.

**Then stop and wait — unless the caller is a beginner.** For a power user, propose, take the
answer, then EXTRACT. For a beginner, proceed on the survey's recommendation and list the
assumptions in the report: the survey's value is that the sources are right, which the caller
corrects from the report as cheaply as from a question. **Why this is a gate, not a summary:**
coverage is decided here, by which sources get used — a deck built from the wrong two lectures is
not something better cards can repair later.

**Scanned or handwritten sources.** If a PDF has almost no text layer but images, say so in
the survey. The options are: read it with `image-vision` (Gemini, if available) and build from
the transcription, or skip that source. Do not propose a deck from empty text.

