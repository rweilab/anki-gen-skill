# anki-gen + image-vision

Build evidence-based Anki decks from lecture PDFs, notes, homework, and YouTube
videos. Text-first by default; diagram images and video stills are opt-in.

The builder creates an `.apkg`. Importing it into Anki is manual.

## Install

No Git required:

```bash
curl -fsSL https://raw.githubusercontent.com/YOUR_GITHUB_USER/anki-gen-skill/main/bootstrap.sh | bash
```

Or click **Code → Download ZIP**, extract it, and run:

```bash
bash install.sh
```

The installer places both skills in `~/.claude/skills/`, verifies them, and
backs up any previous install under `~/.claude/skills/.backups/`. It never
touches `~/.config/anki-gen` or your Anki collection.

Restart or reload opencode afterwards.

## Setup

```bash
bash ~/.claude/skills/anki-gen/scripts/setup.sh
```

This prints the system packages for your OS and installs the Python libraries
into your user site. It never runs `sudo`.

| OS | System packages |
|---|---|
| macOS | `brew install python poppler ffmpeg tesseract`; Anki: `brew install --cask anki` |
| Debian/Ubuntu | `sudo apt install python3 python3-pip python3-venv poppler-utils ffmpeg tesseract-ocr` |
| Fedora | `sudo dnf install python3 python3-pip poppler-utils ffmpeg tesseract` (FFmpeg may need RPM Fusion) |
| Arch | `sudo pacman -S python python-pip poppler ffmpeg tesseract` |

Install the Anki desktop app separately. On Linux, use the official AppImage or
Flathub.

## Doctor

Run this from a terminal and again from inside opencode:

```bash
python3 ~/.claude/skills/anki-gen/scripts/doctor.py
```

It reports the version, Python, libraries, PDF/video tools, FTS5, the optional
Gemini key, and the platform-specific fix for anything missing. Exit code 1
means the core text path is not ready.

## Gemini key (optional)

Only needed for handwriting or figures handled by `image-vision`:

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

For a YouTube video or playlist:

> make flashcards from this playlist

The agent asks once whether to pull diagram stills, selects candidate frames,
and lists low-confidence frames instead of forcing them into cards. Review is a
local 1–5 page at `127.0.0.1`; scope is sampled, not the whole deck. Then import
the `.apkg` with **File → Import** in Anki.

## Update

Run the install command again. The installer prints the old and new versions and
leaves a timestamped backup under:

```text
~/.claude/skills/.backups/anki-gen-YYYYMMDD-HHMMSS/
```

Your config and Gemini key in `~/.config/anki-gen/` are untouched.

## Development

For a symlinked working copy, keep the real folders in a repo and symlink them
into the skills directory:

```bash
ln -s ~/repos/anki-gen-skill/anki-gen ~/.claude/skills/anki-gen
ln -s ~/repos/anki-gen-skill/image-vision ~/.claude/skills/image-vision
```

Use `git pull` to update. Do **not** run `install.sh` on a symlinked checkout;
it would replace the symlinks with copies.

## Notes

- Text-first is the default; images are opt-in.
- `image-vision` and Gemini are optional.
- No Whisper; videos without captions are skipped.
- Anki desktop is not installed by this skill.
- `vision-sidecar/` folders are safe to delete.
