# Optional references

## Card patterns for programming languages

Only the categorizations, not per-language lists. In rough order of yield: **distinctions** —
near-identical constructs with different behaviour (blocking vs non-blocking assignment; `*` vs
`.*`; pass-by-value vs reference) — the highest-yield coding category; **behaviour prediction** —
"what does this snippet print/return?" tests execution semantics, not recognition; **look-up
avoidance** — argument order and return values you actually keep searching for (the value-case
test applied to a library); **error diagnosis** — "why did this fail?", tied to the language's failure modes;
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
memorising at all** — promoted to the value-case rule. **Contrastive design** — deliberately juxtaposing
confusables (the reciprocal pair, wt% beside at%) is a feature; the deblater treats interference as
a defect, but the confusion is the test. **Desirable difficulty is unbounded** — nothing checks
whether a front gives away its own answer. **Practice cards with a full worked solution** —
considered and declined: the Procedure guardrail rejects "a problem-set item wearing a card's
clothes"; a full solution is not a retrieval target.

---

## Media

Media policy, extraction, ranking, build flags, and caps are owned by `references/authoring.md`;
video frames are owned by `references/video.md`. This file keeps programming patterns, known gaps,
and the deck audit.

---

## DECK AUDIT

Optional; run only if the request asks, never offer it in the survey. No script — the search and audit are
yours. (An earlier `deck_audit.py` never scored anything and shelled out to a missing binary; the
wrapper was removed, the judgement kept.)

1. Search AnkiWeb, GitHub and Reddit for decks matching the course name/context.
2. Judge the top 3–5 against *this* skill's principles — the audit rubric, so nothing repeats them:
   atomicity (one retrieval decision, answer-first, back explains) 30%; layer coverage and
   tier-zero 25%; no computation prompts 25%; provenance 10%; formatting 10%.
3. Report the scores, recommend the best, and say plainly if none is worth having — "generate your
   own" is a legitimate verdict.
4. If the user accepts one, download it and set it as the merge target.
