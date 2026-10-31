# Runbook prompts

CLASSIFIER at authoring; DEBLOATER at review follow-up. Card-writing rules and gates are the
writer/verifier contract; no second writer prompt.

## CLASSIFIER

Segment source material into atomic concepts and classify each.

**Input:** read `sources.md`/`transcripts.md` once in full (single-source `.md` for diagnosis;
per-source only for a later narrow check), course context, and `media/` if on. Classify broadly;
the scope gate filters. Read `intake.md` § Scope first.

**Task:** (1) identify the course domain; (2) segment into atomic concepts explicitly present in
the source; (3) classify each with `layer` (L1/L2/L3/Procedure), `topic`, `objects`, `type`
(fact/formula/definition/concept/derivation/boundary/procedure), `kc_id` (stable, opaque, e.g.
`thermo.steady_flow`), `kc_type`, optional `stratum`, `requires` (KC IDs), and `source` (file +
page/slide/line). Use `source`, not `source_ref`.

`topic` is the chapter/lecture heading, never a layer code, lecture number, fact, or subtopic; same
lecture shares the topic. `objects` is 0–2 cross-topic buckets; prefer `[]`. Tags are front-visible:
never put the answer/method/theorem/technique in either. `kc_id` is for the KC map, not a tag.

**Do not produce concepts for:** anything not explicitly in the source; computed final-value fronts;
proofs/worked examples (unless a Procedure decision); relations the material does not discuss.
Method/next-step problem fronts are Procedure cards, not exclusions. Scope is the brake on volume.

**Every concept has:** `source`, `layer`, `topic`, `type`, `objects` (0–2, may be `[]`).

**Output only a JSON array:**

```json
[
  {"id":"concept_001","topic":"Fourier Transform","objects":["signals"],"layer":"L2","type":"derivation","kc_id":"fourier.transform","kc_type":"concept","requires":[],"source":"Lec 05 p.12","content":"Fourier Transform converts time-domain signal to frequency domain..."},
  {"id":"concept_002","topic":"Fourier Transform","objects":[],"layer":"L3","type":"boundary","kc_id":"fourier.transient_boundary","kc_type":"boundary","requires":["fourier.transform"],"source":"Lec 05 p.18","content":"FT assumes the signal is periodic/infinite; it fails for transient signals without windowing..."}
]
```

## DEBLOATER PROMPT

A short judgement pass after review, not a subagent. `roi_report.py` is a signal; measured review
feedback outranks it. Never auto-cut.

- **Audience sets aggressiveness:** cramming keeps anchors; a strong learner can lose them.
- **Redundancy** → drop/merge. **Bad bundling** (independent facts share a schedule) → split.
  **Good chunk** (items always transfer together) → keep.
- **Protect** anchors, reciprocal procedures, one procedure walkthrough per procedure. Compress long
  backs before deleting; keep the why.
- **Report protections as well as cuts.** Name the card by topic and number; do not quote card
  text.
- **Apply to `cards.jsonl` in one complete whole-file write**, then run one gates call. Never edit
  the `.apkg`.
