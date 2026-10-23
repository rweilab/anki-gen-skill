# Maintainer notes

Not loaded by `SKILL.md`. Read this before architectural or token-efficiency
changes. It records what the experimental ALPHA actually showed; it is not a
verdict on every deck size or every compression idea.

## Maintainer docs

Maintainer-only references live under `maintainers/`, never `references/`. `references/` is for the
deck run; `maintainers/` is for changes to the skill.

- `maintainers/README.md` — one-line index of the files below.
- `maintainers/lessons.md` — regression lessons; read before changing a script.
- `maintainers/dossier-format.md` — dossier schema, files, snapshots, archive rules; read before
  changing dossier storage.

## Quality contract

The skill exists to take the resources available in the caller's directory — or resources it can
find — and build cards this specific learner can actually use. The quality floor is **98%**. That
is a quality floor, not a confidence claim; high confidence and a deck that needs few or no
corrections are outcomes of meeting it.

Priority order:

1. correctness, answerability, sourcing, and learner fit
2. reliability, portability, and resourcefulness
3. token and API-call efficiency
4. speed

Never buy a lower priority by sacrificing a higher one. Do not remove source context, learner
context, provenance, why-explanations, or hard-earned heuristics merely to save calls, tokens, or
time. Compaction is allowed after the evidence and reasoning have done their job.

Heuristics are adaptable guidelines, not a rigid checklist. Preserve the *why*, the precise
vocabulary, and the distinctions that took real failures to learn. Why-questions are part of the
product: they explain card decisions to the caller and make the heuristics transferable to new
material.

The skill must work in any supported directory and environment, discover usable sources, state
its assumptions, and individualize the deck. Minimal API calls, low token usage, and fast runs
are goals only within that quality contract.

## Rule ownership

One owner per rule. `SKILL.md` keeps the one-line contract; the owner reference carries the
explanation; the code gate is the check that can fail. “Prose” means the owner text plus review is
the enforcement. Duplicates are point-of-use guards, not second definitions.

Owner references are under `references/` unless the cell names `SKILL.md`, `AGENTS.md`, `scripts/`,
or a `maintainers/` path.

| Rule/behavior | SKILL contract | Owner reference | Code gate | Duplicates |
|---|---|---|---|---|
| Quality kernel | SKILL top | `card-writing.md`, `authoring.md` (media) | `validate_cards`; pipeline `quality` (report) | stage 7/11; short prompt guards |
| 1 Import vs syntax | Rule 1 | `card-writing.md` build note | `validate_apkg.py` import test | stage 12 |
| 2 MathJax delimiters | Rule 2 | `rendering.md` | `render.py`; `validate_cards` stray-`$` | — |
| 3 No markdown | Rule 3 | `rendering.md` | `render.py` | — |
| 4 Raw strings | Rule 4 | `rendering.md`, `authoring.md` | `validate_cards` control-char | authoring mechanics |
| 5 Every symbol | Rule 5 | `card-writing.md` § symbols | `validate_cards` glossary info | WRITER/VERIFIER prompts |
| 6 Tier-zero | Rule 6 | `card-writing.md` § tier-zero | `tier_zero` field/build order (signal) | WRITER prompt |
| 7 Forbidden patterns fronts | Rule 7 | `card-writing.md` § recallability | `validate_cards.is_computation_prompt` | WRITER prompt; calibration |
| 8 No computed front | Rule 8 | `card-writing.md` § recallability | same; review `--ask recall` | WRITER/VERIFIER prompts |
| 9 No machine split | Rule 9 | `authoring.md` mechanics | prose | VERIFIER prompt |
| 10 Anchors | Rule 10 | `card-writing.md` § anchors | `roi_report.py` anchors (signal) | WRITER prompt |
| 11 Answer first | Rule 11 | `card-writing.md` § answer first | `validate_cards` answer-alignment (enzyme proxy) | WRITER prompt; review checklist |
| 12 Course language | Rule 12 | `card-writing.md` § course language | prose | WRITER prompt |
| 13 Calibration | Rule 13 | `card-writing.md` § calibration | prose | WRITER prompt; review |
| 14 Retrieval success | Rule 14 | `card-writing.md` § retrieval success | `roi_report.py` costliest (signal); review | stage 13 |
| 15 Cloze enumerations | Rule 15 | `card-writing.md` § cloze | `build_native.check_cloze_braces` | WRITER prompt |
| 16 Backs explain | Rule 16 | `card-writing.md` § backs | prose | kernel; WRITER/DEBLOATER |
| 17 Provenance | Rule 17 | `card-writing.md` § provenance | `validate_cards` source checks | WRITER prompt; `schema.md` |
| 18 Housekeeping fields | Rule 18 | `card-writing.md` § housekeeping | prose | WRITER prompt |
| 19 Procedure | Rule 19 | `card-writing.md` § Procedure | `validate_cards` Procedure-front-warn | WRITER prompt |
| 20 Reflow | Rule 20 | `authoring.md`, `rendering.md` | `render.py` | — |
| 21 Cardability/scope | Rule 21; stage 6 | `card-writing.md` scope budget | stage 6 artifact | CLASSIFIER prompt |
| 22 Debloat | Rule 22 | `prompts.md` DEBLOATER | `roi_report.py` (signal) | review score semantics |
| 23 One deck, named | Rule 23 | `survey.md` deck naming; `card-writing.md` § topic | prose | stage 2 |
| 24 Full front/back | Rule 24 | `review.md` | `review_server.py` | — |
| 25 No katex | Rule 25 | `rendering.md` | prose | — |
| 26 No cross-card pointers | Rule 26 | `card-writing.md` § no cross-card pointers | prose | WRITER/DEBLOATER |
| 27 Topic/objects | Rule 27 | `card-writing.md` § topic/objects | `validate_cards` topic-is-layer-code/objects-count/tag-leak | CLASSIFIER/WRITER prompts |
| Media | kernel; stage 7 | `authoring.md`; `video.md` | `frames.py`, `media_index.py`, pipeline media risk | kernel; stage 7; video |
| Review | stage 10 | `review.md` | `triage.py`, `review_server.py`, pipeline review status | stage 10 |
| Revision | Revising an imported deck | `revision.md` | `revision.py`, `anki_connect.py` | — |
| Cleanup | stage 14 | `SKILL.md` stage 14; `AGENTS.md` no-litter | `smoke.sh` no-litter | `output.md` retired |
| Gates | stage map | `scripts/` | `validate_cards`, `validate_apkg`, `roi_report`, `pipeline.py` | stage map |

## Change discipline

**Before adding a script, flag or section, walk the ladder: does it need to exist, is it already
here, does the stdlib cover it, can it be one line?** A rule costs a broken deck; a *script* costs
maintenance forever. The 2026-10-17 pass added three scripts and cut one — the cut (extract
condensation) had measured 0.4% on a real corpus before anyone noticed it did nothing. Additions
here are prose, and prose is a bet: three rounds moved no measured number.

Passing tests are a floor, not proof. They show a path is passable, not that it is correct,
complete, or well-maintained. Review the control flow, failure modes, user impact, and
maintainability of every change.

## Agent execution boundaries

Do not spawn opencode child processes (including debug/config commands), use
main-model vision, probe for office/desktop converters, run unbounded/hanging
commands, or kill the harness/own process. Stop only a known test child after a timeout. Once a plan
exists, run autonomously to completion; ask only for destructive or missing
inputs. See `AGENTS.md`.

## v1.5 implementation map

Start here before reading the revision code:

| Need | Read |
|---|---|
| CLI flags and output | `scripts/revision.py` |
| One revision verb | `scripts/revision_ops/<verb>.py` |
| Snapshot, sizes, delete, prune | `scripts/revision_ops/snapshot.py` |
| Shared note/schedule/conflict helpers | `scripts/revision_ops/common.py` |
| Atomic storage and locks | `scripts/dossier/store.py` |
| Record and manifest format | `scripts/dossier/model.py`, `manifest.py` |
| Behavior index | `tests/revision_hardening.py`, `tests/README.md` |

Data flow: `attach` writes state, `plan` writes a plan, `apply` writes snapshot +
affected backup + apply log, and `revert` reads the backup + apply log. Old state
is never duplicated in `snapshot.json`.

## Deferred: v1.5 deck revisions

**v1.5 status:** implemented in `scripts/dossier/`, `scripts/revision_ops/`,
`scripts/deck_context.py`, `scripts/revision.py`, and `scripts/anki_connect.py`. The notes
below remain the rationale and the boundaries.

Do not implement this in v1.4.x. Notes only:

- An `.apkg` import merges by note GUID; it does not replace the collection.
  Existing notes can update while keeping scheduling/history; new notes are
  added; notes absent from the package are not deleted. `.colpkg` replaces the
  whole collection and is not the revision mechanism.
- Current note IDs are `md5(front|back)` (`cardid.py`). A stable explicit `hash`
  is required before editing existing notes, or Anki sees a new note.
- The future revision path needs: GUID extraction/migration, revision reports
  (`added`/`updated`/`unchanged`/`retired`), note-type compatibility checks, and
  optional AnkiConnect cleanup. `--merge-existing` is add-only and must not be
  presented as an update path.

## Changelog discipline

Every behavior, script, schema, reference, or packaging change gets an entry
under the section matching `VERSION`. Do not bump `VERSION` unless the user
explicitly asks. `scripts/smoke.sh` runs `scripts/changelog_check.py`, which fails
if `VERSION` and the latest changelog section disagree or the section is empty.
See `AGENTS.md`.

## What the experimental skill tried to do

Location: `~/.claude/skills/anki-experimental/` (archived ALPHA). Read this
summary instead of loading the whole experimental skill.

**Goal:** keep per-card reasoning and heuristics while cutting total processed
tokens, unique input, and peak context. The thesis was that a long chat
re-sends its whole history on every step; small, fresh batch contexts should
avoid that.

**Intended control flow:**

```text
ingest.py  -> chunks.jsonl + FTS5 source index + toc/meta
           -> facts.jsonl (compact source map, one row per fact)
           -> packet.py per 8–12-card topic
                (rules + stage card + scope + facts + source excerpts + deck state)
           -> ledger.md + cards.jsonl
           -> author.py validation -> state.py
           -> review.py (1–5 only) -> audit.py (static full-deck page)
           -> build.py (Anki-native, optional media) -> cleanup
```

**Components:**

- `ingest.py` — text/PDF ingest, FTS5 chunks, optional figure extraction and
  one-image vision for near-empty pages.
- `page.py` — token-light source pager; returns only the chunks for a query.
- `packet.py` — the control-flow leash: one compact batch packet containing the
  rules, stage card, scope, facts, excerpts, and deck state.
- `facts.py`, `state.py` — compact fact table and deck state.
- `author.py` — schema/media/ledger validation.
- `review.py` — localhost 1–5 review with hash-keyed feedback.
- `audit.py` — static whole-deck dashboard with filters, flags, images, ledger,
  and export.
- `build.py` — Anki-native Basic/Cloze build with import check and optional
  media bundling.
- `figures.py` / `vision.py` — opt-in figure list/description and one-image
  Gemini transcription outside the main context.

**What was different from base:** base favors one emitting script, a full
corpus/deck context, and a broad validator. Experimental favored many small
contexts, a compressed fact table, packet-per-batch rules, and a human audit
page.

**What the DSA run actually did:** one session, one 23.8 KB packet, nine topic
ledgers, cards written through bash/Python snippets, and a broader topic scope.
That is not the fresh-context-per-batch flow above, so the architecture was not
cleanly tested.

## Experimental ALPHA postmortem

Source: `SCHOOL-DSA-Base.apkg` and `SCHOOL-DSA-Experimental.apkg` in
`~/syncthing/RAM/old_syncthing/coding/DSA`, sessions
`ses_ea69c33f2ffeXcJTXvWN3AbwFx` and `ses_ea6a2c0a2ffeN272yyrcUZtrB0`.

| Observation | Evidence |
|---|---|
| Total processing and cost were effectively tied. | Base 234,855 input / 3.62M cache / $0.0703; experimental 226,588 / 3.97M / $0.0692. Total tokens 275k vs 265k; cost −1.6%. |
| The experimental peak was lower, but it used more steps and cache. | Peak 121k vs 89k; messages 48 vs 75; bash 47 vs 60; cache +9.5%. |
| One emitting script was efficient at this deck size. | Base 2 writes (48.8k script + 7k ledger); experimental 9 topic ledgers + 60 bash calls. |
| Compression correlated with less why/source. | Base 107 `Why:` and 106 source footers; experimental 0 `Why:` and 90 sources. |
| Reasoning fell while output rose. | Base 20,386 reasoning / 19,970 output; experimental 14,052 / 24,736. |
| The quality comparison was confounded by scope. | Base leaned complexity/arrays/lists/stacks; experimental added trees, BSTs, hash tables, postfix. |
| The stateless thesis was not cleanly tested. | Experimental ran one session, read one 23.8k packet, and wrote cards through bash/Python snippets rather than fresh batch contexts. |
| Peak context alone is not a success metric. | Lower peak coexisted with higher cache and more steps. |
| Validator breadth is cheap quality. | Base `validate_cards` ~22.6 KB vs experimental `author` ~5.6 KB; experimental missed why/coverage checks. |
| Projected savings were not evidence. | The 80% projection did not appear; the measured total was 3.6% lower at 1.6% lower cost. |
| New subsystems did not help this deck. | Media/vision/audit were unused or weaker than the base equivalents for DSA. |
| Salvage value is separate from architecture value. | The static audit UI and OS/install matrix are token-neutral; the authoring pipeline was not better. |

## What this does and does not say

It does **not** prove compression is always bad. It shows that at ~120 cards,
with this execution, compression shifted cost into more steps and cache while
reducing why/source. The 99-card/17M-cache case is a different regime; the
threshold is still unmeasured.

It does suggest that **step count, why/source preservation, and validator
breadth** belong in the success metric alongside total tokens and cost.

## If this is retried

Use a controlled A/B: same source, same topic list, same target card count, same
model/settings. Run fresh contexts per 8–12-card batch, write `cards.jsonl`
directly, and compare total tokens, cache, messages, cost, why/source coverage,
validator findings, reasoning/card, and blind quality. Do not compare decks with
different scope.

## Possible salvage

- Static whole-deck audit page (filters, validator flags, duplicates, images,
  ledger, flag export) — human QC, no model tokens.
- Cross-platform install/doctor matrix.

Neither salvage item justifies reusing the experimental authoring pipeline.
