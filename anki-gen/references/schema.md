# Card schema and shapes

## Card Schema (Output)

This is the card schema written down. `validate_cards.py` enforces the required fields and the
layer enum directly and is the authority when they disagree.

**Required on every new-run card: `front`, `back`, `layer`, `topic`, `deck`, `source`,
`kc`.** An empty or missing one is an **error**, including `deck`; self-contained
math/definitions use `source: "derived"`. Legacy decks without a KC map may omit `kc`.
**`cloze: true`** is required on any card with `{{cN::}}`; **`tier_zero: true`** marks the
topic's concept card before its formula cards.

- **`source` is the field.** `source_ref` is a deprecated alias `build_native.py` still falls back
  to; nothing new should write it. Both are searched and rendered, so a card with only `source_ref`
  still builds — it is just invisible to every grep for `source`. Use `source: "derived"` for
  self-contained math/definitions; that marker omits the footer and needs no locator.
- **`source_url`** is optional plain text, never a hyperlink; omit it for local recordings.
  It is the copyable URL (`https://...&t=SECONDS`), while `source` carries the human
  label (`DigiKey · RTOS 04 · Memory Management @ 01:32`; full title stays in the
  URL/video metadata). A series URL also carries `&list=PLAYLIST_ID`.
- **`topic`** — the chapter/lecture heading, not a layer code or subtopic. **`objects`** — 0–2
  lowercase **cross-topic buckets** (`concurrency`, `memory`, `rtos`), not subtopics; **`[]` is
  normal**. Both are front-visible (the topic is printed; tags are metadata), so never encode
  the answer: a Bernoulli-substitution card is `topic: "First-Order ODEs"`, not
  `objects: ["bernoulli"]`. Do not tag the topic or a term already explicit in the card; see
  `references/card-writing.md`. Generated tags are lowercase; the Topic field keeps its display
  capitalization.
- **Procedure filter:** `objects: ["procedural"]` is the reserved tag for Procedure cards. It is
  not a content bucket, and an L2 procedure walkthrough does not get it.
- **`kc`** — the knowledge-component ID from `$WORK/kcs.md`. Required for new runs; legacy
  decks without a KC map keep working. A card may also carry `stratum` (`concept`,
  `mechanism`, `condition`, `procedure`, `representation`, `error`, `schema`, `integration`,
  `boundary`, `metacognition`), but it is optional: the KC `type` is the preferred retrieval
  family. `kc` and `stratum` are stored in the card/dossier, never printed on the front or put
  in Anki tags.
- **KC evidence** — `evidence_quote` is a column in `kcs.md` for the KC’s source claim. A
  source-dependent KC needs one short quote; `derived` is the exemption. The gate verifies it
  against the extracted corpus. A card whose claim is narrower than its KC may carry its own
  `evidence_quote`; the card still carries the `source` locator.
- **Single-card KCs** — allowed when the card is a complete, high-value decision; the KC’s
  `why` is the value case. A single-card `concept`/`mechanism` warns; all other types are
  allowed as singles. A 1:1 map warns; exact duplicate claims are errors. Do not add a card or
  change a type just to clear a warning.
- **`hash` is a card's identity**, not a checksum you invent: leave it empty and it is
  `md5(front|back)` — the note GUID and review-log key, one definition in `scripts/cardid.py`.
- **`media`** is opt-in. Each entry is an object `{"file": "<tag>/media/<file>", "side":
  "front"|"back", "caption": "...", "source": "...", "source_url": "..."}`; a bare string means
  `{file, back}`. When media is present, `source`/`source_url` become the card footer so the
  transcript and image provenance are not printed twice.
  Paths are relative to the media root (default: the directory holding cards.json), and the
  files are bundled only with `build_apkg.py --media --media-root <root>`.

**Study order** is softly scattered for larger decks: each topic's `tier_zero` card comes
first, then topics interleave with a source-order bias. Small decks stay grouped. The order is
deterministic for a given deck. Anki's New Card Sort Order can override it.

---

## Card shapes (the templates)

The build emits **two** notetypes — Basic and Cloze. Procedure A/B shapes are in
`references/card-writing.md`, "The Procedure layer."

**L1 Basic** — recall: `Front: {{concept}} — {{question}}` / `Back: {{answer}}`.
**L1 Reversible** — the reciprocal pair, both directions as one card each: `Front: {{concept}} ↔
{{term}}` / `Back: {{definition}}`.
**L2 Basic** — concept, why/how, formula or derivation: `Front: {{question}}` / `Back:
{{explanation}}`.
**L2 Cloze** — only a rule-15 enumeration, one separately examinable item per deletion. Never a
whole formula.
**L3 Basic (boundary):** `Front: When does {{concept}} fail?` / `Back: {{limitation}} — {{consequence}}`.

No Image Occlusion template (no such notetype) and no Type-in. A "Procedure Cloze" used as a
decision card (`Step {{c1::1}}: ...`) tests sequence recognition, not a decision — use A or B (rule
19). An **L2 procedure walkthrough** is different: one card per procedure, first and last steps
visible, 1–3 labeled middle blanks.
