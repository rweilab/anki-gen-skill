# Dev workflow

This file is for maintainers/agents changing the skill; it is not loaded during a
normal deck run.

- **Read the quality contract in `MAINTAINERS.md` before proposing any optimization or new
  implementation.** The 98% quality floor outranks token, API-call, and speed savings. Do not
  remove context, reasoning, provenance, or hard-earned heuristics to make a run cheaper.

- **Use `ponytail` at `ultra` for code implementation.** This is a standing
  maintainer instruction: load the skill before changing code, keep the diff
  minimal, and keep the explanation short. The user can override it with
  "normal mode" or "stop ponytail".

- **Use the todo tool (`todowrite`) for multi-step work.** Create the
  list up front, keep exactly one item in progress, and update it as work lands
  or new follow-ups appear. A stale todo list is a failed handoff.

- **Every behavior, script, schema, reference, packaging, or install change gets a
  changelog entry under the section matching `VERSION`. Do not bump `VERSION` or
  create a new version unless the user explicitly says so.** Do not leave a change
  only in code or docs.
- **Run `bash scripts/smoke.sh` for behavior, script, schema, packaging, or test
  changes.** It includes the changelog/version check, package/shipping manifest
  check, negative fixtures, golden deck, sabotage probes, video fixtures, and
  installer test.
- **Docs-only changes do not need the full smoke.** For `CHANGELOG.md`/`VERSION`,
  run `python3 scripts/changelog_check.py`; for prose only, a diff check is enough.
- **Do not silently rewrite hard-earned rules or validators.** Fold new lessons
  into the rule they belong to; keep the why.
- **No zip/package rebuild unless the user asks.** `package_handoff.sh` is ready.
- **Read `MAINTAINERS.md`** before architectural or token-efficiency changes.

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
  retries transient errors briefly; skip/report permanent ones.
- **Do not kill the harness or your own process.** A test may stop only the known
  child process it started, after a timeout.
- **Run autonomously to completion once a plan exists.** Ask only when blocked by
  a destructive choice or missing input the user must provide.
