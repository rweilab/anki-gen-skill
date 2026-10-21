# anki-gen + image-vision

Turn lecture PDFs, notes, homework, and YouTube videos into evidence-based
Anki decks. Text-first; diagram images and video stills are optional.

The builder produces an `.apkg`. Importing it into Anki is manual.

## Install

No Git required:

```bash
curl -fsSL https://raw.githubusercontent.com/rweilab/anki-gen-skill/main/bootstrap.sh | bash
```

Or use **Code → Download ZIP**, extract it, and run:

```bash
bash install.sh
```

The installer puts both skills in `~/.claude/skills/`, verifies them, and backs
up any previous install under `~/.claude/skills/.backups/`. It does not touch
`~/.config/anki-gen` or your Anki collection.

Restart or reload opencode afterwards.

## Setup

Requires Python 3.10+ and the Anki desktop app.

```bash
bash ~/.claude/skills/anki-gen/scripts/setup.sh
```

The script prints the system packages for your OS and installs the Python
libraries into your user site. It never runs `sudo`.

Then check the install from a terminal **and** from inside opencode:

```bash
python3 ~/.claude/skills/anki-gen/scripts/doctor.py
```

Exit code 1 means the core text path is not ready. The doctor prints the fix.

## Optional Gemini key

Only needed for handwriting and figures handled by `image-vision`:

```bash
mkdir -p ~/.config/anki-gen
chmod 700 ~/.config/anki-gen
read -rsp "Gemini key: " KEY; printf '\n'
printf '%s\n' "$KEY" > ~/.config/anki-gen/gemini.key
chmod 600 ~/.config/anki-gen/gemini.key
```

Without a key, text decks still work; handwriting and figures are skipped.
Never paste the key into chat.

## Use

Ask opencode:

> make flashcards from the PDFs in this folder

For a video or playlist:

> make flashcards from this playlist

The agent asks once whether to pull diagram stills, picks candidate frames, and
lists low-confidence frames rather than forcing them into cards. Review is a
local 1–5 page on `127.0.0.1`; scope is sampled, not the whole deck. Then use
**File → Import** in Anki.

## Update

Run the install command again. The installer prints the old and new versions and
leaves a timestamped backup under:

```text
~/.claude/skills/.backups/anki-gen-YYYYMMDD-HHMMSS/
```

Your config and Gemini key in `~/.config/anki-gen/` are untouched.

## Development

Keep the real folders in the repo and symlink them into the skills directory:

```bash
ln -s ~/repos/anki-gen-skill/anki-gen ~/.claude/skills/anki-gen
ln -s ~/repos/anki-gen-skill/image-vision ~/.claude/skills/image-vision
```

Update with `git pull`. Do **not** run `install.sh` on a symlinked checkout; it
would replace the symlinks with copies.

## Notes

- Text-first is the default; images are opt-in.
- `image-vision` and Gemini are optional.
- No Whisper; videos without captions are skipped.
- Anki desktop is not installed by this skill.
- `vision-sidecar/` folders are safe to delete.
