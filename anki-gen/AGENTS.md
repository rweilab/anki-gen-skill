# Dev workflow

This file is for maintainers/agents changing the skill; it is not loaded during a
normal deck run. It is the single entry point for maintainer work.

## Read order

1. `MAINTAINERS.md` — § Quality contract, § Design axioms, and § Deprecations before any change.
2. `maintainers/lessons.md` — before changing a script; it owns regression history.
3. `maintainers/dossier-format.md` — before changing dossier or revision storage.
4. `references/` — only for a deck run, not for maintainer context.

If a maintainer doc is not linked here, it is not part of the contract.

## Documentation architecture

Four maintainer docs, one question each. The read order is the router.

| File | Question it answers | Put here |
|---|---|---|
| `AGENTS.md` | How do I work on this repo? | workflow, commands, audit protocol, boundaries, doc map |
| `MAINTAINERS.md` | Why is the design this way, and what must not change? | quality contract, axioms, decision ladder, ownership, deprecations |
| `maintainers/lessons.md` | What failed before? | regressions, postmortems, "do not retry" |
| `maintainers/dossier-format.md` | How is revision storage structured? | schema, layout, snapshots, archive rules |

Rules:

1. No new maintainer doc unless it replaces or merges into one of these four.
2. If a doc is not linked from `AGENTS.md`, it does not exist. Delete it or link it.
3. Duplicate ownership is a bug. Merge or delete; never maintain two copies.
4. Runtime procedures belong in `references/`, not `maintainers/`.
5. Release history belongs in `CHANGELOG.md`.
6. Scratch notes, plans, summaries, and TODO files are not committed.
7. Docs are not runtime contracts. Delete or merge directly; do not add compatibility shims.

Why: an AI agent reads a subset of the repo. More docs means more chances to read
the wrong one. Stale or duplicate docs are worse than no docs. One owner means one
place to update. This is Design Axiom 13 — alignment has a budget — applied to
documentation.

## Change workflow

- **Read the quality contract in `MAINTAINERS.md` before proposing any optimization or new
  implementation.** The 98% quality floor outranks token, API-call, and speed savings. Do not
  remove context, reasoning, provenance, or hard-earned heuristics to make a run cheaper.
- **Use `ponytail` at `ultra` for code implementation.** Load the skill before changing code,
  keep the diff minimal, and keep the explanation short. The user can override it with
  "normal mode" or "stop ponytail".
- **Use the todo tool (`todowrite`) for multi-step work.** Create the list up front, keep exactly
  one item in progress, and update it as work lands or new follow-ups appear. A stale todo list
  is a failed handoff.
- **Every behavior, script, schema, reference, packaging, or install change gets a changelog
  entry under the section matching `VERSION`. Do not bump `VERSION` or create a new version
  unless the user explicitly says so.** Do not leave a change only in code or docs.
- **Run `bash scripts/smoke.sh` for behavior, script, schema, packaging, or test changes.** It
  includes the changelog/version check, package/shipping manifest check, negative fixtures,
  golden deck, sabotage probes, video fixtures, and installer test.
- **Passing tests are a floor, not proof.** They show expected paths do not syntactically fail;
  they do not prove card quality, adherence to the skill, or alignment. Review the control flow,
  failure modes, user impact, and maintainability of every change.
- **Docs-only changes do not need the full smoke.** For `CHANGELOG.md`/`VERSION`, run
  `python3 scripts/changelog_check.py`; for prose only, a diff check is enough.
- **Do not silently rewrite hard-earned rules or validators.** Fold new lessons into the rule
  they belong to; keep the why.
- **No zip/package rebuild unless the user asks.** `package_handoff.sh` is ready.

## Runtime contract

`SKILL.md` is the 7-step runbook. Do not add diagnosis commands, deck-script authoring paths,
per-card ledgers, or fixed card/KC/call quotas to it. The model writes its own budget from scope;
runtime rules are structural and scale-free. A new runtime artifact or command must replace an
existing one, not sit beside it. Keep `SKILL.md` under ~300 lines and ten hard rules.

Do not edit the live skill while a deck run is active. Use a copy or finish the run first; a gate
schema change under a running model forces rework.

Read `MAINTAINERS.md` § Design axioms and § Research anchors before changing a stage, reference,
script, gate, or command. Remember: more systems and more context eventually reduce alignment.

## Complexity review

For every change, feature, or implementation suggestion, ask first: **is there an implementation
that reduces the overall complexity of the skill/repo?** Prefer fewer systems, artifacts, commands,
checks, gates, steps, and prose — not the simplest local code at any cost, but the change that
removes more surface than it adds. If it adds runtime surface, name what it replaces. Record the
answer in the changelog or handoff.

## Independent maintainer audit

Before calling a change to `SKILL.md`, references, stage flow, commands, or pipeline behavior good:

1. Run `bash scripts/smoke.sh` and the focused tests. Smoke is a passability floor, not quality.
2. Run the **cold dry-run** below: a fresh agent with no prior context reads `SKILL.md` and
   attempts the skill end to end in `/tmp`. It should write artifacts, run the real commands, and
   report breaks. A plan-only answer is not a dry run.
3. Optionally run one read-only plan audit on a different source type to catch comprehension gaps.
4. Do the manual code and heuristic reasoning yourself.
5. Record findings. A clean run is not certification; passing tests do not prove quality or
   adherence.

### Cold dry-run audit

Use a tiny text source so the run is fast:

```bash
mkdir -p /tmp/opencode/anki-cold-<date>
printf '%s\n' \
  "Ohm's law: V = IR. Resistance is the ratio V/I." \
  "In a series circuit, the same current flows through every element." \
  "In a parallel circuit, the same voltage appears across every branch." \
  > /tmp/opencode/anki-cold-<date>/notes.txt
```

Give the agent only the skill path, the user request, and these constraints. Do not describe the
seven steps or the expected answers; the point is to see what the skill alone produces.

> This is a cold-start dry run. Treat it as a fresh task: do not use prior conversation context.
> Read `SKILL.md` first; open another reference only when the skill says that step needs it.
>
> Skill root: `<skill root>`
> Work only in `/tmp/opencode/anki-cold-<date>`. Do not modify the skill repo.
>
> User request: "Make flashcards from notes.txt. Call the deck COLD::TEST."
>
> No human reviewer is available: skip the web review, but run gates and build. Do not run a
> background review server; do not wait. Skip the adversarial subagent if no read-only subagent
> tool is available. No images. Do not leave background processes.
>
> Attempt the skill end to end. You may write intake.md (with a Scope section), kcs.md, cards.jsonl, and
> work files under the temporary folder. Use the skill's scripts directly. If a command fails, capture the exact
> error and continue only if safe.
>
> Report: steps and exact commands; artifacts; where the skill broke, was ambiguous, or made you
> guess; whether you stayed on the path; unclear defaults (adversarial, images, context/dossier,
> review actions). Do not fix the skill. Leave the folder for inspection.

Findings: a confirmed break gets a fix and, where deterministic, a regression test. An ambiguous
line gets a one-line wording fix; do not add a new stage or document. A default confusion belongs
in `SKILL.md`, not in a new reference. One cold dry-run per runtime change is enough; use a second
prompt only when the first is clean but the change touches a different source type.

Never let the cold agent edit the repo or spawn an `opencode` child. Keep the temporary folder
until findings are recorded, then remove it. Tests are a floor; this audit finds what tests cannot.

## Agent execution boundaries

- **Do not spawn opencode child processes** (including `opencode run`, `debug`, `serve`,
  or attach) or recursively call the skill from a test/debug agent.
- **Do not use main-model vision while testing the deck path.** Do not `read` images,
  frames, scans, screenshots, or contact sheets. Use `frames.md`/metrics; only the
  separate `image-vision` pass may inspect an ambiguous frame.
- **Do not probe for office/desktop converters** (LibreOffice, `soffice`, Office) or
  unrelated tools. Use the skill's declared extractors; after two failed probes,
  report the limitation.
- **Do not run commands that can hang** (interactive servers, playback, unbounded
  downloads). Use short timeouts and bounded subprocess calls.
- **Never sleep to wait out a rate limit or yt-dlp failure.** The yt-dlp wrapper
  retries transient errors briefly; skip/report permanent ones. Exception: `image-vision/scripts/vision_check.py`
  proactively paces Gemini calls and may perform one bounded `--retry-429` sleep; never loop on 429.
- **Do not kill the harness or your own process.** A test may stop only the known
  child process it started, after a timeout.
- **Never stop a child with `pkill -f`/`pgrep -f` and a literal script name.**
  The pattern can match the shell running the command. Capture the PID (`$!`),
  use the tool's finish endpoint, or use a bracket pattern such as
  `pkill -f '[v]ision_check.py'`.
- **Run autonomously to completion once a plan exists.** Ask only when blocked by
  a destructive choice or missing input the user must provide.

## Deprecations

Legacy paths are acknowledged in exactly one place: `MAINTAINERS.md` § Deprecations. Do not add a
runtime alias or compatibility shim without a removal version in that table. Docs are consolidated
immediately because they are not runtime contracts.
