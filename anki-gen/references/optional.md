# Optional references

## Card patterns for programming languages

Only the categorizations, not per-language lists. In rough order of yield: **distinctions** —
near-identical constructs with different behaviour (blocking vs non-blocking assignment; `*` vs
`.*`; pass-by-value vs reference) — the highest-yield coding category; **behaviour prediction** —
"what does this snippet print/return?" tests execution semantics, not recognition; **look-up
avoidance** — argument order and return values you actually keep searching for (rule 21 applied to
a library); **error diagnosis** — "why did this fail?", tied to the language's failure modes;
**anti-pattern** — do not turn a codebase into cards or memorise rarely-used commands; does the
retained knowledge improve real implementation or debugging? Mechanical limit: the markdown
renderer supports **inline** `` `code` `` only — no fenced blocks, so keep code cards to inline
snippets or add block support in `render.py`.

---

## Known gaps — considered and deferred

Recorded so they are not re-derived; promoting one to a rule needs a reason, usually that the skill
started getting it wrong. **Interleaving is not always right** — it aids discrimination but hurts
initial acquisition (Rohrer & Taylor), so blocking by topic is usually correct near an exam.
**Unlabelled retrieval** — real exams don't announce the chapter, so a topic-organised deck can
train chapter-bound retrieval; handled only implicitly by stripping topic prefixes. **Worth
memorising at all** — promoted to rule 21. **Contrastive design** — deliberately juxtaposing
confusables (the reciprocal pair, wt% beside at%) is a feature; the deblater treats interference as
a defect, but the confusion is the test. **Desirable difficulty is unbounded** — nothing checks
whether a front gives away its own answer. **Practice cards with a full worked solution** —
considered and declined: the Procedure guardrail rejects "a problem-set item wearing a card's
clothes"; a full solution is not a retrieval target.

---

## Media Handling (opt-in)

Figure extraction always happens; **bundling is off unless the user asked.**

- `extract_pdf.py [--page-crops auto|all|off]` writes `<tag>/media/fig_p<page>_<idx>.png` and `<tag>/figures.json` (page,
  dimensions, bytes, caption, nearby text, heading, bbox, kind). Captioned textbook pages and
  vector-only slide pages also get tight `page-crop`/`slide-crop` images; they are `confirm`
  candidates, never auto-attached. The manifest keeps a count + 3-name sample, so stdout
  never carries hundreds of paths; `--manifest-full` restores them only for extraction diagnosis.
- The model chooses from `media_index.py <workdir>` or `--cards cards.jsonl` (compact: path, page, size, quality,
  flags, title, caption) — **never vision**. High-quality figures are listed first;
  caption/slide-title/page match, or nothing.
- Extracted raster figures are scored with the same visual metrics as video frames:
  tiny and exact-duplicate images are dropped; blank, text-like, and table images
  are kept and flagged so a small diagram is not lost. Ambiguous figures are confirmed
  with `image-vision` only when they are actually being used for a card. Vector
  textbook/slide figures are rendered as tight page crops; a vector-only PPTX still needs
  a PDF export.
- Build with `--media --media-root <work>`; a text-only build carries no media at all.
- Web images only on request: high-signal sources first (textbooks, OpenStax, university notes,
  Paul's Online Math Notes, Wikimedia, NASA/NOAA, publishers); attach none if the top candidate is
  not clearly relevant. The source URL lands in the image caption and the card footer.
- Caps: ≤1600 px and ≤1 MB per image, ≤2 per card, soft deck warning at
  `max(10 MB, 250 KB × image_cards)`; no hard deck cap. Over-cap files are downscaled with Pillow
  (EXIF orientation applied), then skipped only if still over.
- Packaging is the classic layout — `collection.anki2` + a `media` JSON map + numbered files.
  Anki's exporter writes a stub `collection.anki2` for legacy readers, so it is not used.
- Review: image cards are a bounded cross-section (see `references/review.md`); the page serves
  `/media/` and shows a placeholder for a missing file. Wrong images go in the comment box.
- `assets/mathjax/tex-svg.js` stays the only always-vendored asset. No OCR, no LaTeX-to-image.

---

## DECK AUDIT

Optional; run only if the request asks, never offer it in the survey. No script — the search and audit are
yours. (An earlier `deck_audit.py` never scored anything and shelled out to a missing binary; the
wrapper was removed, the judgement kept.)

1. Search AnkiWeb, GitHub and Reddit for decks matching `course_hint`.
2. Judge the top 3–5 against *this* skill's principles — the audit rubric, so nothing repeats them:
   atomicity (rules 8, 11, 22) 30%; layer coverage and tier-zero (rules 6, 19) 25%; no computation
   prompts (rules 7, 8) 25%; provenance (rule 17) 10%; formatting (rules 2, 15) 10%.
3. Report the scores, recommend the best, and say plainly if none is worth having — "generate your
   own" is a legitimate verdict.
4. If the user accepts one, download it and set it as the merge target.

- **Video frames are opt-in.** `extract_video.py`/`frames.py` support YouTube
  transcripts and 720p stills; automatic scoring, with image-vision confirmation
  for ambiguous candidates when available. The main model never reads images;
  media may be reused across related cards. Personal study only; cite URL +
  timestamp. See `references/video.md`.
- **Handwritten/scanned pages are not OCR'd by the builder.** Use the separate
  `image-vision` skill (Gemini free tier) to transcribe; ask once. A figure that is the only
  source for a fact can be read the same way; attach it only if the user asked.

