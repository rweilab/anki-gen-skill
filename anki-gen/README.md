# anki-gen — maintainer and vendoring notes

The user guide is the repo root `README.md`; in the handoff zip it ships as
`INSTALL.md`. A normal deck run reads `SKILL.md`, not this file.

- Python 3.10+; `anki` is required for every build. Do not reintroduce `genanki`.
- `scripts/setup.sh` installs missing system and Python packages best effort;
  `doctor.py` checks the result. Do not duplicate the OS matrix here.
- MathJax is vendored at `assets/mathjax/tex-svg.js`. Do not use a CDN.
- Anki Desktop is external; import is manual. Revision uses AnkiConnect only;
  never inspect the collection database. See `references/revision.md`.
- Tests: `bash scripts/smoke.sh`. Packaging: `scripts/package_handoff.sh`.
  Maintainer workflow: `AGENTS.md` and `MAINTAINERS.md`.
