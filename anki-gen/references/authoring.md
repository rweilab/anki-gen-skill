# Authoring cards: mechanics

One authoring format: `$WORK/cards.jsonl`. One line per card. No deck script, no
`make_cards.py`, no ad hoc Python patches. `cards.json` is still read for old work dirs;
new runs write `cards.jsonl`.

Write the whole file in one pass per topic. To change a card, rewrite the file (or the
affected topic batch) in one write. Never shuttle the source through a shell
`read → replace → write` loop: it is a near-miss matcher, it silently corrupts cards, and
it re-sends the whole file at every step.

## Order

1. Add a `## Scope` section to `$WORK/intake.md`: what to card, what not to card, a
   `Ceiling: N` line, and the parked list with reasons.
2. Write `$WORK/kcs.md`: the compact KC table. A KC is a concept, not a card. Single-card KCs
   are allowed when the card is a complete high-value decision and `why` makes the value case.
   A 1:1 map warns; exact duplicate claims are errors. Do not write filler cards.
3. Write `$WORK/cards.jsonl` topic by topic in source order. Each card carries `kc`; `stratum`
   is optional. A normal topic is a small batch, not a quota.

Read `references/card-writing.md` before the first card; read only the sections the card
needs. The ten rules in `SKILL.md` are the hard floor.

## Card JSON

Required fields: `front`, `back`, `layer`, `topic`, `source`, `kc`. `deck` is legacy and optional; the build uses `--deck-name`. Minimum:

```json
{"front":"What does a 9 V battery rating measure?","back":"**Energy per unit charge.** **Why:** ...","layer":"L1","topic":"Voltage and Power","source":"Slides 2 p.2","kc":"power.voltage_meaning","tier_zero":true}
```

Optional fields: `objects`, `cloze`, `tier_zero`, `media`, `source_url`, `evidence_quote`
(for a card claim narrower than its KC), `stratum`.

**Fields.**
- `source` is the locator (`Slides 2 p.2`, `Lec 04 Q7`, or `derived` for self-contained math).
  `source_ref` is a deprecated alias; do not write it. `source_url` is optional plain text.
- `topic` is the chapter/lecture heading. `objects` is 0–2 lowercase cross-topic buckets; `[]`
  is normal. Tags are front-visible: never put the answer, method, or theorem in either.
- `kc` must exist in `kcs.md`. `stratum` is optional; the KC `type` is the preferred family.
- `hash` is identity: leave it empty; it is `md5(front|back)`. Do not invent one.
- `media` entries are `{file, side, caption, source}`; paths are relative to the media root.
  One image per card is the default.

## Schema policy

- Write `cards.jsonl`. `cards.json` is read-only for old work dirs.
- Required fields are frozen. New fields must be optional.
- Do not repurpose a field. Unknown fields are ignored by the gate and preserved by the dossier.
- `deck` is legacy; `--deck-name` is the single deck-name source.
- There is deliberately no per-card schema version. Additive changes only; a new required field
  waits for a major version.

**Shapes.** The build emits Basic and Cloze only.
- L1 Basic: recall of a fact, definition, formula, or constant.
- L1 reversible: a reciprocal pair, one card each direction.
- L2 Basic: concept, why/how, derivation, or analogy.
- L2 Cloze: only a rule-15 enumeration, one separately examinable item per deletion; never a
  whole formula.
- L3 Basic: boundary, failure mode, or edge case.
- Procedure A/B: one decision per card; shapes live in `card-writing.md` under Procedure.
No Type-in and no Image Occlusion notetype.

`cards.jsonl` is JSON, not Python. Double every LaTeX backslash (`\\frac`, `\\text`). A
single `\frac` can become a formfeed and corrupt the card. The validator catches control
characters; fix them, do not disable the check.

Use the course's vocabulary. Define every symbol with units. Put the answer in the first
back sentence, then the why. Do not put a computed final value on a front, a cross-card pointer in
a back, or an answer-leaking term in `topic`/`objects`.

## Batching

- Write one topic batch in one `write` call. Do not append card-by-card.
- Run one gates call after the batch. Fix all errors in one rewrite.
- After review, apply all feedback in one rewrite; then one gates call.
- A global symbol or formatting change is one rewrite of `cards.jsonl`, not one edit per card
  or per symbol.
- A deck of any size is a sequence of topic batches. The batch is the unit, not the deck.

## Reading discipline

- Read `sources.md` once if it fits, or read its table of contents and the per-source files
  you need. Do not reload the whole corpus to confirm a card.
- Do not read `scripts/`, the validator source, or a file you just wrote. Use the gate’s
  `fix:` hint; if it is unclear, report the error.
- Do not read other work’s handoff docs. Read the chosen sources, learner context, and the
  stage reference.
- Put conclusions on disk in `intake.md` § Scope or `kcs.md`; do not re-derive them at every step.

## KCs

`kcs.md`:

```markdown
# KCs — Deck Name

| kc | type | claim | why | requires | evidence_quote | source |
|---|---|---|---|---|---|---|
| thermo.control_volume | concept | A control volume is a fixed region. | Reused by mass, energy, and momentum balances | — | "A control volume is a fixed region" | Lec 04 p.3 |
| thermo.steady_flow | procedure | Apply the steady-flow energy equation. | One-card method decision | thermo.control_volume | "Apply the steady-flow energy equation" | Lec 04 p.12 |
```

- A KC is a concept, not a card. Single-card KCs are allowed when the card is a complete,
  high-value decision.
- `why` is the value case: reused, exam-weighted, error-prone, a prerequisite, or a high-value
  exception. Do not write filler cards to satisfy a count.
- A single-card `concept`/`mechanism` warns; all other types are allowed as singles.
- A 1:1 map warns; exact duplicate claims are errors. Do not add a card or change a type just
  to clear a warning.
- `type` is optional; if omitted, the review still judges the KC. Every `requires` resolves. A
  source-dependent KC needs a short quote that appears in the extracted corpus; `derived` is
  the exemption.
- `intake.md` § Scope carries `Ceiling: N`, a soft cap on total cards. The gate warns when the deck
  exceeds it; it never auto-cuts. Park the weaker candidate instead.

## Media (default by source)

Images default on for slide and video sources, off for text-only sources. When images are on:

1. Run `media_index.py "$WORK" --cards "$WORK/cards.jsonl" --per-card 2` once. It prints a
   compact ranked list.
2. Pick only candidates that show the thing the front asks about. Prefer a full slide/frame;
   a crop needs confirmation.
3. Batch every `confirm` image into one `image-vision` call (or one call per source if the
   batch is truly large). No per-image calls, no corpus pre-confirmation, no galleries.
4. Add `media` entries to `cards.jsonl` and rewrite the file once. One image per card.
5. Build with `--media --media-root "$WORK"`.

Media entry: `{"file":"<tag>/media/<file>","side":"front|back","caption":"...","source":"..."}`.
Paths are relative to the media root.

Never attach a title/outline/agenda slide, an incomplete crop, a whitespace-heavy frame, or a
duplicate. If no good image exists, leave the card without one. “More images” does not lower
the bar. If image-vision is unavailable, leave `confirm` images unattached and report it; do
not bulk-read pixels with the main model.

Shared diagrams may appear on several related cards; the builder bundles the file once.
Wrong images go in the review comment box, not into a new patch loop.

## Imported decks

Do not hand-edit an imported deck or open its live collection. Read
`references/revision.md` and use the supported AnkiConnect path.
