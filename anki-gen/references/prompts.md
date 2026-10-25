# Stage prompts

Two prompts: CLASSIFIER at intake/authoring, DEBLOATER at review follow-up. The card-writing
rules and gates are the writer/verifier contract; there is no second writer prompt.

## CLASSIFIER PROMPT

You are the CLASSIFIER. Segment source material into atomic concepts and classify each.

**Input:** `$WORK/sources.md` for document batches and/or `$WORK/transcripts.md` for video (the
single-source `.md` for a diagnosis run; per-source `<tag>.md` only for a narrow check), the
course name/context, and `media/` if images are on. Classify broadly; the scope gate filters the
list before anything is written. If `scope_gate.md` exists, read it first.

**Task:** (1) identify the course domain; (2) segment into atomic concepts explicitly present in
the source; (3) classify each with `layer` (L1/L2/L3/Procedure), `topic`, `objects`, `type`
(fact/formula/definition/concept/derivation/boundary/procedure), `kc_id` (stable, opaque, e.g.
`thermo.steady_flow`), `kc_type`, optional `stratum`, `requires` (KC IDs), and `source` (file +
page/slide/line). Use `source`, not `source_ref`.

`topic` is the chapter/lecture heading a student could look up — never a layer code, lecture
number, single fact, or subtopic. Cards from the same lecture/chapter share the topic. `objects`
is 0–2 broad cross-topic buckets; prefer `[]`. Tags are front-visible: never put the answer,
method, theorem, or named technique in `topic` or `objects`. `kc_id` is for the KC map, not a tag.

**Do not produce concepts for:** anything not explicitly in the source; problem-solving or
computed fronts; proofs and worked examples (unless a Procedure decision card); relations the
material does not discuss. The scope gate is the brake on volume; coverage is not a reason for
more cards.

**Every concept has:** `source`, `layer`, `topic`, `type`, and `objects` (0–2, may be `[]`).

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

- **Audience sets aggressiveness.** A cramming learner keeps anchors; someone who owns the basics
  can lose them.
- **Redundancy** → drop or merge. **Bad bundling** (independently examinable facts share one
  schedule) → split. **Good chunk** (items always transfer together) → keep.
- **Protect** anchors, reciprocal procedures, and one procedure walkthrough per procedure.
  Compress long backs before deleting; keep the why.
- **Report protections as well as cuts.** Name the card by topic and number; do not quote card
  text.
- **Apply to `cards.jsonl`**, then rerun the gates and review. Never edit the `.apkg`.
