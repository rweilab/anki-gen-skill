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
  never reads frames);
- if the user said “find it,” search and prefer the official channel/playlist; proceed only when
  the match is strong, otherwise ask one confirmation;
- YouTube: no Whisper; if no captions exist, skip that video and say so.
- Local: sidecar captions first; otherwise faster-whisper locally. No cloud upload.

**Write the answers to `$WORK/intake.md` before leaving the survey.** Stages 4b,
7 and 10 read this instead of re-asking:

```markdown
# Intake
- deck: <caller's deck name>
- learner: beginner | power
- sources: <chosen files/videos/playlists>
- video: none | <url> | playlist | items x-z
- images: yes | no
- review: default | no review
- assumed: <one line per assumption>
```

**Read the course's own learner context and say what you found.** A directory carries files written
for whoever works in it — `AGENTS.md`, `CLAUDE.md`, `STUDY-LOG.md`, `README`, notes-to-self.
Nothing else in the pipeline opens them, and they are the cheapest source of the two signals that
decide what a deck is *for*: what has already caused a recurring error (rule 21's second
criterion), and the learner's level (the calibration table). A `STUDY-LOG.md` saying "I keep mixing
up wt% and at%" is worth more than another lecture deck. Report anything that changes scope or
scaffolding — or say plainly that none were found.

**The deck audit is opt-in; do not offer it.** Run stage 3 only when the request asks ("is there a
deck for this", "check online", "merge with what exists", or `audit_web: true`). The modal outcome
is "generate your own"; a real Callister deck audited at 58/100. It pays off only when a good deck
already exists for a popular course — rare enough to be a sentence in the request, not a question
every run.

**Ask for the deck name here too**, suggesting a shape: `SCHOOL::CIRCUITS::TOPIC`. Their answer is
the name, flat included (rule 23); `--deck-name` is required at build.

**Then stop and wait — unless the caller is a beginner.** For a power user, propose, take the
answer, then EXTRACT. For a beginner, proceed on the survey's recommendation and list the
assumptions in the report: the survey's value is that the sources are right, which the caller
corrects from the report as cheaply as from a question. **Why this is a gate, not a summary:**
coverage is decided here, by which sources get used — a deck built from the wrong two lectures is
not something better cards can repair later.

**Scanned or handwritten sources.** If a PDF has almost no text layer but images, say so in
the survey. The options are: read it with `image-vision` (Gemini, if available) and build from
the transcription, or skip that source. Do not propose a deck from empty text.

