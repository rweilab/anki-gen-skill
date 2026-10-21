# Card-writing detail

The rule index is the contract; this is the working detail for rules that need more than a line.
Read the part you are about to write against, not the whole thing.

Rule map: 5 symbols · 6 tier-zero · 10 anchors · 11 front/back length · 12 course language ·
13 calibration · 14 retrieval success · 15 cloze · 16 backs explain · 17 provenance ·
18 housekeeping · 19 Procedure · 26 no cross-card pointers · 27 topic/objects.

### Every symbol is defined on its card

If a front or back contains symbols, the back defines each with units — `N` = total atomic
lattice sites, with the required density units named. "Identify all variables" is an exam
objective, so a formula card without the glossary tests half the thing. `validate_cards` warns on
symbol-heavy L1/L2 cards with no glossary, definition verb, or `**Why:**`.

### A tier-zero card comes before the formula cards

One conceptual card before each topic's formulas, answering the question a student has before
meeting any notation. Bad: "What is the equilibrium vacancy concentration formula?" Good: "At the
atomic level, what happens, and what three things control how many empty sites there are?" It must
be answerable without the vocabulary; the back names the factors in plain language before any
equation; mark it `tier_zero: true`.

### Anchor cards for shared vocabulary

A deck is a dependency graph. Five cards querying a term no card defines is a single point of
failure — blank on the definition, all five unreachable. Audit every noun the deck leans on: the
named structures (SC/BCC/FCC/HCP), Miller index vs direction index, course terms (Burgers vector,
interstitial, grain size number), any acronym used twice. Add the anchor before the dependants:
`28 atoms/cell …` → add `27 what are the four common structures, and what distinguishes them?`.
**An anchor answers "what is this and how is it different from its neighbour", not a bare
definition** — contrasting FCC against BCC gives a handle for every later card.

### Match the front to the back's length

A yes/no front ("Is a 1p state possible?") can be answered in one word while its back is a
paragraph, so the paragraph is never read. Demand the mechanism ("Why can there be no 1p state?")
or cut the back. Nothing checks this.

### Speak the course's language, not the textbook's

A card must be answerable in the vocabulary and notation the course uses. Three ways to break it,
all of which read sophisticated and land blank:

- **Named things the course never named.** If the source never says "Pauling's formula", don't
  invoke it — it adds a retrieval step the learner never took. Use the course's term (*percent
  ionic character*, *grain size number*). Attribution is fine in a back, never on a front.
- **Notation standing in for prose.** Symbols do no work a sentence wouldn't do better, unless the
  notation *is* the content (Miller indices, quantum-number labels, formula recall). State the
  concept in words — an energy curve's shape is not symbol-bound.
- **Unearned prerequisites.** Don't put a value, name or prior concept on a front the learner may
  not have — "why does the formula give MgO three-quarters ionic?" quietly needs electronegativity
  differences. If values are printed on the question, say so in the back.

Check every front: could a student who attended every lecture answer it, using only the
lecturer's terms?

### Retrieval success is the currency — report on it

Per the **bifurcation model** (Kornell & Bjork), a retrieved memory strengthens and a non-retrieved
one gains nothing beyond a re-read. Feedback makes testing known material safe, but **a deck's
value is not its size — it is the fraction of cards you actually fail.** Cards you ace are
maintenance cost paid forever. Two habits destroy that signal: **testing what you already know**
(learners self-test the easiest items and restudy the hardest — backwards; Tullis et al. 2018),
and **assuming coverage is coverage** (a 60-card deck you fail 5 of is worth less than a 30-card
deck you fail 12 of). On handover, say where to spend: which topics are anchors you own, which
cards are worth burning time on.

### Use cloze for enumerations, not prose

Cloze is right for exactly one thing: an enumeration whose items are *separately examinable* but
benefit from *shared context*. Splitting into Basic cards gets scheduling but loses context; cloze
gets both. Do not use it for prose (nothing to delete), concept cards, or a single formula whose
whole answer is the deletion.

**Three constraints that bite:**

1. **No math inside a deletion — above all no braces.** Anki's cloze parser ends a deletion at the
   **first** `}}`, so `{{c4::$a = \frac{4R}{\sqrt{3}} \approx 2.31R$}}` closes at the `}}` inside
   `\sqrt{3}}` and leaks the rest onto the front. Not a regex detail — Anki's real parse, and
   **unrecoverable by brace-depth counting**. Delete a word, never an expression: `edge length a =
   {{c1::2R}}`. Unicode `√`, `≈`, `·` render fine and carry no braces: `a = {{c1::4R/√3}}`. If
   the answer is a braced symbol (`{hkl}`), show the symbol and blank the words, or move it to the
   back. `check_cloze_braces()` rejects it at build time.
2. **Delete the answer, not the question.** Removing the *term* and leaving its description tests
   recognition; you want production. Show the symbol only when it cannot legally sit in a deletion,
   and say so in the back.
3. **Every blank must state its expected answer.** `edge length [...]` is unanswerable — with what,
   in what form? Write `{{c4::4R/√3 ≈ 2.31R}}`, or name the form (*edge length a, in terms of R*).
   Apply to units, precision, and which quantity is meant.

**Constraint 3 holds for every free front, not just cloze blanks** — it is about the *retrieval
target*. A compound front is fine, but every clause must state what kind of answer it wants.
**Comparison/ranking fronts must embed the decision data** (a table, raw digits, or `$math$`) so
the learner can decide without a lookup; `validate_cards` warns when one has none (some are
legitimate pure recall). The builder routes on `card["cloze"]` and validates deletion count and
brace balance.

**The build goes through Anki's own library.** `genanki` writes `cards.type = 0` where Anki needs
the 1-based cloze ordinal, so its cloze decks show `{{c1::4}}` literally; patching the database to
`ord + 1` makes Anki 26 refuse the package (`DbError InvalidColumnType(6, "type", Integer)` —
verified by isolation: re-zipping alone imports, a no-op SQL write imports, only the `type` write
fails). So `build_native.py` has Anki create the notetypes and notes and zips the collection Anki
wrote. **Do not reintroduce genanki.** `validate_apkg.py` runs a **real import** first — the only
proof a deck opens is that something opened it.

### Write for the version of you who has forgotten

Every failed review re-reads the card cold, so the reader is a future you who lost the context
months ago and must re-enter in one pass. Optimise for *re-comprehension*, not elegance. The test:
one re-read, and you know what is asked without re-parsing. One idea per card — not one *atom*;
facts that always travel together stay together. Cut ornament, not mechanism: the "why" and the
trap are load-bearing; the second worked example and the restatement are not. **Expertise reversal
from the writer's side:** the reader is always a novice, because they have forgotten.

### No cross-card pointers

A back must never defer to a sibling. "See the magnitude check card" and "as shown above" fail
because **each card is reviewed alone, in random order, with no knowledge of what else is in the
deck** — the pointer resolves to nothing on the one screen where it was needed, and the card it
points at may itself have been cut. This is distinct from a *stale* cross-reference (a pointer to
a card merged away, which the deblater catches); this one is structural. **Write the information
instead.** A fact on two cards costs seconds of review; a fact on one card that defers to a
sibling costs a blank and a wasted rep. Required duplication is correct here (glossaries repeat); a
pointer is the same mistake inverted. It is a rule because the reference is easy to write, feels
economical, and fails silently — a run quoting "see the magnitude check card" produced a card
unanswerable for the one topic where it mattered most, and nothing flagged it.

### Backs explain, they do not just display

A back that restates the front tests recall of a string. It must add at least one of: **why it
works** (the mechanism, plain language); **an intuition or analogy** ("like a balloon: same mass,
more volume, less dense"); **the variable glossary** (rule 5); **a boundary** (when it breaks, the
common error). Prefer sentences over fragments. If a student who skipped the lecture could not
follow the back, it is too thin.

### The recallability test — no front may demand a computed answer

**Before writing any card: could a student answer this honestly from memory after one careful
reading?** If the answer needs a multi-step calculation, the card is invalid — the most common way
a STEM deck goes wrong, and it fails *quietly* (reasonable, well-formatted, correct, useless). The
tell: the front supplies given data **and** asks for a value **out**. Inputs belong on fronts;
outputs-of-your-calculation do not.

```
BAD   Copper at 1000 °C: ρ = 8.4 g/cm³, A = 63.5 g/mol, Q_v = 0.90 eV.
      What are the correct values of N and N_v?        -> work it out, not recall.
BAD   33 g Cu and 47 g Zn. What are the atom percents?  -> the only way is algebra.
GOOD  Why does copper's atom percent come out above its weight percent in a Cu–Zn
      alloy, and which way does that run for zinc?      -> recallable; numbers in the back.
```

**The automated check is a backstop, not a substitute.** `validate_cards.py` catches the explicit
"given data, value out" shape and is **blind** to demands phrased without given data ("what percent
ionic character do MgO and CH₄ have?" still needs the Pauling formula). A broader rule was tried
and reverted — it fired on recallable table cards ("what are the APF values for SC, BCC, FCC and
HCP?"). **So a clean run does not mean every card is answerable**; per-card review is required.

**Front the *concept, method, relationship, direction of an effect, or common error*; put worked
numbers in the back as a worked example, not "the answer you must produce".** Legitimately
recallable numbers — fixed constants, table values (atoms per cell, coordination numbers, APF,
Boltzmann constant), course reference values — are fine. The problem is never *having* a number;
it is *producing* one. Don't put an artifact the learner isn't looking at on the front ("the slides
state…"); state the data and cite the source in the footer. Don't phrase a question so it only
makes sense as a computation — ask about the *structure* of the answer.

**Reject → rewrite** — the writer and verifier both work from this, its only copy:

- ❌ "Solve ∫x²dx" → ✅ "What is the power rule for integration?"
- ❌ "Calculate the Jacobian of..." → ✅ "What does the Jacobian determinant represent?"
- ❌ "Prove that..." → ✅ "Why does the Jacobian determinant give volume scaling?"
- ❌ "Calculate the eigenvalue of..." → ✅ "When is a matrix diagonalizable?"
- ❌ Multi-step computation on the front → ✅ "What are the steps of Gaussian elimination?"
  (Procedure layer, rule 19)

Cards test **understanding, recognition, boundaries** — never mechanical computation.

### Every card carries a provenance footer

Every card cites its source with a locator — a repeatedly-failing card must say where to read
around it, and "the lecture" lets the learner find nothing. It goes in `source`; the builder
renders it as a quiet footer. `validate_cards.py` **errors** when it is missing, and warns when it
has no page, slide, question or chapter.

```
Ch 4 · Lec 10 Q7
Ch 3 · Lec 08 Q2–3 / HW 1 Q3
Ch 2 · Lec 04 Q11 / slide 95
```

- **Only cite what the learner can open.** "The slides state…" points at a deck they are not
  looking at while reviewing. Cite the *problem*, not the artifact: put the numbers on the front so
  the card stands alone, cite the lecture and chapter underneath.
- **Never invent URLs.** No fabricated YouTube links with confident timestamps — if you have not
  opened it, do not cite it. Omit rather than guess.

### Housekeeping lives in fields, not in visible card text

Put the topic and tier in `topic` / `layer` / `tier_zero`. The note type already displays the topic
and its object tags above the question. Prefixing fronts with `**Vacancies.**` makes a card read
like a form.

### The topic is a chapter name, and object tags are a sniper

**`topic` is the table-of-contents heading, not a card's subtopic.** `Unit Cells`,
`Dislocations`, `XRD & Diffraction`, `Vacancies` — good. Three failures: **a layer code**
(`topic: "L2"` is both the label printed on every card and a deck tag, so "L2" returns every
understanding card and says nothing about the subject); **a section, not a chapter** (`Chapter 4
defects`, `Unit 2`); **a single card or subtopic wearing a topic's name** (`The T=-(u+v)/3
identity`, `Radians`, `Sine`, `Tangent` inside a Unit Circle deck). If several cards come from the
same lecture or chapter, they share the same topic. A topic with 1–2 cards is usually a subtopic;
merge it into the parent unless it is a real chapter. Roughly **4–15 cards per topic** is healthy;
small decks may legitimately be one topic.

**`objects` are optional.** A topic tag is broad by construction — searching `Vacancies` returns
the count, the energy, the concentration, the formula (a shotgun). Apply an object tag only when
the card is **specifically about that thing** and the thing recurs across several cards: a card
about vacancy *concentration* in copper is `#vacancy_concentration` and `#cu`, not `#vacancies`.
**0 to 2** per card; **zero is normal**. A third is a paraphrase of the front. Do not tag
subtopics or single-card identities: in a Unit Circle deck, `radians`, `sine`, and `tangent` are
usually subtopics, not object tags. Pick the objects the card is *about*, not the ones it mentions,
and **a tag should appear on more than one card** — a one-off names nothing searchable.
`validate_cards.py` reports the census and warns when most are singletons. What an object is: a material (`cu`, `ni`,
`na_cl`), a structure (`fcc`, `bcc`, `hcp`), a named phenomenon or defect (`screw_dislocation`), a
named relation (`bragg_law`, `apf`). Prefer the course's name; two or three words, not a clause.
Tags land flat, no namespace; topics keep capitalisation, objects are lowercased. The layer code is
**not** a tag — it stays a field for `triage.py`/`roi_report.py`. Object tags are also how "related
notes" works: rule 26 forbids a back pointing at another card, and a tag query — *every card about
FCC* — is the precise, never-stale version.

### The Procedure layer tests *decisions*, never solutions

Rule 8 stands. The Procedure layer is the specification of what a procedural card *may* ask — the
retrieval target is always a **decision**, never a worked result. Two shapes, no others:

**Shape A — method selection.**
```
Front: [problem statement, display LaTeX]
       **Which method applies here, and what condition selects it?**
Back:  the method, named, plus the criterion that identifies it.
```

**Shape B — next-step prediction.**
```
Front: [problem statement, display LaTeX]
       [the state reached so far, display LaTeX]
       **What are the next steps?**
Back:  the next bounded step only — never the remainder of the solution.
```

**The front must state its demand.** A problem plus a halfway state is ambiguous about whether to
finish, name the next step, or name the method; without the explicit question the retrieval target
is a guess, and a guessed target is graded wrong for the wrong reason.

**Guardrails — all five:** (1) one decision per back — three sub-decisions is three cards; (2)
bounded fronts — the learner reaches the decision from the state shown, not by working the
intervening algebra; (3) a `procedural` tag, so procedural load can be filtered independently
(`tag:procedural`), not a subdeck (rule 23); (4) density cap — a handful per topic, at recurring
decision points, not one per problem; (5) the "practice problem in disguise" test — a complete
worked solution on the back is a problem-set item wearing a card's clothes, send it to practice.
`validate_cards.py` warns on a Procedure front with no `?` — the mechanical proxy for "states its
demand"; a warning because a demand can be stated without one, but look at that shape first.

**Why this exists.** Recognising which method applies, and what the next move is, is high-yield for
STEM; a card that merely relocates a problem set into Anki adds review burden without retrieval
value. The guardrails *are* the design: a 20-step derivation with one answer is not a hard card, it
is an unusable one. **Recorded so it is not resurrected:** the "Procedure Cloze" shape (`Step
{{c1::1}}: ...`) tests sequence recognition, not decision-making — use A or B. (A "Type-in" notetype
never existed in the build.)

---

## Calibrate before you write a single card

**Rule 5 (define every symbol) and rule 16 (backs explain) are novice-tuned.** For someone who
sat through the lectures the same support becomes *redundant processing* — the **expertise
reversal effect** (Kalyuga et al. 2003): guidance essential to a novice can hurt an expert.
Establish this first, because it changes how much a back carries:

| Learner | Back should | Glossing | Worked examples | Boundary (L3) framed as |
|---|---|---|---|---|
| Cold, or re-entering after a gap | full mechanism, every symbol defined, an analogy | always | more than one | **the failure** — what breaks, what it costs |
| Attended the lectures, cramming | the distinction and the trap; assume the vocabulary | only for symbols the course flags | one, at most | **a decision** — which move, which condition, which way the result moves |
| Already strong, narrow weakness | the boundary or the exception | never | none | **the boundary** — where the limit lies |

**The last column is a preference, not a formality** (rule 7). "Spot the error in this finished
answer" and "which move do you make here" are both legal L3s and *not the same card*: a learner
who rejects a diagnosis-shaped L3 reads it as a trap, not a decision. Reframe the front around
the decision, keep the trap in the back. A 5 with "I'd rather have a procedural question" is the
learner picking a column, not rejecting the topic.

**Over-scaffolded deck signal:** the learner says it *deviates from what they need*, or a front
"doesn't make sense" — expertise reversal as disengagement, not a phrasing bug. Reach for less
scaffolding before simpler wording.

**Calibration governs BACKS only. Fronts are never calibrated down.** A front must be answerable
**instantly, from memory, by the person this deck is for**:

- **Name the concrete things.** A metaphor the source never named ("why does the chain matter?")
  is unretrievable for novice and expert alike — say which chain.
- **Never ask for an abstraction from nothing.** A front may ask the learner to *use* a concept,
  or distinguish things named on the front — not invent the framing first.
- **Terseness is not the goal.** Aim for no unresolvable reference, not a short front.

Same test as rule 12: could a student who attended every lecture answer it, using only the
lecturer's terms? If a *front* fails that, no back calibration saves it.
