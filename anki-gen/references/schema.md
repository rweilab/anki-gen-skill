# Card schema and shapes

## Card Schema (Output)

This is the card schema written down. `validate_cards.py` enforces the required fields and the
layer enum directly and is the authority when they disagree.

**Required on every card: `front`, `back`, `layer`, `topic`, `deck`, `source`.** An empty or
missing one is an **error**, including `deck`. **`cloze: true`** is required on any card with
`{{cN::}}`; **`tier_zero: true`** marks the topic's concept card before its formula cards.

- **`source` is the field.** `source_ref` is a deprecated alias `build_native.py` still falls back
  to; nothing new should write it. Both are searched and rendered, so a card with only `source_ref`
  still builds — it is just invisible to every grep for `source`.
- **`source_url`** is optional and plain text (never a hyperlink). Video cards use it for the
  copyable timestamp URL: `<channel> - <video title> @ mm:ss` for a single video, or
  `<channel> - <playlist> NN - <video title> @ mm:ss` for a series. The URL includes `&t=SECONDS`
  and, for a series, `&list=PLAYLIST_ID`.
- **`topic`** — the chapter/lecture heading, not a layer code or subtopic. **`objects`** — 0–2
  lowercase tags for named things that recur; **`[]` is normal**. Do not tag subtopics such as
  `radians`/`sine`/`tangent` in a Unit Circle deck; see `references/card-writing.md`.
- **`stratum`** is optional and deck-authored ("Shape B", "Hess's law"); `triage.py` reports
  coverage per stratum without interpreting it. The tool cannot know what a deck ought to contain —
  only its author can say what its kinds are.
- **`hash` is a card's identity**, not a checksum you invent: leave it empty and it is
  `md5(front|back)` — the note GUID and review-log key, one definition in `scripts/cardid.py`.
- **`media`** is opt-in. Each entry is an object `{"file": "<tag>/media/<file>", "side":
  "front"|"back", "caption": "...", "source": "..."}`; a bare string means `{file, back}`.
  Paths are relative to the media root (default: the directory holding cards.json), and the
  files are bundled only with `build_apkg.py --media --media-root <root>`.

**New-card order** is first-appearance topic, then `tier_zero`, then L1/L2; L3/Procedure
keep authored order. Anki's New Card Sort Order can override it.

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

No Image Occlusion template (no such notetype) and no Type-in. A "Procedure Cloze" shape (`Step
{{c1::1}}: ...`) tests sequence recognition, not a decision — use A or B (rule 19).
