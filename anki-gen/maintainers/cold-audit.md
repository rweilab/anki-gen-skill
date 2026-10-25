# Cold dry-run audit

Passing tests prove only that expected paths do not syntactically fail. They do not prove card
quality, adherence to the runbook, or that a fresh agent can use the skill. Run this after
`smoke.sh` for any change to `SKILL.md`, references, commands, gates, or pipeline behavior.

## What it is

A fresh agent with no conversation history reads `SKILL.md` for the first time and **attempts the
skill end to end** in a temporary folder. This is a dry run, not a plan review. It should write the
artifacts, run the real commands, and hit real failures.

## Setup

Use a tiny text source so the run is fast.

```bash
mkdir -p /tmp/opencode/anki-cold-<date>
printf '%s\n' \
  "Ohm's law: V = IR. Resistance is the ratio V/I." \
  "In a series circuit, the same current flows through every element." \
  "In a parallel circuit, the same voltage appears across every branch." \
  > /tmp/opencode/anki-cold-<date>/notes.txt
```

Do not let the agent modify the skill repo. Work only under the temporary folder.

## Agent prompt

Give the agent only the skill path, the user request, and these constraints. Do not describe the
seven steps or the expected answers; the point is to see what the skill alone produces.

> This is a cold-start dry run. Treat it as a fresh task: do not use prior conversation context.
> Read `SKILL.md` first; open another reference only when the skill says that step needs it.
>
> Skill root: `/home/slap/repos/anki-gen-skill/anki-gen`
> Work only in `/tmp/opencode/anki-cold-<date>`. Do not modify the skill repo.
>
> User request: "Make flashcards from notes.txt. Call the deck COLD::TEST."
>
> No human reviewer is available: skip the web review, but run gates and build. Do not run a
> background review server; do not wait. Skip the adversarial subagent if no read-only subagent
> tool is available. No images. Do not leave background processes.
>
> Attempt the skill end to end. You may write intake.md, scope_gate.md, kcs.md, cards.jsonl, and
> work files under the temporary folder. Use the skill's scripts directly. If a command fails,
> capture the exact error and continue only if safe.
>
> Report: steps and exact commands; artifacts; where the skill broke, was ambiguous, or made you
> guess; whether you stayed on the path; unclear defaults (adversarial, images, context/dossier,
> review actions). Do not fix the skill. Leave the folder for inspection.

## What to do with findings

- A **confirmed break** gets a fix and, where deterministic, a regression test.
- An **ambiguous line** gets a one-line wording fix; do not add a new stage or document.
- A **default confusion** belongs in `SKILL.md`, not in a new reference.
- A clean run is not certification. Record what the agent did not exercise: web review, human
  judgment, image vision, real course material.

## Rules

- One cold dry-run per runtime change is enough; use a second prompt only when the first is clean
  but the change touches a different source type.
- Never let the cold agent edit the repo or spawn an `opencode` child.
- Keep the temporary folder until the findings are recorded, then remove it.
- Tests are a floor. This audit is how the skill finds the failures tests cannot see.
