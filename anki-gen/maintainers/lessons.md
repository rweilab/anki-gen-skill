# Regression lessons

Architecture/token postmortem: `MAINTAINERS.md` (not loaded by the skill).

## Regression lessons


Behaviour changes, leading with the why; the rule or section carries the full reasoning. Kept short
because these are the failures that are invisible until they bite.

### Cold-start failure modes

A fresh agent given only `SKILL.md` still tends to:

- skip `intake.md`, `scope_gate.md`, or `kcs.md` because the request feels small;
- read every reference up front instead of the current stage's section;
- treat the 10–15 batch size as a deck target, or treat `--max` as a card cap;
- run `validate_apkg.py` again after the pipeline already did the real import;
- attach media because frames were extracted, although media is opt-in;
- omit the quality/manual-review status or claim a sample review certifies the deck.

These are prose-only guards. Use them in audits; do not turn them into new scripts or hard gates.

- **`--merge-existing` duplicated the whole deck on re-run.** Cards already present are now skipped
  by GUID, with the count printed.
- **A true back can still miss the answer.** A fructose-1,6-bisphosphate card asked “which
  enzyme?” but explained the split without naming **aldolase**. The validator now errors on an
  explicit “which enzyme” front with no enzyme name; the card-writing rule is answer-first.
- **The model read frames instead of letting the pipeline choose them.** Main-model vision made 23
  image reads on a 154-card deck (21% of tokens, 28% of tool calls); ambiguous frames now go to the
  separate cached `image-vision` pass, with no contact sheets or scan galleries.
- **`pgrep -f`/`pkill -f` can match the shell running the command.** A long vision run was stopped
  with `kill $(pgrep -f vision_check.py)`; the pattern matched its own command line and the stop
  timed out. Capture the child PID (`$!`) or use a bracket pattern.
- **A PPTX probe for LibreOffice was a workaround, not a requirement.** `.pptx` is a ZIP of XML;
  `extract_slides.py` reads text/notes/embedded images directly. Vector slides are cited, not
  rendered.
- **Tags are front-visible.** A one-topic object tag that appears only in the answer is now a
  validator error; a Bernoulli-substitution card cannot be tagged `bernoulli`.
- **Tests must fail on a broken implementation.** New guardrails have mutation probes; a passing
  mutation means the test, not the code, needs fixing.
- **A check against a schema that no longer exists is not a check.** `validate_apkg`'s cloze guard
  read `col.models` and `templates.qfmt`; modern Anki leaves both empty, so it silently passed
  everything. Derive the ordinal count from `notes.flds` and test a one-deletion note (which the
  old count comparison would have rejected).
- **Card identity must follow card content.** An explicit `hash` field outlived a text edit, so a
  corrected card kept its old GUID and `--merge-existing` skipped the fix. Identity is
  `md5(front|back)`; stable IDs are a separate, deferred revision feature.
- **Smoke must leave no work behind.** A failure used to opt into keeping its temp tree, and the
  review sentinel defaulted into the caller's cwd. Clean by default, keep only on `KEEP_WORK=1`,
  and compare the working tree before/after.
- **`genanki` and `--engine` are gone.** That path could not produce a cloze deck Anki 26 opens,
  forced `genanki` on every import, and hashed with sha256 where everything else uses md5, so
  identity did not survive an engine change. `anki` is now a hard requirement.
- **`--strict` did nothing on the default path** (implemented only on the deleted genanki path). It
  now runs the static checks and refuses on an error.
- **`roi_report.py` has no built-in exam weights.** Coverage groups by `topic`; weighting is
  optional via `--exam-weights`; without it the report says so instead of printing dead "unscored"
  rows. Anchors come from `tier_zero`, not phrase-matching.
- **Review is a triaged subset.** `triage.py` always runs; `--plan` renders its choice with a reason
  per card. The whole deck is still reviewable without `--plan`.
- **`render.py` no longer corrupts code spans or display-math lines.** It had run its math pass
  inside inline code (rendering a card that explained the delimiters as garbage, then blaming the
  author's stray `$`) and deleted prose sharing a line with `$$...$$`. Own-line display blocks
  render byte-identically.
- **Card identity has one definition** (`scripts/cardid.py`): builder, review server and triage all
  derive `md5(front|back)` from it, so a review score and a note GUID agree by construction.
- **`triage.py`'s format axis keys on `stratum`**, so a deck-authored sub-kind earns its own exemplar
  instead of being *reported* as "0 of 3 shown" with no mechanism to fix it.
- **The review budget is breadth-first** — measured: `--per-topic 1 --max 30` showed 20 cards over
  19/19 topics; `--per-topic 3 --max 24` showed 24 over 16/19.
- **The card face leads with the topic; tags are a sniper.** `META` was `{{Layer}} · {{Topic}}`, so
  every card was headed "L2", and the tag set was `[topic, layer]` — a tag returning every
  understanding card and saying nothing about the subject. The face shows the topic; the layer ships
  as a field and reads as a word (`Recall`/`Understanding`/`Boundary`) where a human sees it.
- **New `objects` field: 0–2 tags naming the specific things a card is about.** A topic tag returns
  everything relevant (shotgun); an object tag returns the cards specifically about a thing
  (sniper). A card on vacancy concentration in copper gets `#vacancy_concentration` and `#cu`, not a
  third tag restating its topic. `validate_cards.py` enforces the cap, rejects a layer code in
  `topic`, flags an object that duplicates the topic (Anki folds tags case-insensitively and would
  drop it), and reports the object census to catch singleton tags.
- **Object tags are how "related notes" works.** Rule 26 forbids a back pointing at another card; a
  related-notes footer is the same thing and goes stale. "Every card about FCC" is a tag query.
- **Status lines while it runs.** Short plain-language status is encouraged at every level, replacing
  "never narrate the pipeline"; what stays banned is *jargon* narration — stage numbers, layer codes,
  validator output. The estimate is a hedge, never a promise; the write stage is the only slow part
  and its length depends on the material.
- **The review URL gets one sentence** — what the page is and to come back when done — then the URL
  alone on its own line, so it stays paste-able. A beginner who has never seen the page needs to
  know what it is; a bare URL told them nothing.
- **`rejected.json` / `--rejected` are gone; a 5 is handled by editing the source.** The tombstone
  could not hold — a re-scope rewrites card text, so a reworded rejected card carried a new hash and
  slipped the filter — while adding a file and a silent stale-list failure mode. `cardid.py` keeps
  `card_hash` and `last_row_per_card`.
- **The deck audit is opt-in.** The web review runs by default on first generation; later changes ask whether to reopen it.
- **Three gates no longer block a beginner** — the source survey proceeds on stated assumptions, the
  deck audit is skipped, and the trim list moves into the report.
- **Cleanup is explicit and default-delete.** Stage 14 is a checklist: the `.apkg` is the only new
  file in the caller's cwd, the work directory is deleted in full, and a hand-authored source is
  promoted only to a caller-named path — never to a folder the agent invents. (A run that left a
  `midterm1_deck/` folder behind is why this is a checklist.)
- **Rule 26, no cross-card pointers.** Only *stale* pointers were called out before, missing the
  structural case: the reference resolves to nothing on the one screen where it is needed.
- **The formula sheet is a question, not a rule.** "Do not card what the sheet prints" is wrong for
  a reference deck. The high-value half survives: when the sheet is given, the deck's mass moves to
  its absences and the decisions around each equation.
- **Boundary cards became a calibration axis.** The L3 exemption is a default, not a law; a learner
  who prefers boundaries as decisions gets the same content reframed.
- **The review page had no JS smoke test.** An undefined helper (`layer_word`) left `#sheet` empty
  while the page loaded; only a browser console showed it. The lesson: after rendering the page,
  assert the first card is in the DOM, not just that the server returned 200.
- **Media is opt-in and human-audited.** A default build must carry no media files; the review
  samples image cards and shows a missing-file placeholder. Model vision is never assumed —
  uncertain figures are dropped and listed, not guessed.
- **Text-first is the default; `image-vision` is external.** Handwritten/scanned sources are
  transcribed with `image-vision` (Gemini), not OCR'd by the builder. Never build a deck from
  an empty extract; attach a figure only on request and audit it.
- **Over-cap images are downscaled, not skipped.** Pillow (optional, image builds only) shrinks to
  1600 px and re-encodes; EXIF orientation is applied on re-encode. Only a file still over 1 MB is
  dropped, so good web images are not lost to a strict pixel cap.
- **Anki's exporter writes a stub `collection.anki2`** for legacy readers (the real data goes in
  `collection.anki21`), so it cannot be used here. The builder hand-writes the classic layout:
  `collection.anki2` + a `media` JSON map + numbered files.
- **Token discipline is a workflow, not a card cut.** Batch 10–15 cards after a one-line ledger;
  read only the allowlist; phase-split large reviews. The 2026-10 MA2034 audit: 67 one-card edits
  and a 77k script read-back made a 99-card build 905k input; a 67-card build with 2 writes + 11
  edits was 148k. Reasoning per card and heuristic coverage are the invariant; card density is not
  a token lever. If a rule or script is wrong, fix it yourself: reproduce, smallest edit, run
  `smoke.sh`, add a changelog line. No lock.
- **Removed:** `deck_audit.py` (never scored anything), `parse_intent`'s `--resume` (its session
  directory was never created), `schemas/intent.json` (read by nothing), Image Occlusion and Type-in
  templates (no notetype implements them), and the lettered check labels (`A3`, `B4`) in favour of
  rule numbers.

## Architecture failure modes

Observed on the PH2023 v1.5.4 run; use these as audit patterns, not new gates.

- **The run was 298 tool calls and 38.3M cache for 89 cards.** 76% of cache was after the first
  review. Initial authoring was ~24%; the rest was review/fix loops.
- **138 edits.** 16 media edits, 59 review edits, 51 MathJax edits, 9 mid-run adaptation edits.
  The one-card edit loop is the largest avoidable cost.
- **The MathJax pass was 51 edits for 51 symbols.** A global formatting change should be one
  rewrite. The gate now warns on bare `X_y`, so the model can author it correctly the first time.
- **The `<br>` fix used five builds and five gates.** The source was fixed, but the final
  formatting was not visually re-reviewed. A formatting change needs one rendered-card check.
- **The second adversarial pass returned zero output on a length limit.** It was not a pass.
  Treat no-output/length-limit as not run; do not rerun after a formatting-only change.
- **The mid-run v1.5.4 schema change forced four gates, nine edits, and a build.** Do not edit the
  live skill during a deck run; a gate schema cannot change under a running model.
- **The model read the full 27KB card-writing guide, 20KB review guide, and 45KB study log before
  authoring.** It hit 220k context before the first review. Intake opens only `survey.md` and the
  study-log calibration summary.
- **The final built fields contain real `<br>` HTML tags and zero escaped `&lt;br>`.** That is the
  renderer's hard-break output, not source text. The review page was not reopened after the fix;
  that was the verification gap, not the HTML.
- **Residual quality defects survive a clean gate.** Card 6 still had plaintext `Vsphere`/`Asphere`;
  the first adversarial pass flagged one and it was not fixed. The one-rubric review and MathJax
  rule exist to catch that earlier.
- **The 89-card deck stayed under its own `Ceiling: 90` and used 23 KCs, not a 1:1 map.** The
  KC value policy worked; the problem was post-review edit discipline, not card-count pressure.

### Review and knowledge-component lessons

- **A review log that is not a build input is advice, not a loop.** The web page can be perfect and
  the deck still unchanged. `review_actions.md` is the missing handoff: score 1 rescopes, score 5
  removes, score 4 diagnoses, and the build refuses an unresolved file.
- **A locator is not evidence.** `source: "Lec 04 p.12"` proves only that a citation string exists.
  The `evidence_quote` check is what catches a plausible claim the extract does not support.
- **`tier_zero` is not a prerequisite graph.** It is one anchor boolean. `kcs.md` and its
  `requires` edges are the actual coverage/dependency contract; do not grow another boolean.
- **Do not turn KC into a second ontology.** One compact table in `kcs.md`, one `kc` per card and an optional
  `stratum`; the KC `type` is the preferred family. If a field does not improve coverage, review rescoping, or
  grounding, it does not belong.

### v1.5.4 alignment lessons

- **A large action space is the failure mode.** The 1.5.3 run used 161 tool calls, 29.7M cache, and
  312k peak context for 53 cards. The cause was not the model; it was the 16-stage table, five
  authoring paths, diagnosis commands, and the per-card ledger all looking legitimate.
- **A compact KC map is not a ledger.** `kcs.md` is a concept-level value/coverage model. Single-card
  KCs are allowed when the card is a complete high-value decision; `why` is the value case. A
  1:1 map warns; duplicate claims are errors. Do not force filler cards to satisfy a count.
- **One gate surface.** `pipeline.py --gates-only` prints exact errors with fixes and writes
  `gates.json`; a second validator call is a regression.
- **No magic numbers.** The model writes its budget from scope in `intake.md`; runtime rules are
  structural and scale-free.

### v1.5.3 build-cycle lessons

- **A 147-call run is an alignment failure, not a model failure.** The skill's ~25-step budget was
  not enforced by the normal path. One extraction call, `.jsonl`, one gates call, one packet, one
  build; if a command does not advance an artifact or resolve a gate, do not run it.
- **A full-deck/full-source adversarial prompt wastes the reviewer.** Give it `review_packet.md`
  only. The reviewer is a heuristic checker, not a corpus reader.
- **Image-vision is a time-intensive tool, not a media default.** Confirm only images about to be
  attached, after card text exists. No mode, no fixed count; card need is the budget.
- **A source read while extraction is running is a partial read.** Use one synchronous extraction
  call and wait.
- **A one-card KC is not automatically a card label.** It is allowed when the `why` is specific and
  the card is a complete decision; single-card `concept`/`mechanism` KCs are flagged for review.
