---
name: anki-gen
description: Generate evidence-based Anki flashcards from lecture notes, PDFs, PowerPoint, homework, textbooks, YouTube videos, and local recordings, and review them in a built-in local web page. Use when the user asks to make flashcards or an Anki deck, turn course material into cards, merge a deck, or study with spaced repetition. Outputs .apkg for direct import.
---

# Anki STEM Flashcard Generator

Generate atomic, evidence-based Anki cards from STEM material, review them in a local page,
and build an `.apkg`.

Harness-agnostic: plain `SKILL.md` plus `scripts/`. `SKILL` is the directory containing this
file; on this install it is `~/.claude/skills/anki-gen`, but `.opencode/skills/anki-gen` and
`.agents/skills/anki-gen` work the same. The entry point is the only harness difference
(`/anki-gen` vs description match).

`$WORK` means `.anki-gen-temp/<filesystem-safe-topic>`, e.g. `circuits-midterm2`, not the
deck name with `::`. Slug it from the deck name: lowercase, replace `::` and spaces with `-`.
Every artifact lives there. The `.apkg` is the only new file in the caller's directory.

## Route first

- **New deck** from sources: follow the seven-step runbook below.
- **Existing imported deck**: read `references/revision.md`; use `scripts/revision.py` and
  AnkiConnect. Do not run the generation path. Deck spin-off is deferred; do not invent an
  AnkiConnect script for it. Never open, copy, query, or inspect the live collection DB, even
  read-only.
- **Scanned or handwritten source**: use the separate `image-vision` skill first,
  then the runbook.

## Quality kernel

These ten rules apply to every card. Read the relevant sections of `references/card-writing.md`
before writing; do not author from the source alone. If the harness cannot select sections, read
the file once at authoring, not at intake.

1. **Source-grounded.** Every card has a locator, or `source: "derived"` for self-contained math.
2. **One retrieval decision.** A wrong answer points to one thing to repair.
3. **One unambiguous cue.** Two experts would give the same answer; the cue does not leak it.
4. **Production, not recognition.** No computed answer on the front.
5. **Conditions on the card.** Assumptions, units, and symbol definitions travel with it.
6. **Near-miss discrimination.** The card separates the target from a tempting alternative.
7. **Answer first.** The first back sentence answers the front; the why adds mechanism,
   consequence, mnemonic, or use.
8. **Every symbol defined** on the card, with units, and written in MathJax: `$P_{0}$`,
   `$v_{0y}$`, `$\rho_{\text{oil}}$`, `$V_{\text{disp}}$`. Bare `P_0`, `ρ_obj`, `V_disp`, or
   `Vsphere` is a defect. Code spans are exempt.
9. **Self-contained front.** No “shown,” “this circuit,” or “the slide” without the image on
   the front. No cross-card pointers.
10. **Media bar.** Full slide/frame by default; crops need confirmation; one image per card;
    no title, outline, agenda, incomplete crop, or whitespace-heavy image.

A gate passing is not a quality certificate. The review is.

## The runbook

The normal path is seven steps. Do not invent a parallel one. The skill is deliberately small:
read only the current step's reference; do not read ahead. More context is not better.

1. **Intake.** Read the request and the chosen sources. Open only `survey.md` and the source
   table of contents for now; do not open `card-writing.md`, `review.md`, or `prompts.md`
   until their step. Read the learner-calibration fields in `survey.md`; if no learner context
   exists, assume beginner/cold and state it. Do not read the whole study log.
   Write `$WORK/intake.md`: deck name, learner context, sources, image yes/no, assumptions, and
   **your own budget** for this run (estimated extraction, authoring, review, and build calls
   based on scope). No fixed numbers.
2. **Extract.** Run one foreground extraction with all chosen documents and media. Wait for it
   to return. Do not background a second extractor; do not read `sources.md` until it exists.
3. **Author.** Read the source table of contents and only the per-source files you need. Add a
   `## Scope` section to `$WORK/intake.md` with a `Ceiling: N` line, and write `$WORK/kcs.md`. Then write
   `$WORK/cards.jsonl` in one pass per topic. One authoring format; no deck script.
4. **Gates.** Run one gates call. It writes `gates.json`, `review_plan.json`,
   `review_packet.md`, and `roi.txt`. Fix all errors in one rewrite, then run one gates call again.
   Do not run a separate validator after every edit.
5. **Review.** Start the web review. Wait. Run one adversarial subagent pass by default when a
   read-only subagent is available; skip only if unavailable or the caller declines. If no human
   reviewer is available, skip the page, say "not manually reviewed; static checks only," and still
   run the adversarial pass after the gates call if a subagent is available. Read only low scores and comments. Apply all
   feedback in one rewrite. If feedback exists, run one gates call to create
   `review_actions.json`; fill every score-1 action/target, set `"status": "resolved"`, then build.
6. **Build.** Run one build call. It validates the real import.
7. **Cleanup.** Stop the review server, delete `$WORK` in full, leave only the `.apkg`.

### Commands

```bash
SKILL="<the directory containing this SKILL.md>"

# Step 2 — extract all chosen sources (foreground; one call)
python3 "$SKILL/scripts/pipeline.py" --sources <dirs-or-files> --out "$WORK"

# Step 3 — author writes intake.md § Scope, kcs.md, cards.jsonl first (no command).
# Step 3b — if images are on, index candidates once (cards.jsonl must exist).
python3 "$SKILL/scripts/media_index.py" "$WORK" --cards "$WORK/cards.jsonl" --per-card 2
# --per-card 2 is candidates, not attachments; attach one image per card.

# Step 4 — gates (exact errors, review plan, ROI)
python3 "$SKILL/scripts/pipeline.py" --cards "$WORK/cards.jsonl" --gates-only --out "$WORK"

# Step 5 — review (one server, background; then wait)
python3 "$SKILL/scripts/review_server.py" --cards "$WORK/cards.jsonl" \
  --plan "$WORK/review_plan.json" --media-root "$WORK" \
  --out "$WORK/review_feedback.jsonl" --done-file "$WORK/review_done"

# Step 6 — build + real import validation (after review actions are resolved)
python3 "$SKILL/scripts/pipeline.py" --cards "$WORK/cards.jsonl" --gates-only --build \
  --out "$WORK" --deck-name "Deck Name" --out-apkg ./Deck.apkg
# If images are on (default for slides/video/figure-bearing PDFs), append: --media --media-root "$WORK"
# If the caller wants revision context, append: --context
```

`pipeline.py --sources` accepts directories; it excludes `$WORK` automatically. One
extraction call covers documents and media. If an extraction is interrupted, re-run the same
command with `--resume`; do not start a second concurrent extractor. If a source genuinely
cannot be extracted, report it; do not switch extractors or probe for
LibreOffice/Office/desktop converters.

## KCs

A knowledge component is the thing being learned; a card is one retrieval rep. KCs are the
value and coverage model, not a per-card ledger and not a card-count quota.

Write `$WORK/kcs.md` before the cards:

```markdown
# KCs — Deck Name

| kc | type | claim | why | requires | evidence_quote | source |
|---|---|---|---|---|---|---|
| charge.current | concept | Current is charge flow; 1 A = 1 C/s | Reused by every current and power card | — | "1 ampere = 1 coulomb/second" | Slides 1 p.2 |
| nodal.supernode | boundary | A voltage source between non-reference nodes needs a supernode | One-card exception; one card is the complete decision | nodal.steps | "supernode" | Slides 4a p.24 |
```

Rules, all scale-free:

- Every card names a `kc` that exists in `kcs.md`.
- **Single-card KCs are allowed.** `why` must make the value case: reused, exam-weighted,
  error-prone, a prerequisite, or a high-value exception.
- A single-card `concept` or `mechanism` warns: justify it, or add a second retrieval angle
  only if it adds value. All other types (`condition`, `procedure`, `representation`, `schema`,
  `boundary`, `error`, `metacognition`, `integration`, `anchor`) are allowed as singles.
- A map where every KC has exactly one card warns: inspect for card labels. No hard rejection.
- Do not add a card or change a type just to clear a warning. The review judges value.
- Two KCs with the exact same `claim` are an error: they are one KC.
- No filler cards to satisfy a KC count. Park the weaker candidate in `intake.md` § Scope.
- Every `requires` resolves.
- A source-dependent KC carries an `evidence_quote` found in the extracted corpus; `derived`
  is exempt.
- `type` and `stratum` are optional. When `type` is omitted, no type-based single-card warning
  fires; the review still judges the KC. The card’s `topic` is its scope link.

A KC with no cards is a warning: remove it from the map or park it in `intake.md` § Scope with a
reason. `intake.md` § Scope carries `Ceiling: N`, a soft cap on total cards. Set it **before** writing
cards, from the caller's target/scope; do not set it to the number you just wrote. The gate warns
when the deck exceeds it but never auto-cuts. The human decides.

## Media

Images default **on** for slides, video, and any source with usable figures, including
figure-bearing PDFs and scanned/handwritten work. They are off only for a confirmed
text-only source or when the caller explicitly says no. A request that does not mention
images is **not** an opt-out. After extraction, if figures exist, keep images on unless the
caller opted out; default-on still means attach only figures that show what the front asks.

- Write the cards first without media, or plan the media from the topic list. Run
  `python3 "$SKILL/scripts/media_index.py" "$WORK" --cards "$WORK/cards.jsonl" --per-card 2`
  **once**; it prints a compact ranked candidate list.
- Attach only a candidate that shows the thing the front asks about. Prefer the full slide or
  frame; a crop needs confirmation. One image per card.
- `media_index.py` is a text shortlist, not a visual check. Use
  `python3 "$SKILL/../image-vision/scripts/vision_check.py"` first for every candidate
  figure you need to identify or verify, including `direct` candidates. `direct` means
  extraction quality, not semantic correctness.
- Batch candidates into one `image-vision` call by default (or one call per source if the
  batch is genuinely large); no per-image calls, no corpus pre-confirmation, no galleries.
- If no good image exists, leave the card without one and say so. Never lower the bar to hit an
  image count.
- If image-vision is unconfigured, has no usable model, or stops on a rate limit, a bounded
  main-model fallback is allowed for necessary images: keep it small, never use it for bulk
  selection, and label the result **unverified** in the report.

Media entries live in `cards.jsonl` as `{file, side, caption, source}`. Rewrite the file once
to add them; do not patch cards one at a time. Bundle with `--media --media-root`; the image
choice follows the source default.
For a scanned or handwritten source, use the separate `image-vision` skill first; it is the
only bulk-pixel path, and the normal media rule still forbids main-model bulk vision.

## Review

On the first generation, run the web review by default. On later changes, ask whether to
reopen it; if declined, say “not manually reviewed; static checks only.”

Run the server in the background, hand over one sentence and the URL alone on its own line,
then wait. Do not print card text into chat. On “done”, run one gates call; it reduces the
feedback log and writes `review_actions.json` when feedback exists. Read only low scores and
comments. Apply all feedback in one rewrite, then one gates call. Fill `review_actions.json`
and set `"status": "resolved"` before the build. If there is no feedback, no action file is required
and the build proceeds.

Stop a stuck server with `curl -X POST <url>/finish`, never `pkill -f`. Score 1 is calibration
(“known / too easy”), not automatic rejection; score 5 is the only removal verdict.

The adversarial reviewer is the default when a read-only subagent/task tool is available. Give it
`$WORK/review_packet.md` only (the gates call writes it), after the web review is open or after the
gates call when the page is skipped, and ask for findings by card number. It never rewrites or certifies. Skip only when no subagent exists
or the caller declines. Do not rerun it after a formatting-only change; render one card instead.

## Build, cleanup, report

The build command above runs gates and import validation in one call. The build refuses
missing `intake.md` § Scope and `kcs.md` unless `--allow-missing-artifacts` is for a
draft. It also refuses unresolved `review_actions.json` when feedback exists, media risks, or
validation errors. A dossier is not written unless `--context` is passed; the `.apkg` is the default
output. Name the file from the deck name with `::` replaced by `-` (e.g., `COLD-TEST.apkg`).

After a successful build, delete `$WORK` in full. Do not create a source folder or keep the
deck script. Never delete a pre-existing file. Remove `scripts/__pycache__` if present.

Report:

```text
<path/to/deck.apkg>   ·   N cards
Study first: <2–3 highest-weight topics, and why>
Assumed: <the one or two assumptions you made>
Quality: DONE / DONE WITH WARNINGS / NOT REVIEWED / BLOCKED — one line
<optional: a one-line cut list>
```

Never narrate stages, validator counts, or work-file names. Never quote card text; that is
what the review page is for. For an expert caller, add validator warnings, ROI reading, and
what the review found. The `Assumed:` line is mandatory whenever you skipped a question.

## Stop rules

- One extraction. One cards write per topic batch, plus the one media rewrite and one
  post-feedback rewrite. One gates call per batch, one repeat after a fix, and one after review
  when feedback exists; the build has its own internal gate. One build.
- No background extraction, no `nohup`, no second extractor.
- Never spawn a child `opencode` process (including `opencode run` or `debug`) or recursively
  invoke this skill.
- No deck scripts and no ad hoc Python to patch cards. Rewrite the file.
- A global symbol or formatting change is one rewrite of `cards.jsonl`, not one edit per
  card or per symbol. Apply all review feedback in one rewrite.
- A blank line is a paragraph; two trailing spaces are a deliberate hard break. A literal
  `<br>` in `cards.jsonl` is a warning, not the default paragraph separator.
- After a render or formatting change, reopen the review or render one card. Source
  inspection is not a visual check.
- No reading `scripts/` unless a gate error names a confirmed script bug. Read the error’s
  `fix:` hint first; if still blocked, report.
- No validator, extractor, media-index, or builder script as a parallel path. Use
  `pipeline.py`; if a gate error is unclear, read its `fix:` hint.
- Do not probe for LibreOffice, Office, desktop converters, or random system tools. Use the
  declared extractors. After two failed probes, stop and report the limitation.
- No filler cards to satisfy a KC count; park the weaker candidate.
- No command that only confirms a file you wrote. No re-reading an artifact.
- If a command fails twice for the same reason, stop and report the blocker.
- If you exceed your own budget by 50%, stop and report. Do not spend more to avoid reporting.

## How much to ask

Everything technical here is for you. The caller experiences two things: how many questions
they get and how much jargon they hear.

- **Short or casual request:** ask at most one question (the deck name if missing); infer the
  rest; state assumptions; run the gates silently.
- **Iterating or weighing a tradeoff:** be verbose, show the judgement calls, report the
  validator and review detail.
- **No request text but material present:** do not start a full-folder build. Ask one short
  question — chapter, topic, exam, or whole folder — and wait.
- **No sources found:** read `references/getting-started.md`, print it, stop.

A detailed first request is not a reason to block. Interaction level controls questions;
learner calibration controls the backs.

## References

Read each file once, at the step named. The rules above are the contract; references explain.

| File | Read | Carries |
|---|---|---|
| `references/card-writing.md` | before authoring | calibration, symbols, tier-zero, anchors, cloze, recallability, provenance, topic/objects, Procedure |
| `references/authoring.md` | before authoring | fields/shapes, `cards.jsonl`, KC map, media policy, JSON escaping, batching |
| `references/prompts.md` | authoring | classifier and debloater only |
| `references/review.md` | review and follow-up | triage, score meanings, review actions, rescope |
| `references/survey.md` | intake and extraction | source survey, learner context, deck name |
| `references/video.md` | video sources | transcripts, playlists, frames |
| `references/slides.md` | PowerPoint sources | PPTX text, notes, embedded images |
| `references/rendering.md` | render/hard-break changes | MathJax, JSON escaping, night mode |
| `references/optional.md` | when relevant | programming decks, known gaps, deck audit |
| `references/revision.md` | imported decks only | AnkiConnect, snapshots, revert |
| `references/getting-started.md` | no sources found | beginner intro |
| `README.md` | setup | dependencies, MathJax |
