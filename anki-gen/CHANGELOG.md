# Changelog

Newest first. Keep the index to one line per release; details live below.

- **v1.3.2** — Foundation-first new-card order
- **v1.3.1** — One-command install and review polish
- **v1.3** — Video sources and shipping
- **v1.2** — Review fidelity, guards, and token discipline
- **v1.1** — macOS handoff kit
- **v1.0** — Base build

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
