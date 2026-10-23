# Changelog

Newest first. Keep the index to one line per release; details live below.

- **v1.5.0** — Revise imported decks in Anki via AnkiConnect, with a persistent dossier and revert
- **v1.4.2** — Recover alternate images/captions and calibrate review with score-1 evidence
- **v1.4.1** — Local audio/video, PDF/slide/web images, and answer-first card validation
- **v1.4** — Rank visual candidates across PDFs/video and reuse shared media safely
- **v1.3.2** — Order new cards foundation-first within each topic
- **v1.3.1** — One-command installer plus review finish/close UX
- **v1.3** — YouTube/playlist transcripts, video frames, and handoff packaging
- **v1.2** — Review fidelity, validator guards, and token discipline
- **v1.1** — macOS handoff kit
- **v1.0** — Base build

## v1.5.0 — Imported-deck revision and persistent context

### Added
- AnkiConnect-only revision for imported decks: attach, audit, plan, apply, snapshot, and
  revert. Unavailable AnkiConnect fails with a setup message and nonzero exit; new `.apkg`
  builds stay offline.
- Persistent dossiers under `${XDG_DATA_HOME:-~/.local/share}/anki-gen/decks/<deck-uuid>/`:
  stable UUID, schema 1, rebuildable index, manifest file/checksum table, separate authored
  `cards.jsonl` and live `anki_state.jsonl`, transactional writes, resources, adaptive previews,
  and deterministic portable archives. Unknown fields are preserved; newer schemas are refused.
- Plaintext revision planning with human and machine plans, three-way conflict reporting,
  scheduling-safe field updates, merge/split history rules, cloze-shape approval, and explicit
  Delete permanently / Suspend / Keep choices for every destructive group.
- Scheduling snapshots and one-command revert. Each apply stores `deck.apkg` plus metadata-only
  `snapshot.json`; affected old fields and queue state live in `backup.json`. Revert restores
  updates, removes additions, imports deleted notes, and restores suspension while preserving
  later manual edits by default.
- Explicit snapshot retention: `snapshots --sizes` reports per-snapshot and directory usage and
  warns above 256 MB or 16 snapshots by default; `--delete` and `--prune --keep N` require
  `--yes`. Nothing is deleted automatically, and the latest apply snapshot needs `--force`.
- Supported bulk revision: `revision.py update` applies structured field/tag edits by `rev_id`
  with snapshot, backup, and scheduling verification; `revision.py tags --lowercase` normalizes
  deck tags without collection-wide cleanup.
- Adaptive media previews for unused high/medium candidates: about 640 px general, 768–1024 px
  for label-heavy diagrams, 320 px only for contact-sheet recognition. Previews index the
  source; originals are re-extracted before attachment.
- Video sources now default to frame extraction (`--images auto`); audio-only inputs skip it.
- Local transcription feeds faster-whisper a decoded WAV array, avoiding the PyAV
  `metadata_errors` incompatibility, and loads cached models with `local_files_only`.
- Generated tags are lowercase and case-insensitively deduplicated; the displayed `Topic` field
  keeps its capitalization.
- Self-contained math/definitions may use `source: "derived"`, which keeps provenance metadata but
  omits the citation footer. Source-dependent claims still need a locator.
- `pipeline.py --build` packs the dossier automatically before cleanup; `--no-context` opts out.
  Old decks without a dossier can be reconstructed read-only from live fields and tags.

### Changed
- Stage 11 now leaves a durable dossier outside the caller's directory; stage 14 still removes
  `.anki-gen-temp` in full. Revision/dossier detail is lazy-loaded from references, and the v1.5
  `SKILL.md` prose stays smaller than before.
- Snapshot creation counts notes/cards without loading full deck fields or review history.
- Revision now starts with an AnkiConnect preflight, verifies required actions, and can
  detect the Anki profile and install a pinned add-on. The live collection DB is explicitly off-limits.
- The duplicate `deck_context.py` CLI was removed; `revision.py context` is the one dossier
  command surface. The Python facade remains.
- Stage references now have one read-when index; `tests/README.md` maps suite ownership and
  keeps future debugging from starting with a full-tree read.
- Install/bootstrap docs now call out AnkiConnect as a separate opt-in in-Anki add-on.
- `VERSION` is `1.5.0`; the review web UI, its Easy button, and its summary text are unchanged.

### Fixed
- Revert no longer depends on a full deck-state copy inside the snapshot; slim metadata plus the
  affected-state backup is sufficient and keeps large decks from duplicating themselves.
- Future/newer dossier schemas are refused read-only, and archives reject unsafe paths, symlinks,
  duplicates, oversized files, and checksum mismatches.
- Manual Anki edits win over planned field updates unless `--overwrite-conflicts` is explicit.
- Snapshot deletion cannot silently remove the easy `revert --last` target or escape the
  snapshot directory.
- `cardid.py --help` now prints usage instead of treating the flag as a filename.
- A stuck review server is stopped with `POST /finish`; guidance no longer invites a
  self-matching `pkill -f`.
- Back/why guidance now rejects positional restatements, repeated boilerplate, unexplained jargon,
  and citations on obvious math; shared explanations belong on one concept card, with concrete
  good/bad examples from real deck edits.

### Notes
- AnkiConnect is the only live integration surface. No raw SQLite writes, `anki` library path,
  MCP server, or second Anki integration was added.
- Snapshot retention is local and explicit; context export still excludes snapshots by default.

## v1.4.2 — Image/alternate-source ingest and review calibration

### Added
- Compact transcript output from `extract_video.py`: rolling captions are deduplicated and
  grouped into timestamped paragraphs, with a token estimate; the original JSONL/SQLite index
  remains for exact lookup.
- A no-caption path: a video whose captions are missing or rate-limited still registers and
  runs a visual frame scan, instead of being skipped.
- Canonical short source labels (`DigiKey · RTOS 04 · Memory Management @ 01:32`); the full URL
  stays in `source_url`, and manual `frames.py --at` labels are normalized.
- `frames.py --sweep` for a bounded chapter/time-range visual scan, and structure-hash/caption
  clustering with canonical-frame marking; alternates stay in `frames.jsonl`.
- `vision_check.py` hardening: per-image report, flush, per-call and global deadlines, 429
  fail-fast, model discovery with an environment override, and prompt/mode cache keys.
- `media_index.py` merges vision results with figures/frames and ranks candidates per card.
- `pipeline.py` accepts `--work` (and validates `--out`), `--page-crops`, and an opt-in
  `--vision auto` bounded pass over canonical frames.

### Changed
- Exact normalized `(front, back)` duplicates are rejected; soft pairwise front/answer/ROI
  similarity is opt-in (`--deep`) rather than default review noise.
- Capability/coverage planning is explicit: scope/ledger guidance now asks for retrieval
  intents and a soft per-topic target; a >15-card topic emits a warning, never an automatic cut.
- Score 1 is treated as calibration evidence (“known / too easy”) for rescoping topics,
  merging or re-leveling cards, and shifting focus — not as an automatic trim list. The
  review page and its Easy button are unchanged.
- Source survey can seed one official web search from the caller's description, and a failed
  caption extraction can seed a bounded companion-article/slides search. A caller-supplied URL
  is extracted first.

### Fixed
- A missing/429 caption no longer collapses into “no subtitles” and discards the whole video.
- A 900-second vision batch can no longer disappear without output: every result is flushed
  and written to the work tree, and a rate limit stops promptly.
- Repetitive channel/playlist/episode labels no longer dominate card footers.

### Notes
- Deck revision/update of already-imported Anki collections is deferred to v1.5.

## v1.4.1 — Local video/audio and answer-aligned cards

### Added
- A canonical quality contract in `MAINTAINERS.md`, enforced by a guardrail in `AGENTS.md`: the 98%
  quality floor outranks reliability, token/API efficiency, and speed; context and reasoning are
  not cut merely to make a run cheaper.
- PDF/slide/web visual ingest: figure bboxes, nearest caption and nearby text, tight
  `page-crop`/`slide-crop` candidates for vector figures, web image metadata (`urljoin`, alt,
  figcaption, heading), and `media_index.py --cards` ranking. Candidates are `confirm`/`drop`;
  nothing is auto-attached, and the main model still never reads pixels.
- `pipeline.py --build` requires `intake.md`, `scope_gate.md` and `authoring_ledger.md`, prints an
  evidence summary, and now passes through merge, date-filter, playlist/range, title, device and
  initial-prompt options. Multiple video sources merge their source map instead of overwriting it.
- Static validation is the default at build (`--allow-invalid` is diagnosis-only). Structural guards
  cover unterminated cloze, markdown images, cross-card pointers, and content-derived card identity;
  a narrow tier-zero coverage warning and an info-only glossary signal were added.
- Local `.mp4`, `.mkv`, `.mov`, `.webm`, `.m4v`, `.avi`, and audio-only
  `.m4a`, `.mp3`, `.wav`, `.flac` sources, including directory batches.
- Sidecar `.vtt`/`.srt` captions are used before any local model work. When
  absent, `faster-whisper` transcribes locally; no media is uploaded.
- `--model auto` benchmarks actual speech once per machine, caches the choice,
  and falls back to `base.en` if the benchmark fails. Apple Silicon macOS and
  Linux are supported; Intel Macs are not supported for local transcription.
- `pipeline.py` now handles local/video sources and can build + validate the
  final `.apkg` in the same mechanical pass. Its summary includes the package
  path, validation result, note/card counts, and media count.
- Preflight rejects a discoverable stale backup `SKILL.md`; local media also
  checks ffprobe/ffmpeg and reports unsupported Intel Macs.
- Answer-first card rule: if the front asks “which enzyme/law/step,” the back
  must name the target before explaining it. A narrow validator error covers
  explicit “which enzyme” fronts with no enzyme name.
- Install/doctor/package/docs now cover faster-whisper, ffprobe, local media,
  and the supported Mac/Linux platforms.
- Offline adversarial tests for local media, sidecars, audio-only inputs,
  auto-model benchmarking, pipeline build/validation, and answer alignment.

### Fixed
- `validate_apkg.py`'s cloze check was inert on Anki's current schema; it now compares each note's
  distinct `{{cN::}}` ordinals with its cards, so one-deletion notes pass and missing splits fail.
- Card identity is always `md5(front|back)`: a stale explicit `hash` no longer makes a corrected
  card keep its old GUID and get skipped by `--merge-existing`.
- A bad date filter now errors instead of silently filtering every file, and a zero-text/zero-image
  source fails the batch instead of counting as a successful extract.
- The review finish sentinel defaults beside the feedback log, not the caller's cwd; smoke now
  cleans its temp tree on failure and fails if tests change the working tree.
- Local media no longer goes through yt-dlp; frames use the existing
  `frames.py --video-file` path.
- The mechanical pipeline is no longer PDF-only; it no longer leaves video
  extraction, gates, and build as separate model turns.
- A true but unanswered card (the fructose-1,6-bisphosphate/aldolase case) is
  now rejected before it reaches the deck.

### Notes
- Vector-only PPTX slides still need a PDF export; embedded PPTX images are extracted, vector
  shapes are cited/skipped unless a PDF is supplied.
- First local transcription downloads a model; later runs are offline.
- Vector PowerPoint/PDF still cannot be rendered without a PDF export.
- Deck revision/update of already-imported Anki collections remains deferred to
  v1.5.

## v1.4 — Visual source refinement

### Added
- Shared `scripts/visual.py`: edge focus, colour, background, text-wall detection,
  and perceptual hashes; video frames and PDF raster figures use the same score.
- Video frames are sampled in two stages, ranked by structure rather than OCR word
  count, and collapsed only within the same cue. Image-only diagrams now survive;
  labelled diagrams with many words are not mistaken for text walls.
- `frames.md` is compact and merged across videos; `frames.jsonl` carries quality,
  attach advice, metrics, and reject reason. Ambiguous `confirm` frames are
  card-driven for `image-vision`; no fixed per-video confirmation count.
- PDF figure extraction scores/filters raster figures, drops tiny/duplicates, keeps
  blank/text-like/table images flagged, and `media_index.py` lists high quality first.
- `yt-dlp[default,deno]` is installed through `requirements.txt`: EJS scripts and
  Deno ship with the Python environment. `python -m yt_dlp` is used everywhere;
  an existing Node 22+ is accepted as a fallback, with its path passed explicitly.
  A system yt-dlp/Node mismatch no longer causes frame-download debugging.
- The review done screen waits 6 seconds before attempting to close the tab.
- Backups now live under `~/.local/share/anki-gen/backups/`; legacy
  `~/.claude/skills/.backups` directories are migrated and their `SKILL.md`
  files renamed so an old copy cannot be discovered as the active skill.
- Study order is softly scattered across topics: small decks stay grouped; larger
  decks interleave topics, but each topic's `tier_zero` anchor still comes first.
  The order is deterministic for a given deck.
- Object tags are broad buckets now: topic/subtopic duplicates, one-topic tags,
  and one-offs are dropped; cross-topic buckets such as `rtos` and
  `concurrency` remain. Topic and object tags are treated as front-visible:
  `validate_cards.py` rejects a one-topic object tag that appears only in the
  answer (and warns for a topic that does), so a Bernoulli-substitution card
  cannot be tagged `bernoulli`.
- Main-model vision is banned in the skill. Ambiguous frames are confirmed only
  through the separate, cached `image-vision` pass, one call per unique frame,
  with `--max` and a 429 stop. No contact sheets or scan galleries.
- `extract_slides.py` reads `.pptx` text, speaker notes, and embedded raster
  images without Office or LibreOffice; vector-only slides are cited, not rendered.
- Media reuse is explicit: one shared diagram may appear on several related cards;
  the builder bundles the file once. `roi_report.py` reports refs vs unique files.
- Video/media docs now separate “attach” from “read”: the model chooses from
  `frames.md` by text, and never reads the image stream itself.
- `validate_cards.py` adds answer-aware overlap warnings and `roi_report.py`
  reports the same clusters; review feedback is a trim/merge signal, not an
  expansion mandate.
- The Finish button gets a one-shot spotlight/bounce when the last score is
  assigned, with a reduced-motion fallback.
- macOS: PyMuPDF is pinned below 2.0 for Intel wheels, and runtime scripts add
  Homebrew's bin directories when GUI-launched opencode omits them.
- Media cards use one footer source line with channel, title, playlist,
  timestamp, and URL; the duplicate `Image:` line is gone.
- Late high/confirm frames within a shot are preferred; a coarse visual-only scan
  covers videos with no useful cues or no attachable frames.
- `roi_report.py` reports image coverage per topic and topics with no images.
- Video extraction paces subtitle requests, reports skipped/failed videos in a
  structured summary, and never uses agent sleep/poll loops.
- `image-vision/scripts/vision_check.py` adds fast, cached frame confirmation with
  a flash-lite model fallback and bounded 503/429 retries.
- yt-dlp retries transient failures with short bounded backoff and skips permanent
  ones; the skill explicitly forbids sleep/poll loops for rate limits.
- Token discipline: independent review edits are batched in one step; deck scripts
  are written per topic rather than one huge file; subagent summaries are one line
  per fact. Maintainer code changes use `ponytail` at `ultra`, keeping diffs
  minimal and replies short. Agents never spawn an `opencode` child process
  (including `debug`) or recursively invoke the skill; shipped scripts run directly.

### Fixed
- Cached VTT files are reused instead of re-downloaded or lost to a failed retry.
- A shared media file referenced by multiple cards is no longer treated as
  duplicate work; both notes keep the same bundled image.
- `extract_video.py` no longer shadows the `index()` function with a loop variable.
- yt-dlp output with an extension (`vid.mp4.webm`) is found instead of reported as
  a download failure.
- `frames.md` is no longer overwritten by each video.

### Notes
- Vector diagrams in PDFs are still deferred; embedded raster figures are covered.
  The same applies to vector-only PowerPoint slides.
- `--max` is a safety cap, not the selection policy.
- Deck revisions of already-imported Anki collections (stable note IDs,
  update/retire reports, AnkiConnect) are deferred to v1.5. See `MAINTAINERS.md`.
- Tests now include adversarial PPTX fixtures, tag-leak errors, answer-overlap
  false-positive controls, media-reuse package checks, vision budgets, PATH
  fallback, and mutation probes for the new guards.

## v1.3.2 — Foundation-first new-card order

### Added
- New notes are added in source topic order: each topic's `tier_zero` card first,
  then L1, L2, and L3/Procedure in authored order. The sort is stable, so ties
  keep source order.
- With `--merge-existing`, only the new notes are ordered; existing scheduling is
  untouched.
- Anki's New Card Sort Order can override the order; docs point to "Order gathered".
- Smoke tests check both the pure order and the built deck's `due` sequence.

## v1.3.1 — One-command install and review polish

### Install
- `install.sh` now runs `setup.sh` and the doctor automatically after installing
  the skills. `--no-setup` skips dependency work.
- `setup.sh` installs only the missing system packages: Homebrew formulae on
  macOS, or apt/dnf/pacman with sudo on Linux. It installs the Python libraries
  and runs the doctor, printing doctor output only when a core check fails.
- Homebrew is never installed. If it is missing on macOS, setup stops with one
  install line.
- Anki is never installed. Detection now covers `/Applications`, `~/Applications`
  and Spotlight on macOS, plus PATH and Flatpak on Linux, so an existing app is
  not reported as missing.
- `bootstrap.sh` stays a documented three-step downloader and passes flags
  through to `install.sh`.
- `smoke.sh` fails if the repo installer and the handoff installer differ.
- Install docs describe the one-command flow.

### Review page
- The Finish button highlights once every card is marked, with separate Gruvbox
  Light (`#076678`/`#fbf1c7`) and Dark (`#83a598`/`#1d2021`) colors and a single
  gentle nudge. Reduced-motion disables the nudge.
- Saving the review now shows a done screen with a checkmark, a little confetti,
  a "tell your agent: done" instruction, and a Close tab button. It waits a few
  seconds, then tries to close the tab; if the browser blocks that, it says so
  and gives the Cmd+W / Ctrl+W shortcut.

## v1.3 — Video sources and shipping

### Added
- `extract_video.py`: YouTube single video/playlist, videos x–z, timestamped
  transcripts, manual/auto captions, no Whisper, full
  `<channel> - <playlist NN> - <video title> @ mm:ss` source labels.
- `frames.py`: 720p frame extraction, transcript cue detection, OCR/edge
  auto-picking, confidence, one best frame per cue, and optional manual `--at`.
- Video source survey: ask whole playlist vs range and whether to pull diagram
  stills; automatic frame selection only, no per-frame verification.
- Video media: one image per card, captions/sources, existing build/review media
  path; low-confidence frames stay in `frames.md`.
- Video references: full `<channel> - <playlist NN> - <video title> @ mm:ss`
  source line plus a plain, copyable timestamp URL; no hyperlink.
- Video tests: VTT parsing, playlist/range selection, synthetic-video frame
  extraction and auto-pick; no network in CI.
- Subject/tag breadth: topics are chapter/lecture headings; object tags are
  optional and should recur. Validator warns on one-card topics and one-off tags.
  Unit Circle stays one topic rather than `Radians`/`Sine`/`Tangent`.
- Frame confidence: low/medium frames are marked `needs_vision` and handed to
  the separate `image-vision` skill; attach only after diagram confirmation.

### Safety
- Personal study only; cite video/timestamp; no local Whisper in v1.3.

### Shipping and portability

- `VERSION` and `requirements.txt`; installer prints the version transition.
- Atomic cross-platform `install.sh`: stages both skills, verifies them, backs up
  the old install under `~/.claude/skills/.backups/`, replaces it, and leaves
  `~/.config/anki-gen` untouched.
- `setup.sh` for macOS, Debian/Ubuntu, Fedora, and Arch; prints system package
  commands and installs Python libraries into the user site. Never runs sudo.
- Platform-aware `doctor.py` fixes, version check, FTS5 check, and Linux Anki
  desktop detection.
- `INSTALL.md` matrix and generic `HANDOFF.md`.
- Offline installer/upgrade test in smoke.
- `AGENTS.md` dev workflow plus `changelog_check.py`: smoke fails if `VERSION`
  and the latest changelog section disagree or the section is empty.
- Package/shipping check: `package_handoff.sh --check` stages both skills and
  verifies installer/setup/doctor/docs/VERSION without building a zip; smoke runs it.
- `setup_macos.sh` is now a compatibility wrapper around `setup.sh`.
- `package_handoff.sh` includes `VERSION`, `requirements.txt`, `setup.sh`, and
  the rewritten installer; no zip is built by this change.

## v1.2 — Review fidelity, guards, and token discipline

### Changes (before → after)

Only changed values or behavior are shown here; new features are listed below.

| System | Before | After |
|---|---|---|
| Review preview | Cloze answers/hints showed literal `$...$` and `**...**` | Same renderer as the deck: `\(...\)`, bold, and hints render correctly |
| Feedback identity | Scores keyed by review-subset position | Keyed by card hash → note number → old index; reorder-safe |
| Scope gate | Classifier was told to read a stage-6 file that did not exist yet | Classifier classifies broadly; stage 6 filters before writing |
| Cloze policy | Prompts/schema showed whole-formula cloze, contradicting rule 15 | Basic for formulas/definitions/why; cloze only for enumerations |
| Formula sheet | Rule 21 was absolute (“zero cards”) regardless of given vs memorized | Given-at-exam → zero; must-memorize → card as recall |
| Stage 8 | A full LLM audit of the deck/corpus was possible | Layer 1 static only; Layer 2 is the batch check or triaged review |
| Card fields | `cloze`/`tier_zero` were missing from the stage/schema contract | Both are explicit; Procedure shapes point to their real section |
| Paths | `.jsonl` written, `.json` used downstream, triage plan left in cwd | `$WORK/cards.jsonl` and `$WORK/review_plan.json` everywhere |
| Extraction output | Full image/figure/processed-file lists printed | Counts plus samples; full data stays on disk |
| URL tags | Every URL tagged `https` | Last path stem (`lecture.pdf` → `lecture`) |
| Pipeline/media guards | `--gates-only` without cards was a silent no-op; missing media root exited 0 | Exit 2 for the no-op; exit 2 for a missing root; exit 1 when all sources fail |
| `source_ref` | Validator/review showed it; shipped deck dropped the footer | Footer preserved in the `.apkg` |
| Code-span audit | `<code>$</code>` flagged as a stray `$` | Code/pre spans ignored by the delimiter check |

### Numbers (measured, not controlled)

- **99-card MA2034 midterm:** 905,353 input, 17,140,608 cache-read, 246,784 peak, 148 tools, 70 edits.
- **67-card linear algebra:** 148,110 input, 6,623,104 cache-read, 147,907 peak, 74 tools, 12 edits.
- **12-card binary/SI bench:** 45,160 input, 465,280 cache-read, 46,505 peak, 20 tools, 0 edits.
- **Validation:** 20 smoke checks pass; 67/99/61-note decks validate with 0 errors (Materials has 1 pre-existing near-duplicate warning).
- **Caveat:** the 99-card and 67-card runs are different decks; the contrast shows the edit/tool pattern, not a causal result. The 12-card bench ran before the final review-fidelity and guard fixes.

### Review modes
- The 1–5 scale is the primary review.
- The recall (y/n) check is a second pass with its own default log
  (`review_recall.jsonl`), so it cannot overwrite the scale scores.

### Token discipline
- Batch authoring: a one-line-per-card ledger, then 10–15 cards per topic; no
  one-card edit loops.
- Read allowlist: chosen sources, learner context, and the stage reference; no
  unrelated handoff/tool/deck read-backs.
- Review handoff for >50 cards; chunk only if the build still peaks >150k.
- Self-correction is allowed: reproduce, smallest fix, smoke, changelog.
  Reasoning per card and heuristic coverage are the invariant.

### Control-flow audit
- Classifier classifies broadly; the scope gate filters before writing. On a
  re-run it reads `scope_gate.md` if present.
- Cloze is canonical for rule-15 enumerations only; formulas/definitions/why use
  Basic. Formula-sheet cards distinguish given-at-exam from must-memorize.
- Stage 8 is Layer 1 static only; Layer 2 is the batch self-check or triaged
  review, never a full-deck corpus audit.
- Stage 7/schema expose `cloze: true`, `tier_zero: true`, and the deck-script
  convention; Procedure shapes point to `card-writing.md`.
- `$WORK/cards.jsonl` and `$WORK/review_plan.json` are used consistently; triage
  writes the plan into the work directory, and cleanup reads `review_handoff.md`
  before deleting.
- Extraction stdout caps images/figures/processed files; full data stays on disk.
- Prompt header says read only the stage's prompt; `card-writing.md` has a rule
  map; the read table distinguishes lookup from mandatory reads.

### Review fidelity
- Cloze deletion bodies and hints render through the build renderer, so review
  shows `\(...\)` and markdown as the deck will, not literal `$...$`/`**...**`.
- Feedback is keyed by card hash, then note number, then the old index, so a
  reordered or regenerated review plan cannot attach a score to the wrong card.
- Smoke covers cloze preview fidelity and hash-keyed feedback, including legacy
  index-only logs.

### Guards
- `source_ref` cards now keep their provenance footer in the built deck.
- `pipeline.py` exits 2 for `--gates-only` without `--cards`, and exits 1 when
  every source fails; `media_index.py` exits 2 on a missing root.
- URL sources use the last path stem as their tag, not `https`.
- `validate_apkg.py` no longer treats `$` inside `<code>`/`<pre>` as a stray
  delimiter, and a crashed render check is now an error.
- Smoke covers the source-ref footer, URL tags, code-span audit, and CLI guards.

## v1.1 — macOS handoff kit

### Added
- `doctor.py` and `setup_macos.sh`, user-site Python installs, manual Anki
  import, an install/package handoff zip, and the `image-vision` key-file
  fallback.

## v1.0 — Base build

### Local build
- PDF/text extraction, card writing, static validation, Anki build, and a local
  review page.
- Rules, stage prompts, and card-writing detail all inline in one `SKILL.md`.

### Compact core
- Split `SKILL.md` into a small always-loaded core plus references (prompts,
  card-writing, review, lessons, optional); all 27 rules retained.
- `topic` is a chapter name; `objects` are the sniper tags; cleanup is
  default-delete.
- Merge is idempotent for notes and notetypes; the unread schema and backups were
  removed.

### Media support
- Opt-in images: `figures.json` + `media_index.py`, media entries with
  side/caption/source, Pillow downscale, classic media packaging, `/media/` route,
  and a bounded image review sample.
- Handwritten/scanned sources point at the separate `image-vision` skill instead
  of OCR or model vision.
