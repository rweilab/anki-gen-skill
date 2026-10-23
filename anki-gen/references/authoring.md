# Authoring cards: mechanics

**If you emit cards from a Python script, build them with `new_cards.py`** — it moves cheap
mistakes to the line that makes them:

```python
from new_cards import C, dump
cards = [
    C(front=r"**Vacancies.** Why does a crystal contain them at all?",
      back=r"Because forming one costs energy $Q_v$ ...",
      layer="L2", topic="Vacancies", deck=DECK, source="Lec 04 p.12"),
]
dump(cards, "cards.json")
```

`C()` requires `layer`, `topic`, `deck`, `source` as keyword args; it runs `validate_cards`' own
checks as it constructs (same code, cannot disagree) and raises on an error — a dropped `**`, an
unbalanced `$`, a computation-demand front — while the text is in front of you. Warnings collect
into a list `dump()` prints. `new_cards.py --template` prints a starter block. **This does not
replace `validate_cards.py`**, which alone sees deck-wide checks (near-dup fronts, tier-zero
coverage); the batch run on the written `cards.json` is mandatory.

**Author in batches, not one card at a time.** Write a one-line ledger per card (front intent,
retrieval target, why/answer, source anchor, heuristics checked), then append 10–15 cards for a topic in one
`cards.jsonl` write and validate the batch. A 60-card deck is ~5 writes. The ledger is the
reasoning record; review checks every card has a line. Prefer `.jsonl` for decks over ~30 cards;
use `make_cards.py` for media/programmatic decks and write it in one pass per topic — never edit
one card at a time. The linear 67-card deck used 2 writes + 11 edits; the 99-card midterm used 67
edits and 6× the input. **Batch the writes too:** after review, apply independent
per-card edits in one step (several edit calls), not one step per card. Each step
re-sends the whole context, so 14 one-card edits cost far more than two edit steps
with the same changes. If a deck script is used, write it per topic rather than one
huge file followed by many edits. If subagents summarize transcripts, ask for one
line per fact, not prose.

**One authoring path per deck: prefer `.jsonl`.** A `.jsonl` line per card makes a post-review fix
a one-line edit, not a 61-card rewrite; every downstream script reads either form. If a deck script
is used (conventionally `make_cards.py`, using `new_cards.C`), write it in one pass per topic —
never one-card edits. On a large script, `C(..., strict=False)` collects every card error and
`dump()` refuses to write until they are fixed; use it to fix one batch, not to bypass validation.
Use `author.py` scaffold only when there is no script: stubs with
layer/topic/source, fill blanks, `author.py check` prints progress, `author.py finalize` adds
hashes. Do not scaffold and write a script (two sources of truth).

**Write topics in source order.** The builder uses first-appearance topic order as a bias, lifts
each topic's `tier_zero` card first, and softly interleaves topics in larger decks. Small decks
stay grouped. Write topic-by-topic in the order the lecture, chapter, or video presents the
material.

**Line wrapping must not become line breaks in the card.** Wrap for readability; `render.py`
re-flows paragraphs and list items with a space. Joining with `<br>` splits sentences mid-clause.
**Use raw strings for all card text** (rule 4; table in `references/rendering.md`). The one case the table
misses: **never `r`-prefix a string where `\n` is a deliberate newline** — in a raw string `\n`
stays literal and breaks ordered lists. Raw strings for LaTeX/backslashes, normal strings for
intentional newlines. `check_cloze_braces()` also rejects raw-string `\n` leaks.

**Never machine-split a concept into a question by string surgery** (rule 9). **Do not prefix the
front with the topic** (rule 18); bold lead-ins (`**Why:**`, `**Glossary**`) are structure and
welcome. **Scope the forbidden patterns to fronts** (rule 7): `calculate`, `compute`, `derive`,
`solve`, `show that` are fine in a back describing method; rejecting those trains people to ignore
the check. L3 fronts are exempt — a boundary card legitimately narrates a wrong result. A default,
not a law: the calibration table's boundary column governs a learner who would rather be asked
which move to make.

**Edit the source of truth in place — never by shuttling it through a shell.** A whole-file
read-modify-write (`s = open(p).read(); s.replace(...); open(p,'w').write(s)`) puts the entire 60KB
source into context to change one card, and again for the next fix: one real deck needed ten such
operations. Worse, `str.replace` is a near-miss match that silently corrupts a card when the
pattern drifts, and reports success. Use the harness's in-place edit. **Compose the deck in the
file, not in your head first** — the file is the first draft, and `C()` already gives the safety
pre-drafting was buying.

**Address cards by `topic` + `hash`, never by list index.** Every insert or delete renumbers
everything after it; `hash` is identity, `topic` narrows it enough to find by eye. That is why
`--show N` prints the card you just named. Use `roi_report.py --list` to see card numbers, topics,
layers, and fronts without pulling every back into the conversation.

**Use the `content` from the EXTRACT JSON directly for a single-source run. Do not read its
extracted `.md` back in** — the text is already in the JSON, and re-reading doubles the context.
For a pipeline batch, read `sources.md` for documents and/or `transcripts.md` for video once at
classification; per-source `.md` files are for a narrow check. Keys: `content`, `source_type`, `source_path`, `images`, `md` (no `output_dir`; `md`
is the file written). `images` is a count plus a 3-name sample, not the full list; a figure a card
needs is cited by name from the source's own text, and every file is on disk either way.

**Never re-read an artifact the pipeline produced** — not the extract after classification, not
`cards.json`, not a file you just wrote. A 61-card deck is ~13k tokens you already have. Use the narrow instrument:
`roi_report.py --show N`, `triage.py` stdout, `grep`/`jq`. **Stages 8, 9 and 13 consume stdout,
never the file.** **Never fetch, render or dump the review page** — hand over its URL and stop; it
is HTML you wrote, and pulling it back costs thousands of tokens to learn nothing. **Read only what
the source survey chose**, plus the course's learner context and the stage reference — a working
directory holds other work's files; reading them because they were sitting there put ~8k tokens of
unrelated material into one real run. Do not read other work's handoff docs, full tool source, or a
deck/feedback you wrote; use `grep`/`--show`/`cardid.py` last-row. A confirmed script bug is the
exception: read the function, not the file. **Put a conclusion on
disk instead of deriving it in your head** — something reasoned out is re-sent at every later step;
the same thing written to a file costs ~2k to read on the one occasion it is needed. This is why
stages 5 and 6 leave artifacts, and why the deck belongs in a file.

**EXTRACT output directory must be in the current working directory** (e.g.,
`.anki-gen-temp/<topic>`), not `/tmp/`.

## Media (opt-in)

**One media path.** `frames.py` owns candidate quality, `media_index.py` owns ranking and the media
risk audit, `vision_check.py` is the optional confirmation pass, and this file plus
`references/video.md` own policy. Do not invent a second pipeline.

Default: no images; `media` is ignored and a text-only build carries no media at all. Bundling is
opt-in: files are included only with `--media --media-root <work>`; otherwise the `media` field is
ignored.

Figure extraction always happens. `extract_pdf.py [--page-crops auto|all|off]` writes
`<tag>/media/fig_p<page>_<idx>.png` and `<tag>/figures.json` (page, dimensions, bytes, caption,
nearby text, heading, bbox, kind). Captioned textbook pages and vector-only slide pages also get
tight `page-crop`/`slide-crop` images; they are `confirm` candidates, never auto-attached. The
manifest keeps a count + 3-name sample, so stdout never carries hundreds of paths;
`--manifest-full` restores them only for extraction diagnosis.

Extracted raster figures are scored with the same visual metrics as video frames: tiny and
exact-duplicate images are dropped; blank, text-like, and table images are kept and flagged so a
small diagram is not lost. Ambiguous figures are confirmed with `image-vision` only when they are
actually being used for a card. Vector textbook/slide figures are rendered as tight page crops; a
vector-only PPTX still needs a PDF export.

When the user asks for figures, use
`media_index.py <workdir> --cards cards.jsonl --per-card 2`; compact output is path, page, size,
quality, flags, title, and caption, with high-quality figures listed first. Attach only when the
candidate shows the thing the front asks about: caption/slide-title/page match, or nothing.
`--cards` ranks cards that still need media; use `--all-cards` to inspect existing choices. Same
page, same topic, or a generic caption is not enough. Never claim to have seen an image, and never
guess.

A `confirm` crop or frame is **not attachable** without `image-vision` confirmation or explicit
user approval. “More images” is not approval to lower the bar. Do not attach title/outline/agenda
slides, incomplete crops, or whitespace-heavy frames. If no good image exists, leave the card
without one and report how many cards had no acceptable candidate.

If image-vision has no key or exhausts its one bounded retry, the caller may use the ≤6-image
main-model fallback from `SKILL.md` only for images necessary to answer/attach a card. Label that
read as unverified; never present it as image-vision-confirmed.

Web images only on request: high-signal sources first (textbooks, OpenStax, university notes, Paul's
Online Math Notes, Wikimedia, NASA/NOAA, publishers); attach none if the top candidate is not
clearly relevant. The source URL lands in the image caption and the card footer.

`side` defaults to `back`; use `front` when the image *is* the question. A front that says “shown,”
“this circuit,” or “the example” must carry the image on the front or inline the data. Cap:
≤1600 px / ≤1 MB per image, ≤2 per card, soft deck warning at `max(10 MB, 250 KB × image_cards)`;
no hard deck cap. Over-cap images are downscaled with Pillow (EXIF orientation applied), not
dropped, and skipped only if still over. Local-media citations use the recording name + timestamp
and intentionally have no `source_url`.

Packaging is the classic layout — `collection.anki2` + a `media` JSON map + numbered files. Anki's
exporter writes a stub `collection.anki2` for legacy readers, so it is not used.
`assets/mathjax/tex-svg.js` stays the only always-vendored asset; no OCR, no LaTeX-to-image.

Review: image cards are a bounded cross-section (see `references/review.md`); the page serves
`/media/` and shows a placeholder for a missing file. Wrong images go in the comment box.

For video frames, read `references/video.md`: attach the marked `BEST` frame
(high/medium confidence), and keep the video title/timestamp as the source.
Low-confidence candidates stay in `frames.md`. A shared diagram can appear on
several related cards; the main model never reads the image by default, and the bounded
`SKILL.md` fallback is the only exception.

For handwritten pages, transcribe with `image-vision` first; a page image is not a substitute
for text unless the user explicitly wants it.

