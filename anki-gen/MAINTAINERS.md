# Maintainer notes

Not loaded by `SKILL.md`. Read this before architectural or token-efficiency
changes. It records what the experimental ALPHA actually showed; it is not a
verdict on every deck size or every compression idea.

## Agent execution boundaries

Do not spawn opencode child processes (including debug/config commands), use
main-model vision, probe for office/desktop converters, run unbounded/hanging
commands, or kill the harness/own process. Stop only a known test child after a timeout. Once a plan
exists, run autonomously to completion; ask only for destructive or missing
inputs. See `AGENTS.md`.

## Deferred: v1.4.2 deck revisions

Do not implement this in v1.4. Notes only:

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
