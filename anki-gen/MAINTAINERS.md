# Maintainer notes

Not loaded by `SKILL.md`. Read this before architectural or token-efficiency changes.
Architecture history lives in `maintainers/lessons.md`.

Workflow and documentation architecture: `AGENTS.md`. This file owns the quality contract,
design axioms, rule ownership, and deprecations.

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
| Conditions, units, symbols | `card-writing.md` § symbols | glossary warning / review |
| Near-miss discrimination | `card-writing.md` | review / adversarial review |
| Answer first, then why | `card-writing.md` § answer first | `validate_cards` proxy / review |
| Self-contained front | `card-writing.md` § fronts | `validate_cards` front-image warning / review |
| Media bar | `authoring.md`, `video.md` | `media_index` risk audit + review |
| KCs and fields | `authoring.md` | `validate_cards` KC checks |
| Review rescope | `review.md` | `review_actions.json` build gate |
| Build/import | `pipeline.py`, `validate_apkg.py` | build + real import |
| Cleanup | `SKILL.md` | `smoke.sh` no-litter |

The KC model is scale-free: a KC is a concept, not a card. Single-card KCs are allowed when
the card is a complete high-value decision and the `why` makes the value case. A single-card
`concept`/`mechanism` warns; a 1:1 map warns; exact duplicate claims are errors. The gate does
not force filler cards; the review judges value.

## Change discipline and complexity budget

**Before adding a script, flag or section, walk the ladder: does it need to exist, is it already
here, does the stdlib cover it, can it be one line?** A rule costs a broken deck; a *script* costs
maintenance forever. The 2026-10-17 pass added three scripts and cut one — the cut (extract
condensation) had measured 0.4% on a real corpus before anyone noticed it did nothing. Additions
here are prose, and prose is a bet: three rounds moved no measured number.

Passing tests are a floor, not proof. They show a path is passable, not that it is correct,
complete, or well-maintained. Review the control flow, failure modes, user impact, and
maintainability of every change.

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

`SKILL.md` stays under ~300 lines and ten hard rules. A gate should use the same
`validate_cards` checks; a second validator call is a regression.

## Deprecations

Legacy paths are frozen, not wrapped. Do not add a runtime alias or compatibility shim without a
removal version in this table. Canonical docs never mention a deprecated path.

| Item | Status | Replacement | Removal |
|---|---|---|---|
| `scripts/author.py` | Removed now | `cards.jsonl` + `pipeline.py` | done |
| `scripts/new_cards.py` | Removed now | `cards.jsonl` + gates | done |
| `scripts/parse_intent.py` | Removed now | `pipeline.py` flags | done |
| `scripts/handoff/install.sh` | Removed now | root `install.sh` | done |
| `maintainers/README.md` | Removed now | `AGENTS.md` read order | done |
| `maintainers/cold-audit.md` | Removed now | `AGENTS.md` cold audit section | done |
| `anki-gen/HANDOFF.md` | Removed now | root `README.md` / `INSTALL.md` | done |
| `scripts/handoff/INSTALL.md` | Removed now | root `README.md` copied as `INSTALL.md` | done |
| `scripts/setup_macos.sh` | Compatibility shim | `setup.sh` | keep; review at 2.0 |
| `cards.json` | Read-only legacy | `cards.jsonl` | keep reader |
| `deck` field | Optional legacy | `--deck-name` | keep accepted |
| `scope_gate.md` | Read-only fallback | `intake.md` § Scope | 2.0 |
| `review_actions.md` | Legacy read-only | `review_actions.json` | 2.0 |
| `--no-context` | Hidden no-op | omit it | 2.0 |
| `--deep` | Hidden no-op | omit it | 2.0 |
| `--allow-invalid`, `--status` | Advanced/maintainer | keep | review at 2.0 |
