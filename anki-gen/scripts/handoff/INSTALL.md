# anki-gen handoff

This folder contains two opencode skills:

- `anki-gen` — the deck builder
- `image-vision` — optional Gemini reading for handwriting/figures

The builder produces an `.apkg`. **Importing it into Anki is manual.**

## Install / upgrade

```bash
bash install.sh
```

The installer stages both skills, verifies them, backs up existing installs,
and replaces them. It never touches `~/.config/anki-gen` or your decks.

Restart opencode (or reload skills) afterwards.

## Setup

```bash
bash ~/.claude/skills/anki-gen/scripts/setup.sh
```

This prints the system package commands for your OS and installs the Python
libraries into the user site. It **never runs sudo**.

| OS | System packages (printed by setup) |
|---|---|
| macOS | `brew install python poppler ffmpeg tesseract`; Anki: `brew install --cask anki` |
| Debian/Ubuntu | `sudo apt install python3 python3-pip python3-venv poppler-utils ffmpeg tesseract-ocr` |
| Fedora | `sudo dnf install python3 python3-pip poppler-utils ffmpeg tesseract` (FFmpeg may need RPM Fusion) |
| Arch | `sudo pacman -S python python-pip poppler ffmpeg tesseract` |

Install the Anki desktop app separately. Linux: official AppImage or Flathub.

## Doctor

Run it from Terminal **and** from inside opencode:

```bash
python3 ~/.claude/skills/anki-gen/scripts/doctor.py
```

It reports the version, Python, libraries, PDF/video tools, FTS5, the Gemini key,
and the platform-specific fix for anything missing. Exit 1 means the core text
path is not ready.

If a GUI-launched opencode reports the wrong Python, launch opencode from a
terminal or use the Python/user site that the doctor sees.

## Gemini key (optional)

Only for handwriting/figures/image-vision:

```bash
mkdir -p ~/.config/anki-gen
chmod 700 ~/.config/anki-gen
read -rsp "Gemini key: " KEY; printf '\n'
printf '%s\n' "$KEY" > ~/.config/anki-gen/gemini.key
chmod 600 ~/.config/anki-gen/gemini.key
```

No key is not fatal. Text decks work; handwriting/figures are skipped. Never paste
the key into chat.

## Use

Ask opencode:

> make flashcards from the PDFs in this folder

Text-first is the default. For a video:

> make flashcards from this playlist

The agent asks once whether to pull diagram stills. It auto-selects frames; one
image per card; low-confidence frames are listed, not forced into cards.

Review is a local 1–5 page on `127.0.0.1`. Open it on the same machine. Scope is
sampled, not the whole deck. Then **File → Import** the `.apkg` into Anki.

## Update

Extract a newer handoff zip and run `bash install.sh` again. It prints the old and
new versions and leaves a timestamped backup under `~/.claude/skills/.backups/`.
No auto-downloader or background updater.

## Notes

- Text-first is the default; images are opt-in.
- `image-vision`/Gemini is optional and external.
- No Whisper; videos without captions are skipped.
- Anki desktop is not installed by this skill.
- `vision-sidecar/` folders are safe to delete.
