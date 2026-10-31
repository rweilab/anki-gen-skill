# Review flow

Commands use `$SKILL` for the directory containing `SKILL.md`.

## REVIEW — the local review page

Review happens in a throwaway localhost page, **not in the chat** — the chat version pushed every
card's full text through the conversation, and `y/n/e` could not express the two signals that drive
cutting and splitting (*too hard for me*, *I already know this cold*).

### Quality rubric — one rubric

Use this on the triaged sample plus flagged cards. The adversarial reviewer and the human page
use the same rubric; do not maintain a second checklist.

1. **Source-grounded:** locator supports the claim, or `derived` is genuinely self-contained.
2. **One retrieval decision:** a wrong answer points to one thing to repair. It is not a duplicate
   of another card’s target; a contrastive pair is fine.
3. **Clean, unambiguous cue:** a reader can tell what is asked; no vague or orphaned fragment,
   truncated sentence, repeated page header/footer, broken glyph, or extraction debris.
4. **Production, not recognition:** no final numeric value on the front (basic counting is allowed),
   no self-answer, no yes/no or multiple-choice recognition. Procedure may show data/equation sheet.
5. **Conditions and symbols:** assumptions, units, and every symbol are on the card; a
   standard-looking symbol is undefined unless named with units.
6. **Near-miss discrimination:** the card separates the target from a tempting alternative.
7. **Answer first and related:** the first back sentence answers the front; a vague front or a
   back that answers something else is a hard fail.
8. **MathJax symbols:** sub/superscripts are `$P_{0}$`, `$\rho_{\text{oil}}$`; no bare `P_0`.
9. **Self-contained front and back:** no “shown/this circuit/the slide” without front media; no
   cross-card or cross-context pointer (“the table above”, “the previous result”, “the earlier
   example”).
10. **Media bar:** a full image that illustrates the card; one by default, up to two when both are
    needed; no title/outline/crop/whitespace.

Hard-fail: vague/unanswerable front, back unrelated to front, extraction debris/truncation, computed
final value, unsupported source claim, cross-card/context pointer, whole-formula/prose cloze, or a
Procedure card that is a worked/remaining solution. Flag: missing/unknown `kc`, unresolved `requires`,
absent `evidence_quote`, a card-label KC, generic `why`, or a fragment KC. Card count is not KC
quality.

**Adversarial reviewer:** run whenever a read-only subagent is available; skip only if none
exists. Start after the web review opens. Give it `$WORK/review_packet.md` only,
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

**Per-card adjudication does not scale.** The `pipeline.py --gates-only` call picks the set and
**always** runs; even a small deck gets its flagged cards surfaced. Set `SKILL` to the directory
containing `SKILL.md`.

```bash
python3 "$SKILL/scripts/pipeline.py" --cards $WORK/cards.jsonl \
    --gates-only --out "$WORK"
```

**The set is chosen by axis, not by card** — three questions, cheapest cards that answer each:

| Axis | Question | Which cards |
|---|---|---|
| **Risk** | is anything broken? | one exemplar per *flag pattern*, not per instance: six near-dup pairs are one defect |
| **Format** | does it read right? | one per card kind (layer × cloze), preferring an unflagged card |
| **Breadth** | is the coverage right? | one per topic, preferring its `tier_zero` card — one slot answers both |

**The sample is fixed at 12.** No `--max`/`--per-topic`; a bigger sample is certification, not a
quality setting. Risk and format are never dropped. The default spans all four kinds and most
topics.

**A stratum is a family, so it costs one slot.** The format axis keys on `(layer, cloze, stratum)`;
when one is under-shown, add one card, never the whole stratum.

**A clean review is not proof.** Each card stands for a family, so the sample surfaces defects but
cannot certify absence. `second_round` names the unreviewed topics/strata/patterns. Report what a
round found, not coverage. Certification is an explicit all-card pass without `--plan`; never call
the sample certification.

### Run it

The command binds `127.0.0.1`, prints the URL, and appends answers. **Each card shows why it was
selected** ("flagged: near-duplicate front", "tier-zero"); a stale plan **aborts**. Without
`--plan` it renders every card — the fallback, not the flow.

First generation runs review by default; later changes ask whether to reopen; if declined, say not
manually reviewed/static checks only. Start in the background, hand over one sentence and the URL
**alone**, never print card text. Wait; on "done" read disk, generalise, stop with
`curl -s -X POST <url>/finish`; never `pkill -f`.

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

**Image cards.** Every card with `media` is a media candidate. The media sample is deliberately
small and spread across topics; the rest are listed under `second_round.media_not_shown` as
**unaudited**. The page
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

Rows carry `recall: true|false`; the finish screen lists the `false` cards as recallability
failures (hard rule 4) — rewrite the front to ask about the concept, or cut it. Run it as a second
pass over the same plan when the deck is computation-heavy, or alone when recallability is in doubt.

### Review actions (required after feedback)

After the user reviews, run one `pipeline.py --gates-only` call. It reads `review_feedback.jsonl`
plus `review_recall.jsonl`, reduces each log to its last row per card, and writes
`$WORK/review_actions.json` when feedback exists and regenerates `review_packet.md`. The skeleton
groups score 1 by topic/KC and lists score 5 removals, score 4 diagnoses, recall failures, and the
cards the sample did not cover.

In one pass, apply all card changes in one complete write of `cards.jsonl` and fill
`score1[].action`, `score1[].target`, and any `score4[].decision` from the source of truth; set
`"status": "resolved"`. Every score-1 block must name one of `merge | relevel | replace | keep
anchor` and a non-empty target. `pipeline.py --build` refuses while the file is missing, open,
stale, or incomplete; a score-5 card still present is incomplete. Score 1 is rescope evidence,
never an automatic cut; score 5 is the only removal verdict. Then build; the build runs the gates
once more.

The KC map and cards remain the reasoning record. Read `cards.jsonl` once before the whole-file
rewrite if it is not current; do not re-read it after. Do not re-read the corpus, build script,
full source, or raw log; pull a source page range only if an anchor needs checking.

**Check answer alignment before style.** A card can be factually true and still not answer its
front. If the front asks “which enzyme/law/step,” the back must name it first; explanation follows.

**Chunking:** only when context pressure is real (for example, a build peaking around 150k or one
topic exceeding ~40 cards). One scope gate/deck name, per-topic cards+KC rows, concatenate or
`--merge-existing`, then a deck-wide validate/triage/ROI. The risk is cross-topic anchors and
duplicates.

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
| front unanswerable / ambiguous | unresolvable reference | name the concrete thing (hard rules 3 and 9) |
| blank on a term it assumes | missing prerequisite | anchor / glossary (`card-writing.md` § Anchor cards) |
| paragraph back never read | front too short for its back | demand the mechanism (`card-writing.md` § Match the front to the back's length) |
| two cards keep colliding | interference, not redundancy | contrastive pair |
| answerable on paper, not memory | it is a computation front | rewrite to concept (hard rule 4) |
| know the fact, fail the method | procedural gap | Procedure layer, or practise outside Anki |

**Apply the whole feedback batch in one complete write.** Read `cards.jsonl` once if it is not
already current, then write the complete file once. A per-card comment changes one card inside that
single write; it is not a separate edit. Do not re-read the file after the write; let the gates
check it.

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

1. **Name the family.** Not "card 34 was too hard" but "the four structure cards sharing this frame
   can only be answered by recalling a table"; a cloze comment is about cloze cards.
2. **Restate as rules** — deck-wide ("don't invent labels"), topic-wide ("this topic has no anchor"),
   kind-wide ("Procedure fronts never state their demand"). Write them down to apply.
3. **Apply at the width the feedback has.** A deck-wide rule touches every card; a family rule
   touches that family; a per-card comment touches that card. **Change the content at that width,
   but write the file once.** A shape change — cuts, new anchors/tier-zero, rebalance — is a content
   decision, not a different write mechanism.
4. **Apply to withheld cards.** `second_round` names unshown topics/strata/patterns; same families,
   same rules. Offer a second targeted round only when rules conflict or a withheld topic raises a
   question the first round could not answer.
5. **Re-run gates and build** — a content change means both run again before handoff, as one batch.

**A summary that applied feedback only to reviewed cards has failed** when the rule was deck-wide.

**Removing a rejected card.** Score 5 means remove it from `cards.jsonl`; do not reword it and let it
back. A hash-list tombstone failed because re-scoping changes the hash. Read the log’s **last row per
card** (`cardid.last_row_per_card`); a 5 followed by 3 must still be removed.

**Fallback.** If the server will not start, generate a self-contained HTML file, let the user review
it, and accept one pasted JSON blob. The exception, not the flow.
