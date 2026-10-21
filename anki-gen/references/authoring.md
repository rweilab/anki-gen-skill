# Authoring cards: mechanics

## Authoring cards: mechanics

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
why/answer, source anchor, heuristics checked), then append 10–15 cards for a topic in one
`cards.jsonl` write and validate the batch. A 60-card deck is ~5 writes. The ledger is the
reasoning record; review checks every card has a line. Prefer `.jsonl` for decks over ~30 cards;
use `make_cards.py` for media/programmatic decks and write it in one pass per topic — never edit
one card at a time. The linear 67-card deck used 2 writes + 11 edits; the 99-card midterm used 67
edits and 6× the input.

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
`--show N` prints the card you just named.

**Use the `content` from the EXTRACT JSON directly. Do not read the extracted `.md` back in** — the
text is already in the JSON, and re-reading doubles the context for nothing. Keys: `content`,
`source_type`, `source_path`, `images`, `md` (no `output_dir`; `md` is the file written). `images`
is a count plus a 3-name sample, not the full list; a figure a card needs is cited by name from the
source's own text, and every file is on disk either way.

**Never re-read an artifact the pipeline produced** — not the extract, not `cards.json`, not a file
you just wrote. A 61-card deck is ~13k tokens you already have. Use the narrow instrument:
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

Default: no images; `media` is ignored. When the user asks for figures, list candidates with
`media_index.py <workdir>` and attach only when the caption or slide title clearly matches the
card — never claim to have seen an image, and never guess. Unclear means drop and report it.
`side` defaults to `back`; use `front` when the image *is* the question. Cap: ≤1600 px / ≤1 MB
per image, ≤2 per card; over-cap images are downscaled with Pillow (not dropped) and skipped only
if still over. Every card with `media` is audited in review.

For video frames, read `references/video.md`: one image per card, attach the
marked `BEST` frame (high/medium confidence), and keep the video title/timestamp
as the source. Low-confidence candidates stay in `frames.md`.

For handwritten pages, transcribe with `image-vision` first; a page image is not a substitute
for text unless the user explicitly wants it.

