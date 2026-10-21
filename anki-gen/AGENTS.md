# Dev workflow

This file is for maintainers/agents changing the skill; it is not loaded during a
normal deck run.

- **Every behavior, script, schema, reference, packaging, or install change gets a
  changelog entry under the current v1.3 section. Do not bump `VERSION` or create a
  new version unless the user explicitly says so.** Do not leave a change only in
  code or docs.
- **Run `bash scripts/smoke.sh`.** It includes the changelog/version check,
  package/shipping manifest check, negative fixtures, golden deck, sabotage
  probes, video fixtures, and installer test. Run it after every changelog or
  packaging change.
- **Do not silently rewrite hard-earned rules or validators.** Fold new lessons
  into the rule they belong to; keep the why.
- **No zip/package rebuild unless the user asks.** `package_handoff.sh` is ready.
- **Read `MAINTAINERS.md`** before architectural or token-efficiency changes.

## Agent execution boundaries

- **Do not spawn opencode child processes** or recursively call the skill from a
  test/debug agent.
- **Do not run commands that can hang** (interactive servers, playback, unbounded
  downloads). Use short timeouts and bounded subprocess calls.
- **Do not kill the harness or your own process.** A test may stop only the known
  child process it started, after a timeout.
- **Run autonomously to completion once a plan exists.** Ask only when blocked by
  a destructive choice or missing input the user must provide.
