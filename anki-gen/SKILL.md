---
name: anki-gen
description: Generate evidence-based Anki flashcards from lecture notes, PDFs, PowerPoint, homework, textbooks, YouTube videos, and local recordings, and review them in a built-in local web page. Use when the user asks to make flashcards or an Anki deck, turn course material into cards, merge a deck, or study with spaced repetition. Outputs .apkg for direct import.
---

# Anki STEM Flashcard Generator

Generate atomic, evidence-based Anki cards from STEM material, review them in a local page,
and build an `.apkg`.

Harness-agnostic: `SKILL` is the directory containing this file. Install paths
(`~/.claude/skills/...`, `.opencode/skills/...`, `.agents/skills/...`) differ only by entry point.

`$WORK` is `.anki-gen-temp/<slug>` (deck name lowercased, `::`/spaces → `-`), e.g.
`circuits-midterm2`. Every artifact lives there; the `.apkg` is the only new file in the caller's directory.

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
10. **Media bar.** Full slide/frame by default; crops need confirmation; one image per card by
    default, up to two when both are needed; no title, outline, agenda, incomplete crop, or whitespace-heavy image.

A gate passing is not a quality certificate. The review is.

## The runbook

Seven steps; no parallel path. Read only the current step's reference; more context is not better.

1. **Intake.** Read the request and the chosen sources. Open only `survey.md` and the source
   table of contents for now; do not open `card-writing.md`, `review.md`, or `prompts.md`
   until their step. Read the learner-calibration fields in `survey.md`; if no learner context
   exists, assume beginner/cold and state it. Do not read the whole study log.
   Write `$WORK/intake.md`: deck name, learner context, sources, image yes/no, assumptions, and
   **your own budget** for this run (estimated extraction, authoring, review, and build calls
   based on scope). No fixed numbers.
2. **Extract.** Run one foreground extraction with all chosen documents and media. Wait for it
   to return. Do not background a second extractor; do not read `sources.md` until it exists.
3. **Author.** Read the combined source (`sources.md` for documents, `transcripts.md` for video)
   once in full; use per-source files only for a narrow check. Add a `## Scope` section to
   `$WORK/intake.md` with a `Ceiling: N` line, and write `$WORK/kcs.md`. Then write
   `$WORK/cards.jsonl` in one pass per topic during initial authoring. One authoring format; no deck script.
4. **Gates.** Run one gates call. It writes `gates.json`, `review_plan.json`,
   `review_packet.md`, and `roi.txt`. Fix all errors in one whole-file rewrite, then run one gates
   call again. Do not run a separate validator after every edit.
5. **Review.** Start the web review. Wait. Run one adversarial subagent pass whenever a
   read-only subagent is available; skip only if none exists. If no human
   reviewer is available, skip the page, say "not manually reviewed; static checks only," and still
   run the adversarial pass after the gates call if a subagent is available. Read only low scores and
   comments. If feedback exists, run one gates call to create `review_actions.json`; apply all
   feedback in one complete write of `cards.jsonl`; fill every score-1 action/target, set
   `"status": "resolved"`, then build.
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
# --per-card 2 is candidates, not attachments; attach one image per card by default, up to two.

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

`pipeline.py --sources` accepts directories and excludes `$WORK`. One call covers documents and
media; `--resume` continues an interrupted extractor. Report an unextractable source; do not switch
extractors or probe for Office/LibreOffice.

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

- Every card names an existing `kc`.
- **Single-card KCs are allowed.** `why` must make the value case: reused, exam-weighted,
  error-prone, prerequisite, or high-value exception. A single-card `concept`/`mechanism` warns;
  other types (`condition`, `procedure`, `representation`, `schema`, `boundary`, `error`,
  `metacognition`, `integration`, `anchor`) may be singles.
- A 1:1 map warns; duplicate `claim`s are errors. Do not add cards/types to clear a warning.
- No filler cards for a KC count; park the weaker candidate in `intake.md` § Scope.
- Every `requires` resolves. Source-dependent KCs need an `evidence_quote` from the corpus;
  `derived` is exempt.
- `type`/`stratum` are optional; `topic` is the scope link.

A KC with no cards warns: remove it or park it with a reason. `Ceiling: N` is a soft cap set
**before** writing, from scope; the gate warns, never cuts. The human decides.

## Media

Images default **on** for slides, video, and figure-bearing PDFs/scans. Off only for a confirmed
text-only source or an explicit no; silence is not an opt-out. Keep images on after extraction unless
the caller opted out; attach only figures that show what the front asks.

- Write the cards first without media, or plan the media from the topic list. Run
  `python3 "$SKILL/scripts/media_index.py" "$WORK" --cards "$WORK/cards.jsonl" --per-card 2`
  **once**; it prints a compact ranked candidate list.
- Attach only a candidate that shows the thing the front asks about. Prefer the full slide or
  frame; a crop needs confirmation. One image per card by default, up to two when both are needed.
- `media_index.py` is a text shortlist, not a visual check. `direct` candidates may attach on
  high-confidence deterministic evidence: the caption, nearby source text, figure geometry, the
  media-index rank, or a previously verified figure. Use image-vision for `confirm` candidates
  and whenever you need to read labels, values, connectivity, or an ambiguous figure. `direct`
  means extraction quality, not semantic correctness.
- When you do use image-vision, batch the candidates into one call (or one call per source if
  the batch is genuinely large); no per-image calls, no corpus pre-confirmation, no galleries.
- No good image: leave it off; never lower the bar. If image-vision is unavailable, a small
  bounded main-model fallback is allowed for necessary images; label it **unverified**.

Media entries live in `cards.jsonl` as `{file, side, caption, source}`. Rewrite the file once
to add them; do not patch cards one at a time. Bundle with `--media --media-root`; the image
choice follows the source default.
For a scanned or handwritten source, use the separate `image-vision` skill first; it is the
only bulk-pixel path, and the normal media rule still forbids main-model bulk vision.

## Review

On the first generation, run the web review by default. On later changes, ask whether to
reopen it; if declined, say “not manually reviewed; static checks only.”

Run the server in the background; hand over one sentence and the URL alone; wait. Do not print card
text. On “done”, one gates call → apply all feedback in one complete `cards.jsonl` write → fill
`review_actions.json` and set `"status": "resolved"` → build (which runs the gates once more).
No feedback: no action file; build.

Stop a stuck server with `curl -X POST <url>/finish`, never `pkill -f`. Score 1 is calibration
(“known / too easy”), not automatic rejection; score 5 is the only removal verdict.

The adversarial reviewer is mandatory when a read-only subagent/task tool is available. Give it
`$WORK/review_packet.md` only (the gates call writes it), after the web review is open or after the
gates call when the page is skipped, and ask for findings by card number. It never rewrites or
certifies. Skip only when no subagent exists. Do not rerun it after a formatting-only change;
render one card instead.

## Build, cleanup, report

The build runs gates and import validation in one call. It refuses missing `intake.md` § Scope or
`kcs.md` (unless `--allow-missing-artifacts` for a draft), unresolved `review_actions.json`, media
risks, or validation errors. `--context` writes a dossier; otherwise the `.apkg` is the only output.
Name it from the deck name with `::` → `-` (`COLD-TEST.apkg`).

After a successful build, delete `$WORK` in full. Do not create a source folder or keep the deck
script. Never delete a pre-existing file. Remove `scripts/__pycache__` if present.

Report:

```text
<path/to/deck.apkg>   ·   N cards
Study first: <2–3 highest-weight topics, and why>
Assumed: <the one or two assumptions you made>
Quality: DONE / DONE WITH WARNINGS / NOT REVIEWED / BLOCKED — one line
<optional: a one-line cut list>
```

Do not narrate jargon — stage numbers, validator counts, or work-file names; short plain-language
status while it runs is fine. Never quote card text; that is
what the review page is for. For an expert caller, add validator warnings, ROI reading, and
what the review found. The `Assumed:` line is mandatory whenever you skipped a question.

## Stop rules

- One foreground extraction; no `nohup` or second extractor. One write per topic batch, one media
  write, one post-feedback whole-file write. One gates call per batch, one repeat after a fix, one
  after review; build has its own gate. One build.
- Never spawn a child `opencode` process or recursively invoke this skill.
- No deck scripts or ad-hoc Python to patch cards. Rewrite the file.
- One whole-file write for a global symbol/formatting or review change, never per card.
- A blank line is a paragraph; two trailing spaces are a hard break. Literal `<br>` warns.
- After a render/formatting change, reopen review or render one card.
- No reading `scripts/` unless a gate error names a confirmed script bug; use its `fix:` hint.
- No extractor/validator/media-index/builder script as a parallel path; use `pipeline.py`.
- Do not probe for LibreOffice/Office/desktop converters; report an unextractable source.
- No filler cards for a KC count; park the weaker candidate.
- Read `cards.jsonl` once before the post-feedback write; no other re-reads. Use `sources.md`
  headings plus `grep`/line ranges instead of every per-source file.
- If a command fails twice for the same reason, stop and report.
- If you exceed your own budget by 50%, stop and report.

## How much to ask

Everything technical is for you. The caller sees questions and jargon.

- **Short/casual:** at most one question (deck name); infer, state assumptions, run gates silently.
- **Iterating/tradeoff:** be verbose; show judgement, validator, and review detail.
- **No request, material present:** ask chapter/topic/exam/whole folder; wait.
- **No sources:** print `references/getting-started.md`; stop.

Interaction controls questions; calibration controls backs.

## References

Read each file once, at the step named. The rules above are the contract; references explain.

| File | Read | Carries |
|---|---|---|
| `references/card-writing.md` | before authoring | calibration, symbols, tier-zero, anchors, cloze, recallability, provenance, topic/objects, Procedure |
| `references/authoring.md` | before authoring | fields/shapes, `cards.jsonl`, KC map, media policy, JSON escaping, batching |
| `references/prompts.md` | authoring and review follow-up | classifier and debloater only |
| `references/review.md` | review and follow-up | triage, score meanings, review actions, rescope |
| `references/survey.md` | intake and extraction | source survey, learner context, deck name |
| `references/video.md` | video sources | transcripts, playlists, frames |
| `references/slides.md` | PowerPoint sources | PPTX text, notes, embedded images |
| `references/rendering.md` | render/hard-break changes | MathJax, JSON escaping, night mode |
| `references/optional.md` | when relevant | programming decks, known gaps, deck audit |
| `references/revision.md` | imported decks only | AnkiConnect, snapshots, revert |
| `references/getting-started.md` | no sources found | beginner intro |
