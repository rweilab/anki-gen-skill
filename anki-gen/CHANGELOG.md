# Changelog

Newest first. Keep the index to one line per release; details live below.

- **v1.5.8** — Fixed 12-card review, live-deck inspection, sync plans, and dossier-only snapshots
- **v1.5.7** — JSON review actions, intake scope, revision boundary, and final card schema
- **v1.5.6** — One maintainer read order, one installer, route-first runbook, and gate plumbing cleanup
- **v1.5.5** — Default quality path, opt-in revision context, one quality contract, and design axioms
- **v1.5.4** — Seven-step runbook, compact KCs, exact gates, and explicit done states
- **v1.5.3** — Review rescope gate, KC map, and evidence grounding
- **v1.5.2** — Installer resilience and whisper.cpp fallback for local audio
- **v1.5.1** — Always-loaded quality gate, stricter media/video selection, and pipeline quality status
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

## Deferred to a future version

These are deliberate, not forgotten:

- **Post-import learning loop.** AnkiConnect already exposes review history; a future version can
  map leeches and true retention back to cards/KCs and feed exam errors into rewrites. It is too
  much surface for this pass and most users will not re-run the skill a month later.
- **Deck spin-off.** Copy selected live notes into a new deck with fresh scheduling; the source deck
  stays untouched. Deferred because the current build/revision paths cover present needs and it adds
  a new AnkiConnect surface and test matrix.
- **FSRS / deck-option configuration.** Deck review settings belong to the user; the skill should
  not overwrite them.
- **Full semantic duplicate detection and per-deck analytics.** Useful later; not on the critical
  path for the KC/review work.

## v1.5.8 — Fixed review sample and safe live-deck sync

### Changed

**Review**
- `pipeline.py` no longer accepts `--per-topic`/`--max`; the review set is fixed at 12. Risk and
  format axes are never dropped. The page still reports what was not shown.
- Certification is an explicit all-card review-server pass; the default sample is never called
  certification.

**Revision**
- `revision.py decks` lists deck names/IDs. `revision.py inspect --deck` dumps live notes, fields,
  tags, cards, models, and dossier/snapshot counts read-only.
- `snapshots --create --reason` takes a dossier-only checkpoint without applying.
- `sync --deck --cards` writes a read-only plan that matches by `rev_id`, content hash, then
  normalized front/back; ambiguous matches require `--map`; unmatched live notes become a retire
  group.
- `apply` accepts `add` actions from a sync plan. New cards get dossier records and apply-log
  entries.
- Snapshots and revision backups stay under the dossier; there is no legacy `anki/<deck>` path.

**Media and rendering**
- Images now default on for figure-bearing PDFs as well as slides/video; only a confirmed
  text-only source or explicit caller no turns them off. A gates warning surfaces
  `images: no` when extraction found figures, without blocking an intentional opt-out.
- `direct` figures may attach on high-confidence deterministic evidence; `confirm` figures
  require image-vision or explicit caller approval. Stale “vision first for every candidate”
  prose is gone from `SKILL.md`, `authoring.md`, `video.md`, and the changelog. `media_index` is
  only a text shortlist. A bounded main-model fallback remains available when image-vision is
  unconfigured, has no usable model, or stops on a rate limit; label it unverified.
- The renderer unwraps math-only code spans, splits known section labels into paragraphs, skips
  escaped dollars, and normalizes doubled MathJax delimiters. The validator warns on code-span
  math and unseparated section labels, and errors on LaTeX outside math.
- Raw structural HTML in card source now warns: built fields are HTML, authoring is Markdown.
  HTML/CSS-learning cards can still show tags inside code spans.

**Reliability and contract**
- Removed the unused same-context self-audit from `review.md`; the rubric is shared by the
  adversarial reviewer and the human page. The adversarial pass is mandatory when a read-only
  subagent exists, not caller-optional.
- Replaced old rule/stage numbers in runtime references with their current names. The glossary
  check is documented as a warning, and `evidence_quote` is documented as a KC field only.
- A failed post-build validation no longer leaves an `.apkg` in the caller’s directory; the build
  writes beside the target and publishes only after validation.
- `_extracted_figures` reads the state key the extractor writes, and `Ceiling:` accepts a list
  marker. Missing built-in Basic/Cloze notetypes now produce an actionable error.
- `validate_apkg` imports the package once and runs render/media checks on that collection.
  The render check degrades to a warning if Anki’s private API changes; `anki` is pinned below 27.
- The installer restores the previous skills if the second swap fails.
- The review server rejects cross-origin and non-JSON feedback. Review cards now show the object
  tags the build will ship, and cloze backs include front images.
- Added `scripts/schema_types.py` for the JSON shapes that cross module boundaries.

### Tests

- Revision hardening covers `decks`/`inspect`, `snapshots --create`, sync update/add/retire, and
  duplicate-footer prevention.
- Pipeline hardening covers the figure-count warning without blocking, bullet `Ceiling:` parsing,
  state-backed figure counts, and failed-validation cleanup. Render/validator hardening covers the
  capacitance-deck code-span/label failures, escaped dollars, doubled delimiters, and raw HTML
  source.
- The smoke docs audit now fails on stale rule/stage numbers, the removed self-audit, glossary
  severity drift, `evidence_quote` as a card field, and the old media policy. It also checks
  cross-origin/non-JSON feedback rejection and cloze front-image fidelity.

### Compatibility

- Review flags are removed, not deprecated; old commands with them fail fast.
- `sync_plan.json` is a transient apply plan; no migration or compatibility guarantee.
- No existing dossier schema changed.

## v1.5.7 — JSON review actions, intake scope, revision boundary, final card schema

*This release finishes the internal contract cleanup without trimming the runbook or changing
card generation.*

### Changed

**Review and scope**
- `review_actions.json` replaces `review_actions.md` for new runs. It carries `feedback_sha`, so
  staleness is content-based; score-1 actions/targets and score-5 removals are checked by field.
- Legacy `review_actions.md` remains readable for old work directories. New gates never write it.
- Scope now lives in `intake.md` § Scope. `scope_gate.md` remains a read-only fallback for old work
  directories.
- `SKILL.md` keeps its atomic rules; only the changed contract text moved.

**Revision boundary**
- `pipeline.py` no longer imports `deck_context` or dossier code.
- `--context` calls `revision.py context pack`; core and revision stay separate without moving files
  or changing install paths.

**Removed dead surface**
- Deleted `author.py`, `new_cards.py`, and `parse_intent.py`; they were not on the runbook path.
- Removed `--vision`, `--vision-max`, `--vision-seconds`, `--vision-timeout`, and the duplicate
  vision pass. The separate `image-vision` skill is the normal path.
- Removed `--manifest-full` and `--allow-media-risk`; `roi_report --deep` left the
  documented surface.
- Kept `--no-context` and `--deep` as hidden no-ops for old commands; removal target 2.0.
- Kept `preflight`, `--status`, `--allow-invalid`, `--context`, and `--merge-existing`.

**Card schema**
- Required fields are now `front`, `back`, `layer`, `topic`, `source`, and `kc`.
- `deck` is legacy and optional; `--deck-name` is the single source. The dossier falls back to the
  manifest deck name.
- `cards.jsonl` is the write format; `cards.json` remains read-only for old work directories.
- New fields must be optional; unknown fields are ignored by the gate and preserved by the dossier.
  There is no per-card schema version.

### Docs

- Consolidated user install/use guidance into the root `README.md`; the handoff zip
  ships it as `INSTALL.md`.
- Removed duplicate `HANDOFF.md` and `scripts/handoff/INSTALL.md`.
- Shrank `anki-gen/README.md` to maintainer/vendoring notes.
- Corrected image defaults: slide/video images are on by default; text-only sources
  are text-first and the caller can decline.

### Compatibility

- Old `cards.json`, cards with `deck`, old `scope_gate.md`, and old `review_actions.md` still work.
- No change to `.apkg` output, build validation, review page, or install defaults.
- No new compatibility shims; the legacy review/scope paths are read-only and have a 2.0 removal
  target.

## v1.5.6 — One source for maintainers, one installer, route-first runbook

*This release is a safe-20% hygiene pass: it removes parallel paths and duplicated ownership
without changing card generation, artifacts, or field contracts.*

### Changed

**Maintainer docs**
- `AGENTS.md` is now the single maintainer entry point: read order, documentation architecture,
  change workflow, cold audit, and boundaries.
- `MAINTAINERS.md` keeps the quality contract, design axioms, rule ownership, and deprecations;
  duplicate boundaries/changelog/index and experimental postmortem moved out.
- `maintainers/lessons.md` owns regression lessons and architecture history.
- `maintainers/dossier-format.md` owns revision schema and the v1.5 implementation map.
- Removed `maintainers/README.md` and `maintainers/cold-audit.md`; their content is in `AGENTS.md`.
- Added `MAINTAINERS.md` § Deprecations with removal targets. Legacy authoring scripts are
  frozen, not wrapped.

**Runtime and docs**
- `SKILL.md` starts with a route-first block: new deck, existing imported deck/spin-off, or
  handwritten source.
- `SKILL` is now the skill directory, not a hardcoded `~/.claude/skills/anki-gen`.
- `references/revision.md` now matches the code: `--context` is opt-in; `--no-context` is a
  deprecated no-op.
- `cards.jsonl` is canonical in docs; `cards.json` remains accepted for old work dirs.
- `references/rendering.md` describes JSON escaping, not Python raw strings.
- Stale old rule numbers were replaced with section names.

**Installer and packaging**
- One root `install.sh`; removed the duplicate `scripts/handoff/install.sh` and the copy-sync test.
- `package_handoff.sh` now checks invariants and rejects junk/secret files instead of maintaining
  a per-file allowlist.
- Installer default remains `~/.claude/skills`; `ANKI_GEN_SKILLS_DIR` is documented for
  `.opencode/skills` and `.agents/skills`.

**Internal**
- `roi_report.report()` is a pure function; `pipeline.py` no longer swaps `sys.argv` or captures
  stdout.
- Gate fix hints moved to `validate_cards.fix_for()`.
- `preflight.py` resolves backups from the skill root, with a `~/.claude/skills` fallback.

### Compatibility

- No changes to `.apkg` output, card schema, `deck`, `scope_gate.md`, `review_actions.md`, or
  existing flags.
- `cards.json` and old work directories remain readable.
- No new compatibility shims.

## v1.5.5 — Default quality path, opt-in revision context, one quality contract

*This release closes the v1.5.3–v1.5.5 alignment reset: KCs made coverage concept-level, the
16-stage spec became a seven-step runbook, and the quality path became the default so a capable
model has fewer places to drift.*

### Changed

**Defaults**
- The adversarial reviewer is now the default when a read-only subagent is available. It runs after
  the web review opens, reads `review_packet.md` only, and never blocks the human review. Skip only
  when no subagent exists or the caller declines. No output or a length-limit finish means not run.
- Images default on for slide and video sources, off for text-only sources. Ambiguous images still
  go through one batched vision pass; no per-image calls.
- Dossier packing is opt-in with `--context`. The default build leaves only the `.apkg`; revision
  context is explicit. `--no-context` remains accepted as a deprecated no-op.
- No-human path: skip the web page, say "not manually reviewed; static checks only," run the
  adversarial pass after the gates call when a subagent exists, and report `NOT REVIEWED`.

**One quality contract**
- `references/prompts.md` is reduced to the classifier and a short debloater note. The writer and
  verifier prompts are removed; their unique retrieval-angle and density guidance moved into
  `card-writing.md`.
- The old schema reference is merged into `authoring.md` and deleted. `authoring.md` now owns fields,
  card shapes, KCs, media, and batching.
- `references/review.md` now has one 10-item quality rubric used by the self-audit, the adversarial
  reviewer, and the human page. The duplicate self-audit and reviewer checklists are gone.
- `references/card-writing.md` is trimmed of duplicated KC, topic, and field prose, and its stale
  old rule numbers are replaced with the ten hard-rule references.
- `references/review.md` now checks text integrity and front/back relevance in the same rubric:
  no vague/orphaned fragment, truncation, page furniture, broken glyph, or back that answers a
  different question. Standard-looking symbols still count as undefined unless named on the card,
  and cross-context pointers (“the table above”) are hard fails. The validator warns on dangling
  endings, replacement characters, and generic fronts; semantic mismatch stays with the reviewer
  and human.
- Procedure review distinguishes equation selection from memory, allows problem data and an
  equation sheet, and fails final numeric values, worked/remaining solutions, and duplicate
  targets. A generic “calculate” cue is a FIX, not a hard fail. The validator recognizes
  equation/formula/relation/model/first-step decisions, and the classifier no longer excludes
  method/next-step problem-solving fronts.
- The noisy front-similarity heuristic and the enzyme-specific answer proxy were removed. `--deep`
  remains for answer-overlap checks; `roi_report --deep` remains the debloat path.
- Computation-front errors now name the offending verb and suggest a method/meaning rephrase.
  `Ceiling: N` is explicitly set before cards, from scope, so it cannot be back-filled to the
  number just written.
- Symbol-bearing cards without a glossary/definition line now warn instead of reporting info.
  The detector counts simple math variables and recognizes inline `where`/`let` definitions, so a
  formula-only back no longer counts as its own glossary.
- Yes/no fronts with yes/no backs now warn, and the adversarial instruction explicitly fails
  fronts that contain or cue their own answer and multiple-choice/recognition prompts.
- KC evidence cells accept matching straight or curly quotes; the gate strips them before checking.
  The single-card concept warning now says no filler card is required.

**Maintainer knowledge**
- `MAINTAINERS.md` gains `## Design axioms` (including the alignment-budget axiom: more systems and
  more context eventually reduce alignment), a decision ladder, a do-not-resurrect list, and
  research anchors with source links.
- `maintainers/lessons.md` gains `## Architecture failure modes` from the 89-card PH2023 run.
- `AGENTS.md` points maintainers at the axioms and research anchors, requires a cold dry-run
  after smoke for runtime changes, and makes “is there a way to reduce overall complexity?” the
  first question for every change.
- `MAINTAINERS.md` makes the same complexity question the entry point of its complexity budget:
  fewer systems, artifacts, commands, checks, gates, steps, and prose; if a change adds runtime
  surface, it must name what it replaces.
- `maintainers/cold-audit.md` records the dry-run protocol: a fresh agent reads `SKILL.md` and
  attempts the skill end to end in `/tmp`, then reports breaks and ambiguities. A clean run is not
  certification; passing tests only show expected paths do not syntactically fail.
- Legacy `author.py`, `new_cards.py`, and `parse_intent.py` remain available but are documented as
  legacy/test-only; deleting them would break external scripts and is not part of this cleanup.

### Notes

- No deck schema bump. Existing decks and dossiers still build.
- `VERSION` is 1.5.5.
- No new runtime command, flag, or artifact beyond `--context`; no media or revision split.

## v1.5.4 — Seven-step runbook, compact KCs, exact gates, and explicit done states


### Added

**Runbook and alignment**
- `SKILL.md` is now a 7-step runbook with 10 hard rules instead of a 28-rule, 16-stage
  specification. It names exactly three primary commands plus the review server.
- Stop rules now forbid background extraction, deck scripts, ad hoc card patches, tool-source
  reads, diagnosis commands, and confirmation-only commands. The model writes a run budget in
  `intake.md` from scope; there are no fixed card, KC, or tool-call quotas.
- New done states: `READY` / `READY WITH WARNINGS` at gates, and `DONE` / `DONE WITH WARNINGS` /
  `DONE — NOT REVIEWED` after a successful build. `NOT CERTIFIED` is retired as the default label.
- Gate output now prints exact errors and warnings with card numbers, plus a one-line `fix:`
  hint, and writes `gates.json`. The model no longer needs a separate validator call.

**KCs and authoring**
- `kcs.md` replaces `authoring_ledger.md` on the new path: a compact concept-level table, not a
  per-card ledger. Each KC carries a one-line `why` value case. Single-card KCs are allowed when
  the card is a complete high-value decision; a single-card `concept`/`mechanism` warns, a 1:1
  map warns, and exact duplicate claims are errors. No filler cards to satisfy a count.
- `stratum` is optional on a card; the KC `type` is the preferred retrieval family.
- `scope_gate.md` carries a `Ceiling: N` line; the gate warns when the deck exceeds its own
  ceiling and never auto-cuts.
- `cards.jsonl` is the only authoring format. The runbook removes `make_cards.py`,
  `new_cards.C`, and `author.py`; rewrite the file once instead of patching cards in a shell.
- `authoring.md` is rewritten for one-pass JSONL authoring, scale-free KC rules, reading
  discipline, and batched image confirmation.

**Extraction and build**
- `sources.md` is written atomically and gets a `sources.ready` marker. A live extraction lock
  refuses a second extractor in the same work dir; `--sources` accepts a directory and excludes
  the work dir automatically.
- `pipeline.py --build` requires `kcs.md` (or a legacy `authoring_ledger.md`) and still runs the
  real import validation in the same call.
- `--allow-missing-artifacts` now names `kcs.md`.

### Changed

- `validate_cards.py` makes `stratum` optional; accepts `# KCs` or `## KCs`; allows single-card
  KCs with a `why`; warns on single-card `concept`/`mechanism` and 1:1 maps; errors on duplicate
  claims; and keeps legacy `authoring_ledger.md` parsing for old decks and tests.
- `references/authoring.md`, `card-writing.md`, `review.md`, and `prompts.md` now describe `kcs.md`,
  optional `stratum`, and KC-level evidence quotes.
- The pipeline `NEXT` hint and evidence line point at `kcs.md`.

### Removed from the runtime path

- `authoring_ledger.md` as a required artifact; legacy files are still accepted.
- `make_cards.py` / `new_cards.C` / `author.py` from the authoring path.
- Separate validator, triage, ROI, extractor, frame, and builder calls as parallel model paths.
- `NOT CERTIFIED` as the default quality status.

### Post-audit hardening

- MathJax is the default for symbols and sub/superscripts: `$P_{0}$`, `$v_{0y}$`,
  `$\rho_{\text{oil}}$`. Bare `P_0`, `ρ_obj`, or `V_disp` is a validator warning; concatenated
  `Vsphere` is a review defect.
- A literal `<br>` in `cards.jsonl` is a warning; blank lines are paragraphs and two trailing
  spaces are the deliberate hard-break signal. The built HTML still uses `<br>` tags.
- A global symbol or formatting change is one rewrite of `cards.jsonl`, not one edit per card or
  symbol. A formatting change gets a one-card visual check, not a full review.
- The adversarial reviewer gets the packet, one line per sampled card. No output or a length-limit
  finish means not run; do not rerun it after a pure formatting change.
- Intake reads only `survey.md` and the source TOC; the full study log and stage references wait
  for their step.
- No new artifact, command, flag, or stage. `VERSION` remains 1.5.4.

### Notes

- No deck schema bump. Existing decks and dossiers still build.
- The optional adversarial review remains opt-in and reads `review_packet.md` only.
- Media stays a card field; the runbook batches confirmations and asks for one image per card.
- No `VERSION` bump is implied for future changes; this section matches `VERSION` 1.5.4.

## v1.5.3 — Review rescope gate, KC map, and evidence grounding


### Added

**Review loop**
- `triage.py` review plans now carry `stratum` and `kc`.
- `pipeline.py --gates-only` reads scale and recall feedback, prints a compact summary, and writes
  `review_actions.md` when feedback exists. Score 1 is grouped for rescope, not auto-cut; score 5
  is the only removal verdict.
- `pipeline.py --build` refuses while `review_actions.md` is missing, open, unset, stale, or
  incomplete. Every score-1 block needs a valid action and a non-empty target. The review page
  layout and controls are unchanged; the only visible copy change is the score-1 finish-summary
  sentence.
- `pipeline.py --gates-only` writes `review_packet.md`: selected cards, selected KC rows/evidence,
  scope, intake, and media captions only. The optional adversarial reviewer reads the packet, never
  the full deck or corpus, and starts after the web review is open.
- The pipeline prints deck shape (L1/L2/L3/Procedure and stratum counts) without gating it.
- `review_actions.md` is packed as optional dossier evidence when present.

**Knowledge components and evidence**
- `authoring_ledger.md` now starts with a compact `## KCs` map. Cards carry `kc` and `stratum`;
  `validate_cards.py` checks coverage, unknown KCs, unresolved prerequisites, standard strata, and
  rejects a standalone one-card KC (it must be a prerequisite anchor).
- `evidence_quote` lives on the KC map, not every card. The gate checks KC quotes against the
  extracted corpus; `derived` is the exemption.
- Stage 9b adversarial review receives the compact packet, including KC evidence, and runs after
  the web review is open. It never sees the full deck or full source.
- Card/dossier persistence records `kc` additively; old per-card evidence is preserved under
  `extra` and is no longer part of the schema. No schema bump.

### Changed

**Pipeline correctness**
- Mixed directories are split into media and document files instead of silently dropping the PDF.
- The normal runbook uses one synchronous extraction call with all sources; `.jsonl` is the default
  authoring path; `make_cards.py` is advanced only.
- `parse_intent.py` no longer emits the misleading `video_frames` field.
- Procedure Shape A is exempt from the computation-front gate only when the front explicitly asks
  for a method/next step.
- `validate_apkg.py` refuses to call a package valid when the `anki` library is unavailable; it
  runs structural checks, prints `STRUCTURAL ONLY — NOT IMPORT-VALIDATED`, and exits 3.
- `--strict` no longer exists as a no-op; validation is always the default.
- Dead `review_handoff.md` guidance is replaced by `review_actions.md`.
- Image-vision is used sparingly: only for images about to be attached, after card text exists;
  no mode or fixed image count.

## v1.5.2 — Installer resilience and local audio

### Changed

**Installation and local media**
- Setup now installs only `anki` and PyMuPDF as core. Optional image, YouTube, and
  local-audio libraries are installed one at a time, best effort; a missing wheel
  such as ctranslate2 on Python 3.15 no longer aborts the install.
- Missing Homebrew, sudo, system tools, pip, or optional wheels are warnings. The
  installer still installs the skill and reports exactly which features are off.
- Local audio adds a whisper.cpp fallback: Apple Silicon attempts it automatically;
  mainstream Linux uses faster-whisper when available, otherwise a distro package or
  a user-local tarball. The model downloads and is checksum-verified on first use.
  No Python 3.14 downgrade, venv, or PATH change is required.
- `doctor.py` reports the active local-audio backend in one line; `media_transcribe.py`
  falls back to limited metadata when `ffprobe` is missing, and to whisper.cpp when
  faster-whisper fails.
- Setup now prints `Full feature set: installed` or `Full feature set: NOT installed`
  with every remaining doctor warning. Core decks remain usable, and optional gaps
  do not fail the install.
- Missing `pandoc` now falls back to raw HTML, missing `curl` uses Python's URL reader,
  missing `yt-dlp` and `anki` produce feature/core messages instead of tracebacks, and
  missing `ffmpeg` is reported by the frame helper rather than crashing it.
- `parse_intent.py` no longer emits dead `sources`, `course_hint`, `recursive`,
  `max_cards`, or `output_path` fields. Local sources come from the request; deck size
  is the scope-gate ceiling. Stage 5 is explicitly in-chat, and stage 12 is diagnosis
  only because stage 11 already runs the real import.
- The no-formula-sheet case, deck-name question, media opt-in, cleanup comparison, and
  beginner quality line are explicit in the stage map. A maintainer note records the
  cold-start failure modes.
- Added optional **stage 9b adversarial subagent review** for decks where the caller opts in:
  the existing review checklist becomes a 0/1/2 rubric, the reviewer returns findings only,
  and it never replaces human review. Added a maintainer cold-audit protocol using two
  read-only STEM prompts plus smoke, child-process checks, and manual reasoning.

## v1.5.1 — Quality gate and media hardening

### Added

**Quality contract and review**
- An always-loaded **quality kernel** at the top of `SKILL.md`: self-contained fronts, the media
  bar, cloze context, why quality, review status, and the rule that validation is not quality
  certification.
- A pipeline **quality status** line and media/ROI risk summary. The status is `NOT CERTIFIED`
  after static checks and names media risks, ROI split candidates, and whether a review log exists.
- A **recovery rule** in the kernel: if a stage was skipped or a gate fired, stop, produce the
  missing artifact, and re-run the gate; never hand over a deck to get past it.
- A **semantic self-audit** after triage: one evidence line per sampled card, cold-answer and
  symbol checks, source-anchor check, Procedure check, and a parked list for low-ROI cards. It is
  explicitly advisory, not independent manual review.

**Media pipeline**
- `media_index.py` media-risk auditing: title/outline frames, unconfirmed `confirm` crops, generic
  captions, and front references to unseen images.
- Per-source and per-video progress (`[media i/n]`, `[video i/n]`), incremental `video_meta.json`,
  `pipeline_state.json`, `--status`, and playlist `--resume`. Interrupted and failed work is
  recorded instead of looking permanently “running”; resume retries rate-limited captions but
  skips permanent no-captions videos.
- A bounded main-model vision fallback: only when image-vision has no key or its one retry fails,
  the image is necessary to answer/attach a card, and the batch is at most 6 images. The result is
  labeled unverified.

**Authoring and context**
- `pipeline.py` writes one combined `sources.md` for a document batch, and the stage-5/classifier
  wording points document runs at `sources.md` and video runs at `transcripts.md`. The pipeline
  NEXT hint follows the same split instead of naming a file that does not exist.
- `new_cards.C(strict=False)` collects every card error; `dump()` prints them and refuses to write,
  so a large script can fix one batch instead of one error per run.
- `roi_report.py --list` prints card numbers, topics, layers, and fronts without pulling backs into
  the conversation.
- The authoring ledger is now a **card contract**: tier, retrieval target, one-sentence answer,
  why, every symbol and meaning, source evidence or `derived`, and the checks. The self-audit
  compares the finished card against it.
- The scope gate records a soft target count and a **parked** list. Parked candidates are not
  written, but they are kept with a reason instead of being silently deleted.
- A **procedure-familiarity walkthrough** is allowed as an L2 cloze: one card per procedure, first
  and last steps visible, 1–3 labeled middle blanks. It is separate from a Procedure decision card
  and is dropped once the learner knows the flow. The filter tag is the reserved
  `objects: ["procedural"]`.
- Stages 8, 9 and the first stage-13 report are one `pipeline.py --gates-only` call; the standalone
  validate, triage and ROI commands are diagnosis-only. This keeps one plan and one quality line
  per pass.
- Card-count language now treats 10–15 as a batch cap and 4–15 as a healthy ceiling, not a quota;
  the scope target is a ceiling, and low-ROI candidates are parked before writing.

**Verification and maintainer docs**
- Focused regression tests for title/outline frames, confirm-crop risk, self-contained fronts,
  labeled cloze, pipeline state/resume, the media-risk build block, empty transcripts, per-video
  resume, confirm-only vision, and the authoring scaffold.
- Adversarial smoke checks for the worst derailment paths: a build without `--deck-name` is
  refused, `validate_apkg` rejects a non-package cleanly, and a stale review plan aborts before
  serving cards. Smoke also audits internal doc paths and rejects references to retired files.
- `MAINTAINERS.md` gains a rule-ownership table (rule → contract → owner → code gate → duplicates)
  and a visible "Maintainer docs" section. Tests are documented as a floor, not proof of quality.
- `parse_intent.py --help` prints usage, a dossier path works as a `context` deck selector, the
  quality evidence line names `derived` cards, and the topic-tag warning distinguishes chapter
  context from an answer leak.

### Changed

**Media extraction and selection**
- `frames.py` marks title/outline/agenda slides as non-direct; `media_index.py` penalizes
  unconfirmed crops, title frames, and weak caption matches, skips cards that already have media
  by default, and caps flat-index output at 40.
- Vision confirmation is now restricted to `confirm` frames. `direct` frames are attachable
  without an API call; the bounded `pipeline.py --vision` pass no longer asks to confirm them.
- Frame paths are treated as exact. `frames.md` says to copy the backticked path, never rebuild a
  filename from a rounded timestamp.
- `vision_check.py` paces uncached calls at ~5 RPM by default (12-second gap); `--retry-429`
  permits one retry at a doubled delay, then stops. The 429 message names the free-tier RPM/RPD
  cause. `--max-seconds` now defaults to 600 for paced batches.
- `pipeline.py --build` refuses objective media risks unless `--allow-media-risk` is passed.
- The main-model vision rule is stated consistently: never for bulk media by default, with the
  bounded ≤6-image fallback as the only labeled exception; the failure lesson is preserved.

**Build, validation, and review**
- `validate_cards.py` warns when a front refers to an unseen image/example and when a multi-blank
  cloze lacks labels. The stage map notes `--deep` for soft overlap and `--json` for the full
  warning set, since the text view caps at 20.
- `validate_apkg.py` rejects a non-package with a clean error instead of a traceback.
- The web review runs by default on first generation. Later adjustment runs ask whether to reopen
  it; a declined review is reported as not manually reviewed.
- Score-1 clusters are treated as rescope evidence: merge into a harder L3 contrast/boundary card
  or drop trivial siblings instead of adding more of the same.
- The stage-11 command now includes the required `--out "$WORK"` work directory; `pipeline.py`
  refuses a build without one.
- `MAINTAINERS.md` and `AGENTS.md` now say tests are a floor, not proof, and forbid stopping a
  child with a literal-name `pgrep -f`/`pkill -f` that can match its own shell.

**Documentation, context, and maintainability**
- `SKILL.md` now carries a compact stage map (stage → command → gate → reference); the detailed
  stage areas stay in the contract, while extraction and media procedure lives in the owning
  references. The maintainer-only script-ladder paragraph moved verbatim to `MAINTAINERS.md`
  ("Change discipline"), and the duplicate authoring heading was removed.
- Maintainer-only references moved to `maintainers/` with a one-line `maintainers/README.md` index;
  `AGENTS.md`, `SKILL.md`, and the package check point there.
- Prompt topic/object definitions now defer to rule 27 and its owner; the point-of-use
  why/self-contained/cloze/source guards remain. Reference navigation now names rule 8
  (recallability) and records that frames are 720p stills.
- A line-by-line control-flow audit tightened the stage-8 `--deep`/`--json` wording, the VERIFIER
  opt-in static check, the video/local pipeline `--out` shorthand, the rule-11 gate label, and
  marked report-only ROI/tier-zero entries as signals rather than gates.
- `video.md` records that a full-series transcript can exceed 100 KB and be returned in sequential
  read chunks; that is not duplication, and it should not be split further.

### Fixed
- A header-only compact transcript (common after a caption 429) no longer crashes the whole
  playlist; it becomes a `_No transcript (...)._` placeholder and the other videos survive.
- Media state no longer stays `running` after a failure or interruption. A new run marks stale
  work `interrupted`, and `--status`/`--resume` can distinguish done, partial, failed, and
  interrupted sources.
- Playlists no longer appear as one opaque `[media 1/1]` unit; per-video progress and metadata
  show what is done and what remains.
- Confirm-only vision, exact frame paths, and clean background-process stopping remove three
  observed failure modes.
- `validate_apkg.py` no longer prints a traceback for a non-package; it fails closed with a clear
  message.
- `revision.py context import --dry-run` no longer raises `KeyError: 'path'`; it prints a dry-run
  summary and writes nothing.
- Dossier validation no longer warns `W_WHY` when a card has a why but no separate
  `retrieval_target`; it warns only when both are missing.
- Media selection no longer treats title slides, outline frames, incomplete crops, or
  whitespace-heavy frames as ready-to-attach.
- Cloze cards require labeled context, not bare values.
- A passing validator no longer implies a quality deck; the pipeline states what was and was not
  checked.
- A long media run now leaves a progress/state trail and resumes completed sources instead of
  disappearing behind a silent timeout.

### Removed
- The old `stage_media` temp-directory/symlink batch path; media is now processed one source at a
  time with the same work tree.
- The unconditional "web review is never offered" rule.
- The default unbounded `media_index` flat dump and the old 3–5-candidates-per-card guidance.
- The implicit recommendation of unconfirmed `confirm` crops as attachable media.
- The 0.5-second default burst pacing that caused RPM 429s; pacing is now ~5 RPM with one explicit bounded retry.
- The old `output.md` reference; its unique content moved to `survey.md` (deck naming),
  `revision.md` (GUID identity and merge), `authoring.md` (media opt-in), and the stage 11/14
  contract in `SKILL.md` (import and cleanup).
- The old `lessons.md` and `dossier-format.md` reference paths; the content moved to
  `maintainers/lessons.md` and `maintainers/dossier-format.md`.
- Duplicated media-extraction prose from `references/optional.md`; `references/authoring.md` and
  `references/video.md` own media policy.
- Unused `AnkiConnect` wrappers (`get_tags`, `retrieve_media_file`, `change_deck`,
  `set_due_date`); the allowed AnkiConnect verbs remain documented in `revision.md`.
- The unused `new_cards.load` re-export; callers use `cardid.load_cards`.

### Notes
- No current deck was retroactively repaired. The changes target future runs.
- Review UI text, CSS, JS, Easy button, and summary remain unchanged.

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
