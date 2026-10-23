# anki-gen + image-vision

Turn lecture PDFs, PowerPoint decks, notes, homework, and YouTube videos into
evidence-based Anki decks. Text-first; diagram images and video stills are optional.

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

The installer puts both skills in `~/.claude/skills/`, verifies them, backs up
any previous install under `~/.local/share/anki-gen/backups/`, installs the missing
system and Python dependencies, and runs the doctor. It does not touch
`~/.config/anki-gen` or your Anki collection.

Homebrew and the Anki desktop app are never installed. AnkiConnect is a separate
add-on inside Anki Desktop; the revision workflow can detect the Anki profile and
install a pinned build only after you approve it. On macOS, Homebrew must already
be present if a system tool is missing. On Linux, package installation uses
`sudo` and asks for your password once.

Restart or reload opencode afterwards.

## Setup

The install command already does this. To re-run it later:

```bash
bash ~/.claude/skills/anki-gen/scripts/setup.sh
```

It installs only the missing system tools and Python libraries, then runs the
doctor silently. You only see the full doctor output if a core check fails.
`--print-only` shows the commands without changing anything.

The Anki desktop app is only needed to import the finished `.apkg`; it is not a
build dependency and this skill never installs it.

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

For a local recording or a video playlist:

> make flashcards from this playlist

The agent asks once whether to pull diagram stills, picks candidate frames, and
lists low-confidence frames rather than forcing them into cards. Review is a
local 1–5 page on `127.0.0.1`; scope is sampled, not the whole deck. Then use
**File → Import** in Anki.

## Update

Run the install command again. The installer prints the old and new versions and
leaves a timestamped backup under:

```text
~/.local/share/anki-gen/backups/anki-gen-YYYYMMDD-HHMMSS/
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
