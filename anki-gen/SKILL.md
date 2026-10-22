---
name: anki-gen
description: Generate evidence-based Anki flashcards from lecture notes, PDFs, PowerPoint, homework, textbooks, YouTube videos, and local recordings, and review them in a built-in local web page. Use when the user asks to make flashcards or an Anki deck, turn course material into cards, merge a deck, or study with spaced repetition. Outputs .apkg for direct import.
---

# Anki STEM Flashcard Generator

Generate atomic, evidence-based Anki flashcards from STEM course materials with review in a
local web page, optional web deck audit, and optional deck merging.

**Harness-agnostic.** Plain `SKILL.md` + `scripts/`; Claude Code and opencode both discover it.
Paths use `~/.claude/skills/anki-gen/`; substitute the skill's own directory if moved. Only the
entry point differs (`/anki-gen` vs description match); the pipeline is identical.

**Supporting files.** `references/card-writing.md` (read before stage 7), `references/prompts.md`
(stages 5/7/8/13), `references/review.md` (stages 9/10), `references/lessons.md` (when changing a
script), `references/optional.md` (programming decks, known gaps, media, deck audit),
`references/video.md` (video sources), `references/slides.md` (PowerPoint). Each is read
once at its stage, not every step. They ship with the skill; if `references/` is missing, work
from the rules alone (they are the contract).

**Token discipline.** Batch 10–15 cards per topic after a one-line-per-card ledger; read only the
chosen sources, learner context, and the stage's reference; phase-split large reviews. Quality
outranks token, call, and speed savings; never withhold useful evidence, context, or reasoning to
reduce cost. Details: `references/authoring.md`, `references/review.md`.

**Execution.** Never spawn a child `opencode` process (including `opencode run` or
`opencode debug`) or recursively invoke this skill; run the shipped scripts directly.
Never use main-model vision: do not `read` images, frames, scans, screenshots, or
contact sheets. Ambiguous frames go to the separate `image-vision` pass, once per
unique frame and only when needed. Do not probe for LibreOffice, Office, desktop
converters, or random system tools; use the declared extractors. After two failed
tool probes, stop and report the limitation.

## How much to ask, and how much to say

Everything technical here — layers, `tier_zero`, `stratum`, provenance, GUID identity, ROI
axes — is for **you**. The caller experiences two things: how many questions they get, and how
much jargon they hear. Decide the level from the request, not by asking:

| Signal | Read it as |
|---|---|
| Short and casual — "make cards from Lec/", "flashcards for this folder" | **beginner.** Ask at most one question, run every gate silently, don't narrate stages |
| Iterating, "why is this card like that", weighing a tradeoff | **power user.** Be verbose, show reasoning, offer the judgement calls |

**Beginner.** Infer the rest: don't gate on the source survey, don't offer the deck audit, don't
ask about the formula sheet — infer and *state the assumptions in the report*, one line each.
Never narrate the pipeline, report validator warnings, or explain what a layer is. Report four
things: **where the deck is, how many cards, what to study first, what you assumed.**

**Power user.** The rest applies as written.

**No request text, material present.** If the skill is invoked with no topic or source named and
the folder contains files, **do not start a full-folder build.** Ask one short question — what
should the deck cover: a chapter, a topic, an exam, or the whole folder? — and wait. "Everything
here" is a scope decision for the caller, not a default.

**No sources found.** If the folder has no flashcard-able files, do not run the pipeline: read
`references/getting-started.md` and print its text, then stop and wait.

### What to say while it runs

*Status* — "reading the files" — answers the only question a waiting person has: is it working,
should I leave? *Narration* — stage numbers, layer codes, validator output — is noise. Status at
every level; narration never.

| Moment | Say |
|---|---|
| Called, before reading anything | `Looking through the files in this folder…` |
| Extracting a large PDF or several at once | `Pulling the text and figures out…` |
| Before the cards get written | `Building the deck now — this is the slow part, come back in a bit.` |
| Reading feedback back into the deck | `Reading your feedback and rebuilding the final deck…` |
| Handing over the review URL | `Open this link to review the cards, then come back when you're done:` |
| Waiting for "done" | *nothing* — wait |

The estimate is a hedge, not a promise: "come back in a bit" survives a 40-second build and a
ten-minute one; "about three minutes" is wrong both ways. **Beginner extra:** the first URL gets
one clause more — the page scores each card 1–5 and shows why each was picked. Never narrate a
stage number, work-file name, or script name; the `.apkg` path in the report is separate.

### The web review runs by default

It always runs by default and is never offered as a question. A browser page beats a TUI for
judging a card, and a beginner is exactly who should not take the tool's word for it. Honour an
explicit "no review" — but never *ask*. Hand over one short sentence, then the URL alone on its
own line.

### The four interaction points

The gates aren't the friction — they caught a two-order-of-magnitude unit error in a real deck.
Blocking is.

| Point | Power user | Beginner |
|---|---|---|
| Source survey (stage 2) | propose and wait | proceed on stated assumptions; list them |
| Deck audit (stage 3) | run only if asked | **skip** — opt-in only |
| Web review (stage 10) | run | **run** — never skipped, never offered |
| Trim list (stage 13) | propose, get approval | **state it in the report**, apply only if they say so |

### State assumptions; never make silent ones

When you proceed without asking, the report ends with a short **Assumed:** line. A wrong
assumption costs one sentence; a blocking question costs the decision before the caller has
anything to decide it against.

## Rules

Read before writing a card or a script. Each cost a real broken deck.

**Every rule names what holds it.** `[script.py:function]` is a check you can run; **[prose]**
means only this document enforces it — distrust that area when you change it. A rule's `→` name
points to the reference that carries the detail (see **Working references**); don't repeat it
here. **Fold a new lesson into the rule it
belongs to**, or let it replace a weaker one; appending is the last resort. Keep the *why* as a
clause, not a paragraph, unless it changes a decision. The whole file loads every invocation and
only its opening tokens survive a long session — what is duplicated is what gets dropped first.

**Before adding a script, flag or section, walk the ladder: does it need to exist, is it already
here, does the stdlib cover it, can it be one line?** A rule costs a broken deck; a *script* costs
maintenance forever. The 2026-10-17 pass added three scripts and cut one — the cut (extract
condensation) had measured 0.4% on a real corpus before anyone noticed it did nothing. Additions
here are prose, and prose is a bet: three rounds moved no measured number.

1. **A deck that imports is not a deck that reads.** Raw `$...$` backslashes and literal
   `**bold**` fit inside a structurally perfect `.apkg`; structural checks pass on packages Anki
   refuses to open, so the final gate is a real import. `[validate_apkg.py import_test]`
2. **Anki's MathJax is `\(...\)` and `\[...\]`, never `$...$`.** Author `$`, let the builder
   convert; a bare `$` reaching a field is a bug. `[render.py; validate_cards stray-$ check]`
3. **Anki renders no markdown.** Author markdown freely; `[render.py]` converts it.
4. **Write card text in raw Python strings.** `\t`, `\f`, `\r`, `\b`, `\n`, `\v` are Python
   escapes: `\frac` becomes a formfeed, `\text` a TAB — silently. `[validate_cards control-char
   check]` → **Rendering**
5. **Define every symbol on its own card.** "Identify all variables" is an exam objective; a
   formula card without the glossary tests half the thing. `[validate_cards glossary info]`
   → **Every symbol is defined on its card**
6. **A tier-zero concept card comes before each topic's formula cards.**
   `[prose; tier_zero field]` → **A tier-zero card comes before the formula cards**
7. **Forbidden patterns scope to fronts, never backs.** "Set them equal and solve" in a back is
   teaching; L3 fronts are exempt because diagnosing a wrong computation is the point — unless
   calibration says the learner reads boundaries as decisions. `[validate_cards.is_computation_prompt]`
8. **Never put a computed answer on a front.** Given data plus a value out is unanswerable from
   memory and fails quietly: reasonable, well formatted, teaches nothing.
   `[validate_cards.is_computation_prompt; review_server --ask recall]` → **The recallability test**
9. **Never machine-split a concept into a question** by cutting on `=` or `→`. `Atoms per unit
   cell: SC?` is not a question. `[prose]` → **Authoring cards: mechanics**
10. **Anchor every shared term.** Five cards querying an undefined term is a single point of
    failure — blank on the definition, all five unreachable. `[prose; roi_report anchors]`
    → **Anchor cards for shared vocabulary**
11. **Answer the front first, then match its length.** If the front asks “which enzyme/law/step,”
    the back names it in the first sentence; a true explanation that never answers the front is
    broken. A yes/no front with a paragraph back means the paragraph is never read. Demand the
    mechanism, or cut the back. `[validate_cards answer-alignment; prose]`
12. **Speak the course's language**: its terms, its notation, no attribution it never used.
    `[prose]` → **Speak the course's language**
13. **Calibrate scaffolding to the reader — and to backs only.** A front is never calibrated
    down: it must be answerable instantly, by naming the concrete things. `[prose]`
    → **Calibrate before you write a single card**
14. **The deck's value is the fraction of cards failed, not its size.** Retrieval strengthens
    memory; a failed review teaches nothing beyond the re-read, and learners over-test what they
    already know. `[roi_report costliest; review feedback]` → **Retrieval success is the currency**
15. **Cloze is for enumerations that are separately examinable**, never prose, concept cards, or
    one whole formula. `[build_native.check_cloze_braces]` → **Use cloze for enumerations**
16. **Backs explain; they do not restate the front.** `[prose]` → **Backs explain**
17. **Every card carries a citation with a locator.** Cite what the learner can open — numbers on
    the front, citation in the footer — and never invent a URL or timestamp.
    `[validate_cards source checks]` → **Every card carries a provenance footer**
18. **Housekeeping lives in fields, not on the front.** Topic and object tags are already
    displayed above the question; prefixing makes a card read like a form. `[prose]`
    → **Housekeeping lives in fields**
19. **Procedure cards test a decision, never a solution**, and the front states which decision it
    wants. `[validate_cards Procedure-front-warn]` → **The Procedure layer**
20. **Reflow, don't hard-wrap.** Cosmetic source line breaks must not become `<br>`, or sentences
    split mid-clause. `[render.py]` → **Authoring cards: mechanics**
21. **A candidate fact earns a card only if it is not look-up-able, has already caused a
    recurring error, or is reused across topics.** If the learner gets it on the formula sheet
    during the exam, the correct number of cards is zero; if they must recall it from memory, it
    is cardable. When the sheet is given, spend the deck on its absences and the decisions around
    each equation — Anki is the retention system; problem sets, derivations, debugging and labs
    build the skill. Favour representative problems over every homework problem; a clean review
    is not proof of transferable mastery. `[pipeline stage 6 SCOPE GATE artifact]`
22. **Debloat last, and debloating is not minimising.** Target high context *and* low review
    time; split independently examinable facts sharing one schedule, keep items that always
    transfer together. `[roi_report; DEBLOATER PROMPT]`
23. **One deck, named by the caller. Topics are tags, not subdecks** — a deck split per lecture is
    a deck you stop reviewing as a whole, and the earliest material goes unread first. Pass
    through `--deck-name`; `::` nests (`SCHOOL::CIRCUITS::OPAMPS`), the caller's choice, not a
    convention. `[prose]` → **The topic is a chapter name**
24. **Show the reviewer the full front and back.** A truncated card cannot be reviewed.
    `[review_server.py]`
25. **Do not install `katex` or `latex2svg`.** Neither does what this skill once claimed; Anki's
    bundled MathJax is the renderer. `[prose]` → **Rendering**
26. **A back never points at another card.** "See the magnitude card", "as shown above" — each
    card is reviewed alone, random order, so the pointer resolves to nothing where it was needed,
    and the referenced card may have been cut. Put the information in the card. `[prose]`
    → **No cross-card pointers**
27. **A topic is a chapter/lecture heading; object tags are optional.** `topic` names the subject
    a student could look up — `Unit Cells`, `Dislocations`, `XRD & Diffraction`, `Unit Circle`.
    Never a layer code (`L1`), a lecture number, a single card's identity, or a subtopic: one
    Unit Circle deck is all `Unit Circle`, not `Radians`/`Sine`/`Tangent`. `objects` carries 0–2
    broad cross-topic buckets (`concurrency`, `memory`, `rtos`); **zero is normal**. Tags are
    front-visible: never put the answer, method, theorem, or named technique in `topic` or
    `objects`. Do not tag the topic, a subtopic, or a term already explicit in the card; the
    build drops those. `[validate_cards topic-is-layer-code; objects-count; tag-leak]`
    → **The topic is a chapter name**

## Layers

The four layers and the note type each is written in — their only definition; the classifier and
verifier prompts point here.

- **L1 Recall** — facts, definitions, formulas, constants (Basic, Cloze)
- **L2 Understanding** — why/how, intuitions, derivations, analogies (Cloze, Basic)
- **L3 Boundaries** — limitations, edge cases, failure modes (Basic)
- **Procedure** — method selection and next-step prediction (Basic)

**L3 fronts are exempt from the forbidden-pattern rule** (rule 7) — a boundary card legitimately
narrates a wrong result, and diagnosing it *is* the objective. **Procedure is constrained by rule
19.** There is no Type-in and no Image Occlusion note type: the build emits Basic and Cloze.
Behind this: Bloom's taxonomy (the layers are its recall → understand → apply → analyse ladder),
cognitive load (one card, one load), retrieval practice (Q→A, never recognition), desirable
difficulty (cloze; don't let a front give away its answer), and spacing (FSRS handles it).

## Pipeline Stages

**Budget: a whole-corpus run is ~25 steps, not 80.** Steps are the cost, not tokens — every step
re-sends the whole context, so 80 steps pays for its context 80 times. Batching: **one step may
carry several independent calls** (source listing and extract in one; validate, triage and ROI in
one). Five habits:

- **Gather the inputs once.** A directory listing, a script's `--help`, an environment probe —
  independent, so one step, not four.
- **Let a script do a whole stage.** One `pipeline.py` call beats five script calls plus ad-hoc
  Python. `pipeline.py --sources ... --out ...` extracts; re-run with `--cards ... --gates-only`
  for the gates.
- **Write to disk, read back once.** Reasoning is re-sent at every later step; a file read once is
  not.
- **Don't re-read to confirm.** A file you or a script wrote is on disk and will not have changed.
  There is no confirm step.
- **Read allowlist.** Chosen sources, learner context, and the stage's reference; not other work's
  handoff docs, full tool source, or a deck you wrote — use `grep`/`--show`. A confirmed script bug
  is the exception: read the function, not the file.

Fourteen numbered stages follow. Batch independent calls; a clean run is about 25 steps, not 80.
The review round-trip and the build are part of that count.

All scripts live in `~/.claude/skills/anki-gen/scripts/`; run each as `python3 <that
path>/<name>.py`. Batch the separable calls: **build and validate_apkg in one step; roi and the
pre-build gates in one step; read the chosen extracts in one step.** Never re-read an artifact.
Below, `$WORK` means `.anki-gen-temp/<topic>`; every deck artifact lives there, and every command
uses `$WORK/cards.jsonl` (or the same file named `.json`).

```
1. PARSE INTENT   → parse_intent.py "<request>" "<cwd>". Read the whole JSON: sources,
                    date_filter, merge_target, audit_web, course_hint, recursive, deck_name,
                    max_cards, output_path. A lexicon: read the request yourself for the rest.
                    Run it so audit_web, max_cards and merge_target are not silently lost.
                    `recursive` is currently always true; pass a date filter to
                    pipeline.py with `--date-filter` (or use extract_pdf.py directly).
2. SOURCE SURVEY  → survey, PROPOSE sources with a reason each, then STOP for confirmation
                    (beginner: proceed on stated assumptions). Write the answers to
                    $WORK/intake.md (deck, learner, sources, video range, images yes/no,
                    review preference, assumptions). If a later stage finds it
                    missing, ask once rather than guessing. See `references/survey.md`.
3. DECK AUDIT     → optional, opt-in only. Search AnkiWeb/GitHub/Reddit, audit by hand
                    against "DECK AUDIT" in `references/optional.md`. Modal outcome: generate your own.
4. EXTRACT        → prefer pipeline.py --sources <...> --out .anki-gen-temp/<topic>
                    for PDFs, text, PowerPoint, URLs, and directories (one call).
                    For a single-source diagnosis use extract_pdf.py "<source>"
                    "<cwd>/.anki-gen-temp/<topic>" --tag <tag>. PPTX text/notes/
                    embedded images are parsed without Office. Local media goes
                    through stage 4b.
                    (--date-filter limits directory sources). Single-source prints
                    content/source_type/source_path/images_count + a 3-name sample/md; batch
                    prints a manifest with counts and samples
                    of <tag> dirs + md paths (read the .md when classifying). Cite the
                    file the text came from ("Lec 04 · p.12"), not the topic dir.
4b. VIDEO/MEDIA   → read $WORK/intake.md, then pipeline.py --sources "<url-or-local-path>"
                    --out "$WORK" [--images yes|no] [--model auto]
                    [--whole-playlist | --items 2-5] [--title "..."] (preferred).
                    Direct extract_video.py "<url-or-local-path>" --work "$WORK"
                    is the single-source diagnosis path. Writes
                    timestamped transcript chunks, transcripts.md (compact,
                    deduplicated, token-estimated), video_toc.md, and optional
                    frames.md/frames.jsonl. Manual captions first, auto captions
                    fallback. Missing/rate-limited captions still register and run
                    frames; search one official companion article/slides from the
                    title/description. Local files use sidecar VTT/SRT or local
                    faster-whisper; source_url is empty for local media. Read
                    transcripts.md and frames.md next.
                    Frames are scored and ranked; attach `direct` frames, and confirm
                    ambiguous `confirm` ones with the separate image-vision skill when a
                    key exists; its `vision_check.py --max N` is the fast, cached pass.
                    The main model never reads frames; do not make contact sheets or scan
                    galleries. Read frames.md, not the whole candidate list. Use
                    `frames.py --sweep 00:00-02:30 --every 10` for a missed chapter; do
                    not sleep or poll yt-dlp; the scripts retry briefly and report skipped videos.
                    `pipeline.py --vision auto --vision-max 12` is the opt-in bounded
                    pass over canonical frames; it writes vision.jsonl.
5. CLASSIFY       → atomic concepts {layer, topic, objects, type, source} from content.
6. SCOPE GATE     → the do-not-card list in .anki-gen-temp/<topic>/scope_gate.md, BOTH
                    halves: what the formula sheet prints, and — the high-yield part —
                    what it does NOT print. If a sheet is provided, ask once: memorised →
                    card them as recall; given → do NOT card them (rule 21), spend the deck
                    on absences and decisions around each equation. Beginner: infer "given"
                    and put it on the **Assumed:** line. This filters the classified concepts
                    before write. Required, and it must leave a file: a deck that skipped it
                    looks identical to one that needed none. On the run that produced this
                    rule, doing it by hand was the difference between 55 cards and 150.
                    `pipeline.py --build` refuses without intake.md, scope_gate.md and
                    authoring_ledger.md unless `--allow-missing-artifacts` is passed.
7. WRITE          → read only the relevant card-writing sections (the rule map is at
                    its top), plus `authoring.md` and `schema.md`, then write
                    $WORK/cards.jsonl (front, back, layer, topic, objects, deck, source;
                    `cloze: true` on any `{{cN::}}`; `tier_zero: true` on the topic concept
                    card) with a locator, a glossary of every symbol, a plain-English why,
                    and a tier-zero card before each formula card. **Ledger, then batch:**
                    write `.anki-gen-temp/<topic>/authoring_ledger.md` (one line per card:
                    intent, retrieval target, why, source, heuristics), then 10–15 cards for the topic in one
                    write; validate the batch. Avoid redundant retrieval targets and plan a
                    soft 4–15-card topic budget; exact front/back duplicates are errors. One authoring path per deck: prefer .jsonl;
                    if a deck script (conventionally make_cards.py, using new_cards.C), write
                    it in one pass per topic — never one-card edits. Use author.py scaffold
                    only when there is no script: stubs with layer/topic/source, fill blanks,
                    `author.py check` prints progress, `author.py finalize` adds hashes. Do
                    not scaffold and write a script (two sources of truth). `.jsonl` one line
                    per card makes a post-review fix a one-line edit, not a 61-card rewrite;
                    every downstream script reads either form.
                    Media is opt-in and main-model-vision-free: entries are `{file, side,
                    caption, source}` with `<tag>/media/<file>` paths. Attach only when the
                    user asked, from a caption/slide-title/page match or a high-signal
                    source; `media_index.py <work> --cards cards.jsonl` ranks the best
                    3-5 per card by locator + caption/nearby text. Never auto-attach.
                    Unclear → drop and list it. Slide/page crops are `confirm`; video frames: attach high/medium
                    confidence frames; low-confidence frames stay in `frames.md`. A shared
                    diagram may be attached to several related cards; reuse is expected.
                    Read the detail in `references/authoring.md` and `references/video.md`.
                    Video source: `source` is the full `<channel> - ... - <title> @ mm:ss`
                    line; `source_url` is the plain timestamp URL (series includes the playlist).
                    Read $WORK/intake.md for images yes/no and the video range; do not re-ask.
8. VERIFY (static) → validate_cards.py $WORK/cards.jsonl — escapes, delimiters, leaked markup,
                    computation fronts, duplicates, front-visible tag leaks, answer overlap,
                    missing glossary/provenance. Layer 2 is
                    the stage-7 batch self-check or the triaged review, never a corpus audit.
9. TRIAGE         → read `references/review.md` first, then
                    triage.py $WORK/cards.jsonl -o $WORK/review_plan.json — picks a small
                    cross-section, not the deck. Always run, any deck size.
10. REVIEW (web)  → read $WORK/intake.md (learner/review preference) and
                    `references/review.md`. review_server.py --cards $WORK/cards.jsonl
                    --plan $WORK/review_plan.json --media-root "$WORK" --out
                    $WORK/review_feedback.jsonl --done-file $WORK/review_done.
                    Background, hand over URL, WAIT; do
                    NOT print card text into chat. On "done", reduce the log with
                    `cardid.py` (last row per card), read only low scores/comments, generalise,
                    re-scope (see `references/review.md`). The 1–5 scale is the primary review;
                    `--ask recall` is a second pass (default log `review_recall.jsonl`), never
                    a substitute.
11. BUILD         → prefer pipeline.py --cards $WORK/cards.jsonl --gates-only --build
                    --deck-name "Name" --out-apkg ./<deck>.apkg (build + validate in
                    one call). `--work`/`--out` is the work directory; a `.apkg`
                    there is rejected, because the deck belongs in `--out-apkg`. Direct build_apkg.py is the diagnosis path, in the
                    CALLER'S CWD (never the work dir). Needs `anki`.
                    Static validation is the default; `--allow-invalid` is diagnosis
                    only. --merge-existing adds only cards
                    whose hash is absent (idempotent, prints skip count). Media is bundled
                    only with `--media --media-root <work>` when intake says images: yes
                    (default off; --media-root defaults to the cards.jsonl directory). A hand-authored deck script is the source of
                    truth during the run; stage 14 promotes it only to a caller-named path, or
                    deletes it and the .apkg is one-shot.
                    A missing evidence file is a hard stop; `--allow-missing-artifacts` is
                    for a draft only. Static validation is automatic; `--allow-invalid` is
                    diagnosis only.
12. VALIDATE      → validate_apkg.py out.apkg — the only step that sees a deck which imports
                    cleanly but is unreadable.
13. DEBLOAT (ROI) → roi_report.py $WORK/cards.jsonl, then the deblating pass (prompt in `references/prompts.md`).
                    Report concept overlap and media reuse; never cap or trim a deck
                    automatically.
                    After *every* content change; step-10 feedback is measured and outranks
                    the report's surface heuristics. In the main process, not a subagent.
14. CLEANUP       → run after the .apkg validates. The .apkg is the ONLY new file left in the
                    caller's directory. (1) Stop the review server; verify nothing listens.
                    (2) Read review_handoff.md before deleting; if a fresh review session has
                    not read it, copy it beside the promoted source. Delete
                    .anki-gen-temp/<topic>/ in full — cards.json/.jsonl, deck script,
                    extract, video cache, transcripts, frames, media, ledger,
                    review_plan.json, feedback, logs. (3) Do NOT create
                    a source folder or any other file in the caller's cwd to "keep the source":
                    promote only to a path the caller explicitly named; otherwise delete it
                    and say the .apkg is one-shot. (4) Never delete or move a pre-existing
                    file. (5) Verify the only new entry is the .apkg; .anki-gen-temp is gone.
                    (6) Remove the skill's `scripts/__pycache__` if present (bytecode scratch).
```

**Stages 1–2 and 4–14 are mandatory; stage 3 is opt-in.** A beginner may run stage 2 silently on
stated assumptions. After any content change re-run 8 and 13 before the next build. Every defect that shipped passed the old validator, which checked only empty fields and
cloze syntax: raw `$...$` and literal `**bold**` scored `"valid": true`.

**Regenerate, do not patch, when the deck came from a script.** The `.apkg` is a build artifact of
a deck script (conventionally `make_cards.py`) or `build.py`; every content edit belongs in the
script (or the `cards.jsonl`/`.json` it emits) and is produced by re-running it — never hand-edit
the JSON, never edit cards inside Anki during the run and call that fixed. Hand-edits are silently
lost on the next run; the `.apkg` is never the source of truth. After delivery, a pure wording fix
in Anki may keep scheduling history, but it must be mirrored in the source before any rebuild.

## Reporting
The report is the last thing the caller reads; for a beginner it is the whole experience.

**Beginner — four lines, then stop:**
```
<path/to/deck.apkg>   ·   N cards
Study first: <the 2–3 highest-weight topics, and why>
Assumed: <formula sheet given, not memorised — say the word if you want them carded>
<optional: a one-line cut list, only if there is one>
```

**Power user — add** the per-stage results, validator warnings, the ROI reading, what the review
found, and the gates that fired. **Both:** never narrate the pipeline; give the status lines while
it happens, report results after. Never quote card text into the conversation — that is what the
review page is for. Name cards by `topic` and number so the caller can run `roi_report.py --show N`.
The **Assumed** line is not optional when you skipped a question to reduce friction: it is the only
thing between a fast default and a silently wrong deck.

## Working references

Read each file once, at the stage named. The rules above are the contract; a reference is the
explanation. If `references/` is missing, work from the rules alone.

| File | Read | Carries |
|---|---|---|
| `references/card-writing.md` | before stage 7; read the section | calibration table, symbols, tier-zero, anchors, cloze, recallability, provenance, topic/objects, Procedure |
| `references/authoring.md` | before stage 7 | ledger, batch sizes, new_cards, raw strings, edit-in-place, reading discipline |
| `references/schema.md` | lookup while writing JSON | required fields, objects, Basic/Cloze templates |
| `references/rendering.md` | only for render/hard-break/night-mode changes | MathJax delimiters, raw-string escapes, hard breaks, night-mode guard |
| `references/prompts.md` | stages 5/7/8/13; read only that stage's prompt | classifier, writer, verifier, debloater |
| `references/survey.md` | stage 2 | what to propose, learner-context files, deck-name ask |
| `references/review.md` | stages 9/10 and the review handoff | triage budget, score meanings, generalise/re-scope |
| `references/output.md` | at the end | cleanup, deck naming, GUID identity, merge |
| `references/video.md` | when the source is a video | transcripts, playlists, frame cues, auto-picking, legal |
| `references/optional.md` | when relevant | programming decks, known gaps, media, deck audit |
| `references/lessons.md` | when changing a script | regression lessons |
| `references/getting-started.md` | when no sources are found | the beginner intro copy |
| `README.md` | setup | dependencies, vendored MathJax |

## Image-heavy or handwritten sources

Text-first. If a source is scanned/handwritten (near-empty text with images), or a figure is
the only source for a fact, use the separate `image-vision` skill (Gemini) to read it — never
build from empty text; ask once for handwriting, never about ordinary figures. Attach only on
request (`--media`); review audits it. A structure or reaction answer may need a verified image
or manual Anki addition.

