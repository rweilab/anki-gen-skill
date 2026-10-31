# Authoring cards: mechanics

One authoring format: `$WORK/cards.jsonl`. One line per card. No deck script, no
`make_cards.py`, no ad hoc Python patches. `cards.json` is still read for old work dirs;
new runs write `cards.jsonl`.

Write the whole file in one pass per topic during initial authoring. After review, write the
complete file once; do not edit one card or one topic batch at a time. Never shuttle the source
through a shell `read → replace → write` loop: it is a near-miss matcher, it silently corrupts
cards, and it re-sends the whole file at every step.

## Order

1. `intake.md` § Scope: what to card/not card, `Ceiling: N`, parked list with reasons.
2. `kcs.md`: compact KC table. A KC is a concept, not a card; single-card KCs are allowed when
   `why` makes the value case. A 1:1 map warns; duplicate claims are errors; no filler.
3. `cards.jsonl` topic by topic in source order. `kc` is required; `stratum` is optional. A topic
   is a small batch, not a quota.

Read `references/card-writing.md` before the first card; read only the sections the card needs.
The ten rules in `SKILL.md` are the hard floor.

## Card JSON

Required: `front`, `back`, `layer`, `topic`, `source`, `kc`. `deck` is legacy; the build uses
`--deck-name`.

```json
{"front":"What does a 9 V battery rating measure?","back":"**Energy per unit charge.**\n\n**Why:** ...","layer":"L1","topic":"Voltage and Power","source":"Slides 2 p.2","kc":"power.voltage_meaning","tier_zero":true}
```

Optional: `objects`, `cloze`, `tier_zero`, `media`, `source_url`, `stratum`, `rev_id`.
`evidence_quote` is a KC field in `kcs.md`, not a card field.

- `source` is the locator (`Slides 2 p.2`, `Lec 04 Q7`, `derived`). `source_ref` is deprecated;
  `source_url` is optional plain text.
- Backs use a blank line before `**Why:**`/`**Glossary:**`/`**Symbols:**`; never wrap `$...$` in
  backticks.
- `topic` is the chapter heading. `objects` is 0–2 lowercase cross-topic buckets; `[]` is normal.
  Tags are front-visible: never put the answer, method, or theorem in either.
- `kc` must exist in `kcs.md`; `stratum` is optional; KC `type` is the preferred family.
- `hash` is identity (`md5(front|back)`); leave empty. `rev_id` is dossier-sync only; copy it or
  omit it.
- `media` entries are `{file, side, caption, source}` relative to the media root; one image by
  default, up to two when both are needed.

`cards.jsonl` is canonical; `cards.json` is legacy read-only. Required fields are frozen; new
fields optional; unknown fields preserved. No per-card schema version; a new required field waits
for a major version.

**Shapes** (Basic/Cloze only): L1 fact/formula/constant; L1 reversible = reciprocal pair, one card
each; L2 concept/why/derivation; L2 cloze = enumeration only, one item per deletion, never a whole
formula; L3 boundary/failure/edge case; Procedure A/B = one decision per card, shapes in
`card-writing.md`. No Type-in or Image Occlusion.

`cards.jsonl` is JSON, not Python. Double every LaTeX backslash (`\\frac`, `\\text`). A
single `\frac` can become a formfeed and corrupt the card. The validator catches control
characters; fix them, do not disable the check.

Use the course's vocabulary. Define every symbol with units. Put the answer in the first
back sentence, then the why. Do not put a computed final value on a front, a cross-card pointer in
a back, or an answer-leaking term in `topic`/`objects`.

## Batching

- Write one topic batch in one `write` call during initial authoring. Do not append card-by-card.
- Run one gates call after the batch. Fix all errors in one whole-file rewrite.
- After review, apply all feedback in one complete whole-file write; then one gates call.
- A global symbol or formatting change is one whole-file write, not one edit per card or per symbol.
- A deck of any size is a sequence of topic batches during initial authoring. A review change is
  applied to the completed file in one write, not per topic.

## Reading discipline

- Read `sources.md` once in full before authoring; if it is large, read it in order in chunks.
  Use its headings and `grep`/line ranges only for a later narrow check. Do not read every
  per-source `.md` just because it exists.
- Batch independent reads and inspections in one turn. Do not re-read a file you just wrote; the
  one exception is reading `cards.jsonl` once before the whole-file review rewrite.
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

- A KC is a concept, not a card. Single-card KCs are allowed when `why` makes the value case:
  reused, exam-weighted, error-prone, prerequisite, high-value exception.
- Single-card `concept`/`mechanism` warns; other types may be singles. A 1:1 map warns; duplicate
  claims are errors. Do not add cards/types to clear a warning; no filler.
- `type` is optional. Every `requires` resolves. Source-dependent KCs need a short quote from the
  corpus; `derived` exempts.
- `Ceiling: N` is a soft cap; the gate warns, never cuts. Park the weaker candidate.

## Media (default by source)

Images default on for slides/video/figure-bearing PDFs; off only for a confirmed text-only source
or explicit no; silence is not opt-out. When images are on:

1. Run `media_index.py "$WORK" --cards "$WORK/cards.jsonl" --per-card 2` once. It is a compact
   text shortlist, not a visual match.
2. Pick only candidates that show the thing the front asks about. Prefer a full slide/frame; a
   crop needs confirmation.
3. `direct` candidates may attach on a high-confidence caption, nearby source text, geometry,
   media-index rank, or a previously verified figure. Use `image-vision` for `confirm` candidates
   and whenever the figure needs label/value/connectivity reading or is ambiguous. Do not require
   a vision call per card; when you use it, batch candidates into one call.
4. Add `media` entries to `cards.jsonl` and rewrite the file once. One image by default; up to two
   when both are needed.
5. Build with `--media --media-root "$WORK"`.

Media entry: `{"file":"<tag>/media/<file>","side":"front|back","caption":"...","source":"..."}`.
Paths are relative to the media root.

Never attach a title/outline/agenda slide, incomplete crop, whitespace-heavy frame, or duplicate.
No good image → leave it off; “more images” never lowers the bar. If image-vision is unavailable, a
small bounded main-model fallback is allowed for necessary images; label it unverified. Do not use
`read` as the default media path.

Shared diagrams may appear on several related cards; the builder bundles the file once.
Wrong images go in the review comment box, not into a new patch loop.

## Imported decks

Do not hand-edit an imported deck or open its live collection. Read
`references/revision.md` and use the supported AnkiConnect path.
