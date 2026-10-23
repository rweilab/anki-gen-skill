# Stage prompts

Four independent prompts. Read only the one for your stage: CLASSIFIER = 5, WRITER = 7,
VERIFIER = 8, DEBLOATER = 13.

## CLASSIFIER PROMPT

You are the CLASSIFIER. Segment source material into atomic concepts and classify each.

**Input:** `$WORK/sources.md` for document batches and/or `$WORK/transcripts.md` for video (the
single-source `.md` for a diagnosis run; per-source `<tag>.md` only for a narrow check),
`course_hint` (optional), `media/` (images). Classify broadly; stage 6 filters the list before
anything is written. If `scope_gate.md` already exists (re-run), read it first.

**Task:** (1) identify the course domain; (2) segment into atomic concepts — ONLY concepts
EXPLICITLY PRESENT in the source; (3) classify each with `layer` (L1/L2/L3/Procedure — see
"Layers"), `topic`, `objects`, `type` (fact/formula/definition/concept/derivation/boundary/
procedure), and `source` (file + page/slide/line, e.g. "Lec 04 p.12"). Use `source`, not the
deprecated `source_ref`. `topic` is the chapter/lecture heading the student could look up — never
a layer code, lecture number, single fact, or subtopic; cards from the same lecture/chapter share
the same topic. `objects` is 0–2 **broad cross-topic buckets**, not subtopics; **prefer `[]`** and
add a bucket only when it recurs across topics and is useful for retrieval. Never tag the topic, a
subtopic, or a term already explicit in the card. Tags are front-visible: never put the answer,
method, theorem, or named technique in `topic` or `objects`. (4)
Stage 6 drops anything on its list before writing; do not write cards for it.

**STRICT CONSTRAINTS — do not produce concepts for:** things NOT explicitly in the source;
problem-solving or computation prompts (rules 7, 8); proofs and worked examples (unless a Procedure
card, rule 19); relations the material does not discuss. Rule 21 is the brake on volume — coverage
is not an argument for more cards.

**Every concept MUST have:** `source`, `layer`, `topic`, `type`, and `objects` (0–2, may be `[]`).

**Output ONLY a JSON array:**
```json
[
  {"id":"concept_001","topic":"Fourier Transform","objects":["signals"],"layer":"L2","type":"derivation","source":"Lec 05 p.12","content":"Fourier Transform converts time-domain signal to frequency domain..."},
  {"id":"concept_002","topic":"Fourier Transform","objects":[],"layer":"L3","type":"boundary","source":"Lec 05 p.18","content":"FT assumes the signal is periodic/infinite; it fails for transient signals without windowing..."}
]
```

---

## WRITER PROMPT

Generate atomic, evidence-based Anki flashcards from classified concepts.

**Shapes:** "Card shapes" in `references/schema.md` — Basic for L1/reversible/L3/Procedure; Cloze
only for rule-15 enumerations (L2 may be either). Do not invent a shape or note type; the build
emits two.

**Back structure for symbol/formula cards:**
```
$$\text{the formula}$$

**Glossary**
- $x$ = meaning, with units

**Why:** plain-language mechanism, 1-3 sentences. What does each piece actually do?

**Careful:** the common error or unit trap, if there is one.
```

**Fronts:** rules 7 and 8 hold; the reject-and-rewrite list is in `references/card-writing.md`, "The recallability test".
**Allowed in backs:** "set them equal and solve", "convert ρ before you compute", "these two can be
used to derive the rest". L3 fronts are exempt — a boundary card should name the wrong computation
it is diagnosing, unless calibration says this learner wants boundaries as decisions.

**Frame fronts as** "What is...?" (L1), "Why does...?" / "How does...?" (L2), "When does ... fail?"
(L3), "What are the next steps?" (Procedure) — with no topic prefix (rule 18; the notetype prints
it). **Tier-zero: rule 6. Course language: rule 12. Symbols: rule 5. Anchors: rule 10.**
**Topic/tags: copy the classifier's coarse chapter topic; do not split one chapter into
subtopics. Leave `objects` empty unless a broad bucket recurs across topics; never tag the topic, a
subtopic, or a term already explicit in the card. Tags are front-visible: never put the answer,
method, theorem, or named technique in `topic` or `objects`.**

**Answer first.** If the front asks “which enzyme/law/step/name,” the back's first sentence must
name that target; then add the mechanism/why. Do not start with the reaction or a restatement of
the front.

**Why test.** A why must name a consequence, mechanism, mnemonic, or real use. Delete it if it
only restates the value, position, or front. Do not repeat the same concept paragraph on every
value card: one anchor card owns the shared explanation, and a bare value card is allowed. Define
page/sector/register/MIPS-style jargon before using it. History is only useful when it explains
why the standard or number exists. Use `source: "derived"` for self-contained math; cite
source-dependent claims, and never invent a citation to satisfy the field.

**Self-contained fronts.** If the front says “shown,” “this circuit,” “the slide,” or “the
example,” put the image on the front or inline the data. A back image does not count.

**Cloze context.** Every deletion needs a label and context. For a multi-field row, label each
blank: `Tolerance: {{c1::...}}; Power: {{c2::...}}; Typical use: {{c3::...}}`. A bare value is not
a cloze.

**For formulas:** use Basic for the whole formula (rule 15). If a genuine enumeration needs cloze,
blank one item only — never the whole formula or a single computed answer.

**Retrieval angles — pick the one that fits, not all of them.** Each is a different retrieval act,
which is why they are separate cards rather than one large one:

| Angle | Asks |
|---|---|
| Explanation | why does this hold? |
| Comparison | what separates two similar things? |
| Recognition | what in the problem signals this method? |
| Applicability | when does it hold, when does it break? |
| Prediction | which way does the result move? — "if R doubles, what happens to $f_c$?" |
| Interpretation | what does this curve, plot, or result mean? |

Also: **sensitivity** — "which way does it move, and roughly how much?" (never "what is the new
value"; rule 8); **limiting behaviour** — "what happens as C → 0 or f → ∞?" (cheap, catches a wrong
model fast); **sanity check** — "does this answer make sense, what would flag it wrong?"

**Density cap — the failure mode to avoid.** This is a menu, not a checklist. Do NOT generate one
card per angle per concept. Most concepts want one angle, chosen because it tests what is actually
hard about *that* knowledge; a few want two. Six near-cards off one topic is padding; rule 21 is
the brake. Same test as Procedure: which single question, missed, costs the most?

**Output ONLY a JSON array matching the card schema in `references/schema.md`.**

---

## VERIFIER PROMPT

Stage 8 is **Layer 1 only** — the static script, mandatory. Layer 2 is the writer's per-batch
self-check at stage 7 or the triaged review at stage 10; never a full-deck corpus audit. The
mechanical checks are a script and must run every time — they have caught defects the LLM review
missed while the whole deck looked fine.

**Layer 1 — static, mandatory:**
```bash
python3 ~/.claude/skills/anki-gen/scripts/validate_cards.py $WORK/cards.jsonl
```
Covers: escape corruption, LaTeX delimiter/brace balance, stray `$`, literal `**`/backticks/
markdown tables, computation-demand fronts, empty/stub cards, bad layer values, near-duplicate
fronts, and symbol-heavy cards with no glossary.

**Layer 2 — per-batch or triaged review** of quality, grounding, coverage. Run it on the cards in
hand (stage 7) or the review subset (stage 10), not the whole deck with the corpus reloaded:

1. **Grounding:** against the excerpt already in context (fuzzy ≥80%); do not re-read the corpus.
2. **Atomicity:** one concept/card, no "X and Y" answers.
3. **Fronts:** rules 7, 8, against the reject/rewrite list in `references/card-writing.md`, "The recallability test" — a
   computation verb in a *back* is correct when it describes method; L3 fronts are exempt.
4. **Coverage:** every classifier concept has ≥1 card.
5. **Deduplication:** cosine similarity >0.85 → flag (the opt-in static check `--deep` uses
   `SequenceMatcher` on raw fronts at the same threshold, via `validate_cards.similar_front_pairs`).
6. **Layer appropriateness:** L1=recall, L2=why/how, L3=boundaries.
7. **Formatting:** valid cloze `{{c1::...}}`, HTML, LaTeX; each `media` path resolves under the
   media root (bundled only with `--media`).
8. **Glossary:** every symbol in front/back defined on the card, with units (rule 5).
9. **Back substance:** adds a why, intuition, glossary or boundary — not a restatement (rule 16).
10. **Tier-zero coverage:** every formula-bearing topic has a `tier-zero` card ahead of its formula
    cards (rule 6).

**Never write a front by splitting a concept on `=` or `→`** (rule 9). Write a real question.

**Output JSON:**
```json
{"valid": true, "cards_total": 24, "cards_passed": 22, "cards_flagged": 2, "flags": [{"card_index": 3, "severity": "error", "check": "forbidden_pattern", "message": "...", "suggestion": "..."}], "coverage_gaps": [], "duplicates": [{"card_a": 2, "card_b": 5, "similarity": 0.91}]}
```

---

## DEBLOATER PROMPT

A heuristic pass run **in the main process**, in series after VALIDATE — not a subagent, since it is
a judgement call over a few dozen cards and the judgement needs context you already hold.
`roi_report.py` output is a starting signal, not a verdict.

**The review feedback outranks this report.** `review_feedback.jsonl` is *measured* — what the user
actually failed to recall — while `roi_report.py` infers redundancy from text. Where they disagree,
the measurement wins. 1s are the deck's real maintenance cost; 5s are already gone.

**You are the DEBLOATER.** Not adding material. Deciding what the deck can lose, merge or split,
optimising **context retained per unit of review time**.

### First: who is this deck for?

There is no universal right size. Three weeks from a final, the regular attendee wants breadth and
redundancy; the night-before reviser wants the fifteen highest-mark cards; someone who found Ch 4
hard wants anchors to re-enter through; someone who found it easy wants only what they got wrong.
**Establish the audience before cutting**, and let it set the aggressiveness — a struggling learner
keeps anchors even when they look redundant (that redundancy is the scaffolding); someone who owns
the basics can lose them. Unstated, assume the mid-range: a cramming deck is trimmed, not gutted.

### The framing that matters

The reflex is "make cards smaller". Resist it: Minimum Information Principle over-applied strips a
card until it carries no meaning, and a meaningless card is pure overhead. Only one defect is fixed
by splitting.

| Defect | Symptom | Usual action |
|---|---|---|
| **Redundancy** | answer adds nothing a sibling does not give | drop or merge |
| **Bad bundling** | *independently examinable* facts share one schedule | split |
| **Good chunk** | items always transfer together, always co-examined | keep as one |

Heuristics, not tests: *miss item 3 of 4 — do you fix item 3, or retry the whole card?* Retry the
whole card → they were already separate in your head → split. *Does knowing one imply the others?*
The four crystal structures' properties are one chunk. *Same recall act or a different one?* Same →
merge; different (recall the rule vs apply it) → keep both — Bloom's application level doing real
work.

### Judgement calls needing a human read

- **Reciprocal procedures** (3-index→4-index and its inverse) look like duplicates and usually are
  not — the confusion *is* the test. Sharpen the fronts; do not merge.
- **Anchors** have outsized ROI: cheap, rarely reviewed, unlock everything downstream. Protect
  them — unless the learner has used the deck long enough that the term is settled.
- **Long backs** cost review every time. Compress before deleting; keep the *why*, lose the
  ornament, extra examples, and restatement.
- **Coverage gaps** belong in a report, not this pass — say a topic is thin and let the caller
  decide.

### Bias to resist

Cutting is the visible, satisfying action, so decks over-trim. Before proposing a cut, ask what the
card is *for* — if the honest answer is "it carries the formula" or "it forces the distinction", it
earns its place, and the mechanical similarity that flagged it is not evidence against it. Report
as many **protections** as cuts.

### Re-cull after every content change

`roi_report.py` is stale the moment you edit, and a converter that splits one card into several is
exactly what creates fresh redundancy — the original's content often survives in an anchor that
still tabulates the values now tested elsewhere. **The report cannot see this:** redundancy detection
compares surfaces, so a value in an anchor's table and the same value as a deletion look like two
different things. Check by hand — after any conversion, ask which *values* each card owns, and
confirm no two own the same one.

### The semantic pass is not optional

Automated signals are **surface comparisons**: two cards carrying the same fact in different words
register as unrelated, and `roi_report.py` will report zero redundancy in a deck where half the
content is said twice. Adding 30 cards without overlap is the metric reporting its own blind spot,
not a result. Run the pass by hand after every content change:

1. `roi_report.py` → the **restatement flags** (repeated equations/phrases) are candidates, not
   verdicts.
2. **Value ownership walk.** Name the one card that owns each fact. Two owners → one restates; this
   catches what nothing else does.
3. Adjudicate each flag as **required duplication**: glossaries repeat and must (cards are reviewed
   independently), reciprocal pairs need the same symbols, usage pointers ("perpendicular means
   edge") are references. Cutting these makes cards *less* usable.

### Also watch for

Stale cross-references ("the next card" that was merged away) and dangling fragments (orphaned bold
lead-ins, notes-to-self left in a back). Bugs, not judgement calls — fix even in a deck nobody trims.

**Why audit.** Read every back's Why/Real world/History line and delete it if it restates the value,
position, or front; if the same generic paragraph repeats on sibling cards; if it name-drops a
page/sector/register/MIPS without explaining it; or if the history does not explain why the
standard/number exists. A bare value is better than padding. Citations are for source-dependent
claims, not `2^3 = 8`.

**Card audit.** Flag any front that says “shown/the slide/the example” without front media or
inline data, and any multi-blank cloze without labels. These are family-level defects: fix the
pattern, not one card.

### Output

Free-form; a discussion, not a schema. Cover what to drop, merge, split, sharpen or compress, each
with the card's **topic and number**; what to protect and why; coverage gaps. Every recommendation
names a card and states the mechanism so the caller can check it.

**Do not quote card text into the conversation.** To see a card, ask the report:
`roi_report.py cards.json --show 34`. `--show N` prints that card's layer, topic, source, front and
back and exits. Read it there, name it by number, and let the caller open the same command. Then
rebuild and re-run verify and review. **Apply edits to the source of truth** — the emitting script,
or `cards.json` when there is none — never to the `.apkg`, a build artifact whose note ids churn and
lose scheduling history.
