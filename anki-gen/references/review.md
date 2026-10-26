# Review flow

Commands use `$SKILL` for the directory containing `SKILL.md`.

## REVIEW — the local review page

Review happens in a throwaway localhost page, **not in the chat** — the chat version pushed every
card's full text through the conversation, and `y/n/e` could not express the two signals that drive
cutting and splitting (*too hard for me*, *I already know this cold*).

### Quality rubric — one rubric, three users

Use this on the triaged sample plus flagged cards. The self-audit, the adversarial reviewer, and
the human page use the same rubric; do not maintain a second checklist.

1. **Source-grounded:** locator supports the claim, or `derived` is genuinely self-contained.
2. **One retrieval decision:** a wrong answer points to one thing to repair. It is not a duplicate
   of another card’s target; a contrastive pair is fine.
3. **Clean, unambiguous cue:** a reader can tell what is asked; no vague or orphaned fragment,
   truncated sentence, repeated page header/footer, broken glyph, or extraction debris.
4. **Production, not recognition:** the front does not demand a final numeric value (basic
   counting of visible steps/items is allowed), contain its own answer, or reduce to a yes/no or
   multiple-choice recognition prompt. A Procedure card may show problem data and an equation sheet.
5. **Conditions and symbols:** assumptions, units, and every symbol are on this card. A
   standard-looking symbol is still undefined unless the card names it and its units.
6. **Near-miss discrimination:** the card separates the target from a tempting alternative.
7. **Answer first and related:** the first back sentence answers the front; a vague front or a
   back that answers something else is a hard fail.
8. **MathJax symbols:** sub/superscripts are `$P_{0}$`, `$\rho_{\text{oil}}$`; no bare `P_0`.
9. **Self-contained front and back:** no “shown/this circuit/the slide” without front media; no
   cross-card or cross-context pointer (“the table above”, “the previous result”, “the earlier
   example”).
10. **Media bar:** a full image that illustrates the card; no title/outline/crop/whitespace.

Hard-fail an unanswerable or vague front, a back unrelated to the front, obvious extraction
debris/truncation, a computed final value, an unsupported source claim, a cross-card or
cross-context pointer, a whole-formula/prose cloze, or a Procedure card that is a worked or
remaining solution. Flag a missing/unknown
`kc`, an unresolved `requires`, or a KC whose `evidence_quote` is absent from the packet excerpt.
Flag a KC that is a card label, a generic `why`, or a single card that is a fragment. A card count
is not evidence of KC quality.

**Self-audit:** run the rubric on the sampled cards, one line each. It is not independent review
and does not certify the deck. Fix or park what fails; say what you checked and did not check.

**Adversarial reviewer:** default when a read-only subagent is available; skip only if none exists
or the caller declines. Start after the web review opens. Give it `$WORK/review_packet.md` only,
one line per sampled card: `KEEP|FIX|FAIL | card number | one-line reason`. Use the one rubric for
source, symbols, and media, then apply this decision/overlap pass:

- Reduce each front to the exact answer it demands.
- FAIL when the demand is a final numeric value requiring computation (basic counting of visible
  steps/items is allowed), when the back is a worked or remaining solution, when the front demands
  more than one decision, has no explicit question, or cues its own answer, when the card is yes/no
  or multiple-choice recognition, or when it duplicates another card’s target unless the pair is
  contrastive. Fail the redundant duplicate, not both.
- KEEP a card only when the front is self-contained — the equation, every symbol, and any
  “left side/this equation” are on the card — and the back names the decision with its condition
  or reason. Problem data and an equation sheet are allowed; Procedure cards are expected.
- FIX a valid decision card with a generic “calculate/compute” cue, a missing selecting condition,
  or an undefined symbol/context.

It never rewrites or certifies. If it returns no output or ends on its length limit, treat it as
**not run**. Do not rerun it after a formatting-only change; render one card instead.

**Deck shape.** Does the deck contain the card family the learner asked for? If the target is
method selection and every reviewed card is L1 recall, flag the family.

**Formatting-only changes.** A render or formatting change gets a one-card visual check, not a
full review. Reopen the review or render one card; source inspection is not a visual check.

### Review a chosen subset, not the deck

**Per-card adjudication does not scale.** On the first real run the user stopped after nine cards of
fifty-five — and their edits generalised to the whole deck anyway, so the other forty-six bought
nothing. The `pipeline.py --gates-only` call picks the set and **always** runs, any deck size;
even a small deck gets its flagged cards surfaced. Set `SKILL` to the directory containing
`SKILL.md`.

```bash
python3 "$SKILL/scripts/pipeline.py" --cards $WORK/cards.jsonl \
    --gates-only --out "$WORK"
```

**The set is chosen by axis, not by card** — four questions, cheapest cards that answer each:

| Axis | Question | Which cards |
|---|---|---|
| **Risk** | is anything broken? | one exemplar per *flag pattern*, not per instance: six near-dup pairs are one defect |
| **Format** | does it read right? | one per card kind (layer × cloze), preferring an unflagged card |
| **Breadth** | is the coverage right? | one per topic, preferring its `tier_zero` card — one slot answers both |
| **Depth** | what else is in the topic? | only with `--per-topic N` |

`--max` (default **12**) trims **breadth and depth only**; risk and format are never dropped. The
budget is deliberately hard: the previous "every flagged + every tier-zero + one per topic" spent
25 of a real 61-card deck and still never showed a Procedure card. The default shows 12 (19%)
across all four kinds and 12 of 14 topics.

**Spend the budget on breadth, not depth.** `--per-topic N` buys depth and costs coverage: measured
on an 83-card/19-topic deck, `--per-topic 3 --max 24` showed 24 cards over 16/19 topics;
`--per-topic 1 --max 30` showed 20 over **19/19**. Fewer cards, every domain, every kind and flag —
that is the cross-section. **Raise `--max` before `--per-topic`**; the default 12 is a floor, not a
target.

**A stratum is a family, so it costs one slot.** The format axis keys on `(layer, cloze, stratum)`,
so a card family earns its own exemplar. When one is under-shown, add one card, never the whole
stratum — a run that hand-added seven Shape A/B cards instead of two spent three extra slots to
re-learn what one per shape already generalises.

**A clean review is not proof the deck is sound.** The subset is chosen by axis so each card *stands
for a family* — excellent at surfacing defects, structurally incapable of certifying their absence.
A card that **passes** says nothing about its unshown siblings; `second_round` names the topics,
strata and flag patterns the budget held back, and those are **unreviewed**, not approved. Report a
round as *what it found*, never as coverage. Certification is `--max` set to the whole deck, in
sittings — an explicitly chosen pass, not the default.

### Run it

The command is stage 10. It binds `127.0.0.1` on a free port, prints the URL, and appends each
answer to the feedback log. **Each card shows why it was selected** ("flagged: near-duplicate front:
96% similar to cards 22, 25", "tier-zero") — a reviewer who knows why answers better. The plan is
checked against the deck's hashes on startup; a stale plan **aborts**. Without `--plan` the server
renders every card — the fallback, not the flow.

**Before opening the port:** first generation runs the review by default. When the user is asking
for changes or adjustments, ask whether to reopen it; do not assume. If they decline, say the deck
was not manually reviewed and report static checks only.

**Around it:** start in the background, say one short sentence — what the page is and to come back
when done — then give the URL **alone on its own line** (paste-able whole; the server prints it
bare). The sentence is not padding: it is the only thing that tells someone who has never seen this
what they are about to open and what happens next. **Do not print card text into the chat** — that
is what this replaces. Wait; the user says "done" whenever they stop, so read whatever is on disk.
Then generalise and re-scope, stop the server, verify nothing is listening. Stop it with
`curl -s -X POST <url>/finish`; never `pkill -f`, which can match and kill its own shell.

**The score scale:**

| Score | Label | Meaning | Action |
|---|---|---|---|
| 1 | Easy | retrieved instantly / already known | **calibration evidence**: rescope the topic, merge or re-level trivial variants, shift focus, or keep an anchor; never cut silently |
| 2 | Medium | right level | keep |
| 3 | Hard | struggled, got there | keep — this is where the learning is |
| 4 | Beyond me | what the comment says | the agent decides — no reason dropdown |
| 5 | Reject | should not exist | **drop it from the source of truth** |

**Read clusters, not just cards.** Repeated 1s on similar questions mean the retrieval target is too
easy or duplicated: merge the cluster into a harder L3 contrast/boundary card or drop the trivial
siblings, and spend the budget on the harder adjacent material. Do not add more cards of the kind
already scoring 1. Repeated 5s with “what slide?” or “not shown” mean the front is not
self-contained; fix the front/image, do not lower the difficulty bar.

**Image cards.** Every card with `media` is a media candidate. The sample is a bounded
cross-section — `max(3, min(8, ceil(sqrt(image_cards))))`, spread across topics and never trimmed
by `--max`; the rest are listed under `second_round.media_not_shown` as **unaudited**. The page
serves the image from `/media/`, and a missing file shows a red placeholder. A wrong or irrelevant
figure is a normal score or comment — there is no separate control.

### `--ask recall` — the one check nothing else makes

**The 1–5 scale is the primary review. This is a second pass, never the only review**; run it
after the scale pass, or alone only when recallability is in doubt. Its default log is
`review_recall.jsonl`, so it cannot overwrite the scale scores.

The recallability test is the highest-stakes rule and nothing else enforces it: `validate_cards`
catches the explicit "given data, value out" shape and is blind to the rest. Difficulty and
*recallability* are different axes — a card can be hard and perfectly recallable — so this mode
asks a binary question:

```bash
python3 "$SKILL/scripts/review_server.py" \
    --cards $WORK/cards.jsonl --plan $WORK/review_plan.json --ask recall \
    --out $WORK/review_recall.jsonl
```

> **Could you answer this from memory, without working it out?** — `y` / `n`

Rows carry `recall: true|false`; the finish screen lists the `false` cards as rule-8 failures —
rewrite the front to ask about the concept, or cut it. Run it as a second pass over the same plan
when the deck is computation-heavy, or alone when recallability is in doubt.

### Review actions (required after feedback)

After the user reviews, the next `pipeline.py --gates-only` call reads `review_feedback.jsonl`
plus `review_recall.jsonl`, reduces each log to its last row per card, and writes
`$WORK/review_actions.json` when feedback exists. The skeleton groups score 1 by
topic/KC, lists score 5 removals, score 4 diagnoses, recall failures, and the
cards the sample did not cover.

After feedback, the next gates call writes `review_actions.json` and regenerates the packet. Fill
`score1[].action`, `score1[].target`, and any `score4[].decision` from the source of truth, then set
`"status": "resolved"`. Every score-1 block must name one of `merge | relevel | replace | keep
anchor` and a non-empty target. `pipeline.py --build` refuses while the file is missing, open,
stale, or incomplete; a score-5 card still present is incomplete. Score 1 is rescope evidence, never an
automatic cut; score 5 is the only removal verdict.

The KC map and cards remain the reasoning record. Do not re-read the corpus, build script,
full source, or raw log; pull a source page range only if an anchor needs checking.

**Check answer alignment before style.** A card can be factually true and still not answer its
front. If the front asks “which enzyme/law/step,” the back must name it first; explanation follows.

**Chunking:** only if the build still peaks >150k or a topic >40 cards. One scope gate/deck name,
per-topic cards+KC rows, concatenate or `--merge-existing`, then a deck-wide validate/triage/ROI.
The risk is cross-topic anchors and duplicates.

### How to apply it

- **5 → drop it.** Remove the card from the source of truth — the emitting script, or `cards.jsonl`
  when there is none. That is the whole mechanism.
- **1 → rescope the topic, not just the card.** “Easy” means the learner already knows it; use
  it to rebalance scope and difficulty, merge/re-level trivial variants, or protect an anchor.
  Fill that cluster in `review_actions.json` with one of `merge | relevel | replace | keep anchor`,
  name the target, and report the net delta. Propose changes; never cut silently. A review comment
  is never a mandate to expand: if you add cards, make the addition replace a merged/cut card
  unless the user explicitly asked for more.
- **4 → decide from the comment, do not ask.** "Haven't studied this yet" → leave it; "assumes a
  term I don't have" → add an anchor or glossary; "too many steps bundled" → split. **4 with no
  comment → leave it alone** — most early-semester 4s are material not yet covered.
- **2 and 3 → keep.** Do not "improve" a card rated right.

**A repeatedly-failing card is diagnostic, not just under-repeated.** Diagnose before splitting; do
not reflexively split every hard card:

| Symptom on review | Diagnosis | Fix (rule) |
|---|---|---|
| front unanswerable / ambiguous | unresolvable reference | name the concrete thing (13) |
| blank on a term it assumes | missing prerequisite | anchor / glossary (10, 5) |
| paragraph back never read | front too short for its back | demand the mechanism (11) |
| two cards keep colliding | interference, not redundancy | contrastive pair |
| answerable on paper, not memory | it is a computation front | rewrite to concept (8) |
| know the fact, fail the method | procedural gap | Procedure layer, or practise outside Anki |

**Batch independent edits in one step.** A per-card comment is still a one-line
change, but several comments can be applied in one step with several edit calls;
each separate step re-sends the whole context.

`roi_report.py` prints image coverage per topic, restatement flags, costliest
cards, and anchors. In the handoff, report the
image-card count, any topic with strong visual candidates but no images, and which
images were confirmed versus merely listed.

**The deck-wide note generalises; per-card comments are evidence.** The finish screen has a
free-text "deck-wide rule" box, separate from the per-card comment. One sentence there ("these
fronts lean on labels I invented; use the course's own terms") applies to every card — which is
what makes a 25-card review enough to act on a 72-card deck. Read it as an instruction, apply it
everywhere it fits, and say which cards you changed.

### Generalise, then re-scope — the review set is evidence, not a to-do list

The subset was chosen by axis so each card stands for a *family*. Do the reasoning explicitly in the
chat before touching anything:

1. **Name what each piece of feedback implicates.** Not "card 34 was too hard" but "the four
   structure cards sharing this frame can only be answered by recalling a table" — the axis a card
   was chosen for tells you its family. A comment on one cloze card is a statement about the cloze
   cards.
2. **Restate it as rules about the deck** — deck-wide ("don't invent labels"), topic-wide ("this
   topic has no anchor"), kind-wide ("the Procedure fronts never state their demand"). Write them
   down so the next step has something to apply.
3. **Apply it at the width it actually has.** A deck-wide rule (the note box, or a comment that
   generalises) touches every card it covers; a family rule touches that family; a per-card comment
   or score touches that card only. The old wording said re-scope and regenerate the *whole* set for
   any feedback, which turns one comment into 61 rewrites and is why rounds get abandoned;
   patched-not-regenerated is the failure the other way. **Edit at the width the feedback has.** A
   per-card comment is a one-line edit in `cards.jsonl`; a deck-wide rule touches every card, and
   only then is a full regenerate the honest cost. A regenerate **is** still required when the rules
   change the deck's *shape* — cuts, new anchors or tier-zero cards, re-balancing a topic —
   because those change which cards should exist.
4. **Apply the rules to the withheld cards.** `review_plan.json`'s `second_round` names the topics,
   strata and flag patterns the subset did not show; they belong to the same families, so the same
   rules cover them. Offer a second targeted round *only* when the rules conflict or a withheld
   topic raises a question the first round could not answer.
5. **Re-run the gates and rebuild** — a content change means steps 8 and 13 run again before the
   next build, as one batched call.

**A summary that says "applied the feedback to the reviewed cards" has failed** when the feedback
was deck-wide — the reviewer scored a sample, and the point of a sample is that its lessons apply
widely. But a summary that rewrote all 61 cards in response to one comment has failed the other way:
it spent a full rebuild on a one-line change, which is how review rounds stop happening.

**Removing a rejected card.** Score 5 means the card should not exist, so **remove it from the
source of truth** — the emitting script, or `cards.jsonl`. No second mechanism: a hash list was tried
and removed, because a re-scope *rewrites card text*, so a rejected card re-emitted a word different
carries a new hash and slips the filter — it protected only the case that was never the risk (an
unmodified re-run) while enabling a stale list to drop live notes. **A 5 is a verdict on whether the
card exists, not its wording** — do not reword it and let it back, delete it. Read the log reduced
to its **last row per card** (`cardid.last_row_per_card`): the log is append-per-event, so a card
clicked 5 then left on 3 still carries that 5, and the raw log would drop a card the reviewer kept.

**Fallback.** If the server will not start, generate a self-contained HTML file, let the user review
it, and accept one pasted JSON blob. The exception, not the flow.
