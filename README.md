# anki-gen + image-vision

Turn lecture PDFs, PowerPoints, notes, homework, and videos into evidence-based
Anki decks. The builder produces an `.apkg`; importing into Anki is manual.
Slide and video images are on by default; text-only sources stay text-first, and
you can say no. Review happens on a local 1–5 page. Building is local; only the
optional Gemini pass for handwriting or ambiguous frames uploads images.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/rweilab/anki-gen-skill/main/bootstrap.sh | bash
```

Or extract the ZIP and run `bash install.sh`. Restart or reload opencode, then ask:

> make flashcards from the PDFs in this folder

Review the local page, then use **File → Import** in Anki.

## What you need

- **Python 3.10+**.
- **Anki Desktop** for import and revision. The skill never installs Anki.
- **macOS or Linux.** Windows: use WSL2 for generation; revision needs Anki
  Desktop reachable from WSL2.
- Optional: a Gemini key for handwriting/ambiguous images, ffmpeg/yt-dlp for
  video, and local transcription for recordings without captions.
- The installer uses `~/.claude/skills/`. For opencode or another harness, set
  `ANKI_GEN_SKILLS_DIR` (for example `~/.config/opencode/skills`).

## Use

- **New deck:** “make flashcards from the PDFs and PowerPoints in this folder.”
- **Video:** “make flashcards from this playlist.” It asks once before pulling
  stills.
- **Existing deck:** “revise my imported deck.” Uses AnkiConnect; open Anki
  first, and never inspect the collection database.
- **Images:** slide/video images are on by default; candidates are never
  auto-attached; one image per card by default, up to two when both are needed.
- **Review:** open the local page, score and comment, then import. If no human is
  available to review, the deck is marked “not manually reviewed”; the automatic
  checks and the second AI reviewer still run when available.

## Setup, doctor, update

- Re-run setup: `bash ~/.claude/skills/anki-gen/scripts/setup.sh`
  (`--print-only` shows the commands).
- Check the machine: `python3 ~/.claude/skills/anki-gen/scripts/doctor.py`
- Gemini key (optional):
  ```bash
  mkdir -p ~/.config/anki-gen && chmod 700 ~/.config/anki-gen
  read -rsp "Gemini key: " KEY; printf '\n'
  printf '%s\n' "$KEY" > ~/.config/anki-gen/gemini.key
  chmod 600 ~/.config/anki-gen/gemini.key
  ```
  Without it, text decks and direct slide/frame images still work; ambiguous
  images and handwriting are skipped. Never paste the key into chat.
- Update by re-running the installer. It backs up under
  `~/.local/share/anki-gen/backups/` and leaves your config untouched.

## Troubleshooting

- Run `doctor.py` first; it names the missing library or tool and the platform fix.
- Restart/reload opencode if the skill is not found; check `ANKI_GEN_SKILLS_DIR`.
- AnkiConnect: open Anki, then run
  `python3 ~/.claude/skills/anki-gen/scripts/anki_connect.py`.
- Missing images: check whether the source is text-only, whether you declined
  images, and whether the frame was ambiguous enough to need `image-vision`.
- Do not install Office or invent an ad-hoc converter; report the source instead.

## Development

```bash
ln -s ~/repos/anki-gen-skill/anki-gen ~/.claude/skills/anki-gen
ln -s ~/repos/anki-gen-skill/image-vision ~/.claude/skills/image-vision
```

Update with `git pull`; do **not** run `install.sh` on a symlinked checkout. Run
`bash ~/.claude/skills/anki-gen/scripts/smoke.sh` for the mechanical check, and
see `anki-gen/AGENTS.md` for the maintainer workflow.
