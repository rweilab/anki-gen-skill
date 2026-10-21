---
name: image-vision
description: Use when the user references an image or a diagram inside a PDF, worksheet, or file and wants it read into structured data — labels, values, connectivity, relationships, topology, uncertainty. Domain-agnostic (circuits, schematics, graphs, tables, lab setups, figures). Not for PDF color inversion (pdf-study) or tutoring (tutor).
---

# image-vision

Read a local image — or a diagram/figure embedded inside a PDF or worksheet —
into structured data that the caller can reason over. Pixels in, typed and
inspectable facts out. The skill reads; it does not analyze or solve — analysis
happens at the call site. It is **domain-agnostic**: the caller supplies the
domain and schema (a circuit is one example instance, never a hardcoded shape).

## Operating values (why the flow below is shaped this way)

- **Deterministic before clever.** If a check that needs no pixels exists
  (geometry, file inventory, positions, PDF stream facts), do it first. It is
  free, repeatable, and catches whole classes of vision error.
- **Correctness over call count.** A confident wrong transcription costs more
  than an extra read: it poisons every downstream step. Spending 3–5 calls to
  verify one figure is normal and healthy.
- **Judgment over quotas and caps.** There is no hard call budget. But if a
  single *simple* figure is eating 10+ calls with no convergence, the approach
  itself is wrong: stop, change the image source (render-crop vs embed vs
  slice-zoom), change magnification, or ask the user. Never just re-query the
  same pixels harder.
- **Honesty over confidence.** "Unreadable at location X" is always available;
  a fabricated value is never acceptable.
- **Bias is the real enemy.** Establishing a hypothesis from a weak signal and
  then reaffirming it with confirmation reads is how attribution errors get
  locked in. Attribution must be pinned by *independent anchors*, not by
  repeated agreement with an earlier guess.

## When to use

- The user points at an image/diagram and wants it read into labels, values,
  relationships (a circuit, an equation, a figure, a graph, a schema).
- You need a drawing transcribed so you can reason over it — and you want to
  trust *which* drawing it was and *what* it said.
- Do NOT use for PDF color inversion (`pdf-study`) or teaching (`tutor`).

## The pipeline

### Stage 0 — Inventory (free, no vision)

Find every figure and every piece of text that can claim it.

- PDF: `pdfimages -list` (embedded objects: dims, ppi, colorspace) and
  `pdftotext -bbox` (statement/caption positions and reading order).
- Other sources (screenshots, photos, single images): enumerate whatever
  context exists — captions, titles, axis/table headers, adjacent labels —
  and where each sits relative to the drawing.
- List figures, their candidate text, and note when a page has **more than one
  figure** (single-figure ambiguity is where attribution errors are born).

### Stage 1 — Association: pin each figure to its context (the attribution gate)

Attribution is *the* classical failure mode: reading the right pixels and
attaching them to the wrong problem. Never assign a figure to a problem by
document order, filename, or assumption.

- **PDF with embedded rasters:** map each embedded image to its text band by
  *printed size* = `image width / x-ppi` (points on the page), matched against
  the tight crop you get from `-trim` of the render of each caption band. Two
  figures and geometry says which band each belongs to — record that mapping
  before any vision call.
- **Hard block:** if the source has >1 candidate figure and the deterministic
  mapping is inconclusive, do NOT proceed to vision for that figure. Resolve
  geometry first, or ask the user to wave at which drawing they mean.
- **Non-PDF / single-image sources:** skip geometry, go straight to anchoring:
  include the associated text (caption/stem/legend) **in the same frame** as
  the figure. If the context and the drawing can't share one frame (e.g. they
  are far apart), make two crops and state the spatial relationship.
- **Anchor rule (1 call):** any figure you are about to transcribe must be read
  together with (or explicitly tied to) its statement/caption. Transcribe the
  caption verbatim, then cross-check the *label set*: the figure's notated
  labels must be a superset/match of the variables the caption names
  (caption says "find I, I2" → figure must carry those or a consistent near-
  variant like I1,I2; caption "find I1,I2,I3" → figure must carry I1/I2/I3).
  A label-set mismatch means **re-attribute, don't force-fit** — flag both.

### Stage 2 — Extract the region

Get a tight bitmap of only the figure of interest, from the most faithful
source:

- PDF: rendering the page is faithful to what the user sees; extracting an
  embedded image object is cleaner when the drawing is a standalone raster.
  When an embed is low-resolution, prefer a **high-dpi page render crop** of
  that region over upscaling the tiny embed — upscaling can't create the paper
  detail; a render crops whatever fidelity the PDF actually has.
- Crop tightly; neighboring problems, margins, and stray text confuse readers.
- Upscale before sending (Lanczos). Glyph misreads trace back to small text
  (± marks, subscripts, decimals, decimals vs. colons); pixels are the cheap
  fix — but see Stage 6 sanity: if upscaling doesn't converge, switch source.

### Stage 3 — Preflight: the API key and the model

- Read `GEMINI_API_KEY` from the environment every time; never print or hardcode it.
  If it is unset, read `~/.config/anki-gen/gemini.key` (directory `700`, file `600`) if it
  exists, and use its first line. Never echo the value. Missing from both → stop and tell the
  user where to put it.
- **Model guardrail — this cannot bend:** only a flash-lite-class model that is
  on the free tier with a documented high daily request limit (hundreds/day,
  not the ~20/day of mainline flash, never flagship/pro/ultra which can incur
  charges). A wrong pick means mid-task denials or a surprise bill.
- Before the first call of a session, confirm the current free-tier flash-lite
  model from the live rate-limit docs / model list; state the pick before
  spending calls. Fail closed if no model qualifies — never fall back to a
  premium or low-quota model. Do not build quota machinery.

### Stage 4 — Compose the call: domain, schema, integrity hooks

One request: the image inline (base64, not URL) plus a prompt demanding a
single structured JSON object (`responseMimeType: application/json`). Structured
output is what makes every result verifiable at the call site.

**Ask the caller for the domain, target schema, and — optionally — integrity
hooks.** Pass a provided schema through verbatim. If none is supplied, use the
generic entity-graph default:

```json
{
  "entities":   [{ "id", "label", "attributes": {}, "region": "" }],
  "relationships": [{ "type", "from", "to" }],
  "provenance": { "verbatim_text": true, "uncertain": [], "illegible": [] }
}
```

Optional schema companions make verification strong:
- `validators`: local, zero-CPU checks that a correct extract must pass (for a
  circuit: KCL at every node, unique two-terminal endpoints; for a graph: every edge
  endpoint resolves, no dangling ids; for a table: consistent row widths, unit
  prefixes). Caller supplies them; the skill runs them in Stage 6.
- `key_fields`: the answer-determining attributes (circuit example: source
  polarities, given voltages, current/arrow directions, connectivity). These are
  the fields that *must* be confirmed from a second source, not just checked.

The prompt must always demand verbatim reading (no rounding/normalization/
"typo fixes") and honesty about ambiguity (unreadable/cropped/ambiguous → the
`uncertain`/`illegible` list with a location — never a plausible guess).

### Stage 5 — Parse the response

Extract the text payload from the envelope, coerce to the target shape, surface
uncertainty lists. Strip fences/markdown wrappers before concluding.

### Stage 6 — Verified transcription (generic, multi-source)

For every figure, in order:

1. **fetch-1:** the anchored frame (Stage 1) through the schema in Stage 4.
2. **Local integrity:** run the generic consistency check (ids resolve, no
   dups/dangles, verbatim spot-check) **and the caller's `validators`**. A
   failing validator is a red flag on the *extract or attribution*, not the
   figure — re-check before trusting anything further.
3. **fetch-2 (always for key fields):** confirm the answer-determining fields
   from an *independent* image source or a targeted zoom: embed vs render-crop
   vs slice-zoom of the sub-region. Different pixels, different provenance —
   that is the point. ~3–4 calls per figure is the healthy steady state.
4. **Dispute handling:** when sources disagree on a key field, zoom *only* the
   disputed sub-region. If two *different* sources still disagree, treat it as
   unresolved → `uncertain`, and ask the user if the field is required. **Never
   "resolve" by re-prompting the same pixels to confirm** — that is the bias
   trap this whole stage exists to break.
5. **Bias guard:** never inherit attribution, values, or a prior session's
   hypothesis for a figure without re-running Stages 0–1 on it. A cached entry
   graded weak must be re-anchored, not trusted.
6. **Sanity:** if a small figure is consuming >~10 calls without convergence,
   stop and re-plan (new source, bigger magnification, or ask the user).
   Don't grind.

### Stage 7 — Validity, confirm, hand off and cache

- Present the recovered structure, provenance, validation results, uncertainty
  lists; flag what was confirmed vs inferred; hand off.
- Persist a `vision-sidecar` entry per the cache contract below (write-once,
  atomically, reads-only). Do not store solutions or reasoning.

## Cache: `vision-sidecar`

Diagram reads are the expensive artifact and they rarely change — so cache
them, cheaply and visibly.

**Location and naming.** A visible `vision-sidecar/` directory next to the
source (never hidden). One JSON file per source: `<name_with_underscores>.reads.json`,
e.g. `HW/vision-sidecar/HW3_KVL_KCL.reads.json`.

**Contract.**
- **Read-first:** before any network call, if the sidecar exists and its
  `source_sha256` matches the current file hash, serve cached extracts for that
  source — zero calls (Stage 1 reference).
- **Write-after:** persist only after a successful, validated read; atomically
  (tmp + rename); write-once so synced folders stay quiet.
- **Small:** JSON only; never renders/crops/base64. Cap ~64 KB per file;
  decline to cache an extract that would exceed it.
- **Stale by design:** short source hash recorded; edits invalidate cleanly.
- **Disposable / user-authoritative:** any `.reads.json` is deletable at the
  cost of a re-read; a hand-corrected entry is served as-is.
- **Reads only:** structures, labels, values, notes. No solved answers.

**Per-entry provenance (what makes an entry safe to reuse).** Each problem entry
records:
- `association`: how the figure was tied to its context —
  `geometry+anchor` (strongest: deterministic embed↔caption-band match AND
  caption-in-frame read) / `anchor-only` (caption or context in frame, no
  geometry) / `single-image` (sole figure, no ambiguity) /
  `order-assumed` (WEAK — figure assigned by order or filename; never trust,
  re-anchor on load).
- `grade`: `verified` (geometry+anchor and/or multi-source agreement) vs
  `single-pass` (one unanchored or unverified read) vs `weak`.
- `validators_run`: which integrity checks passed.
- `sources`: what pixels were read — embed xref, render-crop coordinates,
  zoom rects, or screenshot paths — so an entry can be reproduced or re-checked.
- `uncertain`: preserved from the reads.

**Weak-flag:** entries whose `association` is `order-assumed` or whose `grade`
is not `verified` must be re-anchored (Stages 0–1) before their content is
used. `verified` entries may be used as-is.

**Regression notes:** keep a machine-readable `revisions`/`regression_notes`
log when a correction is made, so future sessions can see prior failure modes
and not repeat them.

> Canonical failure (referenced by this skill's own regression notes): HW3
> page-2 had two figures whose embedded images were the same topology-ish but
> different circuits. v1 of the sidecar swapped them because attribution used
> document order, captions were never anchored in-frame, and subsequent zoom
> confirmations reinforced the same wrong assignment. The fix was geometric
> embed↔caption-band matching (printed size = width/ppi) plus caption-in-frame
> reads. If you are looking at a place where this skill could fail, that gate
> is Stage 1.

## Guardrails (why they exist)

- **Key hygiene:** env or a `600` key file, never echoed.
- **Honesty over guessing:** a fabricated value poisons the call site with
  confident wrongness; "unreadable at location X" is always available.
- **Fail closed on model choice:** mid-task denials or surprise bills are the
  worst outcomes; a doc check before calling is cheap insurance.
- **Attribution gate:** never assume which figure-identifier a raster belongs
  to without an anchor (geometry or in-frame caption). Bias-reinforcement is
  how intelligence fails — pin facts to independent anchors.
- **Clean up temp artifacts** when done.