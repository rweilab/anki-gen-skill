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

## Design axioms

These are the decisions behind the skill, not a general manifesto. Read them before changing a
stage, reference, script, gate, or command.

1. **Harness > model.** Reliability comes from context assembly, tools, state, verification, and
   review, not from a better prompt.
2. **Deterministic scaffolding around probabilistic work.** Routing, validation, retries,
   permissions, and state transitions are code. The model does judgment.
3. **One canonical path.** No parallel authoring or diagnosis path. A diagnosis script runs only
   when the main command names the failure.
4. **Context is a cache, not a database.** Write state to `$WORK`; read once; read only the current
   step's reference. More systems and more context eventually mean less alignment.
5. **One source of truth per concern.** Schema, quality rules, media policy, and review each have
   one owner. Duplicate prose is a bug.
6. **Independent verification beats same-context self-critique.** Gates, a fresh-context
   adversarial reviewer, and the human review are the quality stack.
7. **Small batches, one rewrite.** A global formatting or review change rewrites the file once,
   never one card or one symbol at a time.
8. **Tests are a floor, not proof.** Passing tests only show that expected paths do not
   syntactically fail; they do not prove card quality, heuristic adherence, or alignment. The real
   import and the human review are the evidence.
9. **Security and agency boundaries live outside the model.** No child `opencode` processes, no
   live collection DB, no ad hoc scripts, no unrestricted tools.
10. **No new system without removing one.** A new artifact, command, flag, stage, or reference
    must replace something or be justified by a measured failure.
11. **Scale-free rules, no magic numbers.** Derive budgets and thresholds from scope or from the
    model's own plan; do not hardcode card, KC, or tool-call quotas.
12. **Protect the 98% quality floor.** Optimize tokens, calls, and speed only after correctness,
    answerability, sourcing, and learner fit.
13. **Alignment has a budget.** Every added branch, artifact, reference, or gate competes with the
    contract for attention. Past a point, more context makes the model less likely to follow the
    path. Prefer deleting, merging, or replacing over adding.

### Decision ladder

Before adding anything, walk this order:

1. Does it need to exist?
2. Is it already here in another form?
3. Does the standard library or an existing helper cover it?
4. Can it be one line or one command?
5. If it must be runtime, what does it replace?
6. Does it add a fixed quota? Make it structural and scale-free instead.
7. Does it move a quality check earlier (a gate) rather than later (prose)?

### Do not resurrect

These were removed or rejected because they added surface without reliability:

- the 16-stage table and persona branching
- five authoring paths; `cards.jsonl` is the one
- the per-card `authoring_ledger.md`
- the hard "2+ cards per KC" rule and the anchor exception
- default `NOT CERTIFIED` plus warning-chasing
- diagnosis commands in the runbook
- literal `<br>` in `cards.jsonl` and plaintext `P_0`
- a second adversarial pass after a formatting-only change
- editing the live skill during a deck run

### Research anchors

One line each; follow the link only for a deep dive.

- Agent Harness Engineering survey — the system around the model is the measurable factor.
  https://picrew.github.io/LLM-Harness/main.pdf
- From Model Scaling to System Scaling — context governance, memory hygiene, skill routing.
  https://doi.org/10.48550/arxiv.2605.26112
- Meta Thin Orchestrator — deterministic routing plus isolated specialist workers.
  https://engineering.fb.com/2026/10/19/ml-applications/thin-orchestrator-ai-agent-architecture/
- Claude Code extension model — hooks for guarantees, skills for procedure, subagents for context
  isolation. https://code.claude.com/docs/en/features-overview
- SkillsBench — focused skills help procedural work; harness and context determine whether they
  fire. https://arxiv.org/html/2602.12670
- SWE-Pro — correctness is not efficiency; LLMs rarely find repository-level optimizations.
  https://arxiv.org/html/2606.25530
- DORA AI report — AI raises generation speed and moves the bottleneck to review and stability.
  https://dora.dev/ai/gen-ai-report/
- Agent evaluation reliability — scaffold choice is a major confound; more tasks do not fix it.
  https://arxiv.org/html/2610.00651
- Agentic misalignment — evaluation awareness and strategic behavior are measured risks.
  https://alignment.anthropic.com/2026/agentic-misalignment-summer-2026/
- AI control — treat the agent as untrusted; monitor artifacts and reasoning, keep a human gate.
  https://arxiv.org/html/2604.15384v2
- OWASP AI Agent Security — least privilege, sandboxing, egress control, and approval gates.
  https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html

## Rule ownership

`SKILL.md` carries ten hard rules; the detailed lessons live in `references/card-writing.md`.
This table is the ownership map, not a second rule list.

| Contract | Owner | Code gate / review |
|---|---|---|
| Source-grounded or `derived` | `card-writing.md` § provenance | `validate_cards` source + KC evidence |
| One retrieval decision | `card-writing.md` § recallability | `validate_cards` / review |
| Unambiguous cue, no leak | `card-writing.md` § recallability | `validate_cards` tag leak / review |
| Production, not recognition | `card-writing.md` § recallability | `validate_cards` computation front |
| Conditions, units, symbols | `card-writing.md` § symbols | glossary info / review |
| Near-miss discrimination | `card-writing.md` | review / adversarial review |
| Answer first, then why | `card-writing.md` § answer first | `validate_cards` proxy / review |
| Self-contained front | `card-writing.md` § fronts | `validate_cards` front-image warning / review |
| Media bar | `authoring.md`, `video.md` | `media_index` risk audit + review |
| KCs and fields | `authoring.md` | `validate_cards` KC checks |
| Review rescope | `review.md` | `review_actions.md` build gate |
| Build/import | `pipeline.py`, `validate_apkg.py` | build + real import |
| Cleanup | `SKILL.md` | `smoke.sh` no-litter |

The KC model is scale-free: a KC is a concept, not a card. Single-card KCs are allowed when
the card is a complete high-value decision and the `why` makes the value case. A single-card
`concept`/`mechanism` warns; a 1:1 map warns; exact duplicate claims are errors. The gate does
not force filler cards; the review judges value.

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

## Complexity budget

**Every change starts with one question:** is there an implementation that reduces the overall
complexity of the skill/repo — fewer systems, artifacts, commands, checks, gates, steps, and prose
— instead of adding? If it adds runtime surface, name what it replaces. “Simple code” is not enough;
the goal is a smaller surface a future agent can follow without drifting.


The runtime path is deliberately small. Before adding a runtime artifact, command, or stage:

1. Can an existing artifact or command carry it? Use that.
2. Can it be a reference or a maintainer-only tool instead? Prefer that.
3. If it must be runtime, what does it replace? Additions should delete or strengthen
   something; do not add a parallel diagnosis path.
4. Does it introduce a fixed card, KC, call, or time quota? If yes, make it structural and
   scale-free instead. The model writes its own budget in `intake.md` from scope.
5. Does every quality lesson it carries have an owner: gate, reference, or review?

`SKILL.md` stays under ~280 lines and ten hard rules. A gate should use the same
`validate_cards` checks; a second validator call is a regression.

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
