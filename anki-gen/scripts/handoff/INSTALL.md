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
replaces them, installs core dependencies, attempts optional features best-effort,
and runs the doctor. Optional failures warn; they do not abort the install. Setup
ends with `Full feature set: installed` or `Full feature set: NOT installed` and
lists the gaps. It never touches `~/.config/anki-gen` or your decks, and it never
installs Homebrew or Anki.

Restart opencode (or reload skills) afterwards.

## Setup

The installer already did this. To re-run it:

```bash
bash ~/.claude/skills/anki-gen/scripts/setup.sh
```

It installs the core Python packages, attempts optional image/video/local-audio
features best-effort, then runs the doctor. YouTube support comes from
`yt-dlp[default,deno]` in the optional requirements, including EJS and Deno; no
system Node install is needed. PyMuPDF is pinned below 2.0 for stable wheels.
PowerPoint text/notes/embedded images are read without Office. macOS without
Homebrew and Linux without sudo still get the core path; missing optional tools
are warnings. `--print-only` shows the commands without changing anything.

The Anki desktop app is separate and never installed by this skill. It is only
needed to import the finished `.apkg`.

Local recordings use ffprobe + ffmpeg and either sidecar VTT/SRT, faster-whisper,
or whisper.cpp. faster-whisper is used when importable; otherwise setup.sh installs
whisper.cpp on Apple Silicon, and on Linux when faster-whisper is unavailable.
The whisper.cpp model downloads on first use. Media is never uploaded. Apple
Silicon macOS and mainstream Linux are supported; Intel Macs are best-effort.

| OS | System packages setup installs when missing |
|---|---|
| macOS | `python poppler pandoc ghostscript mupdf-tools ffmpeg tesseract` |
| Debian/Ubuntu | `python3 python3-pip poppler-utils pandoc ghostscript mupdf-tools ffmpeg tesseract-ocr` |
| Fedora | `python3 python3-pip poppler-utils pandoc ghostscript mupdf-tools ffmpeg tesseract` |
| Arch | `python python-pip poppler pandoc ghostscript mupdf-tools ffmpeg tesseract` |

## Doctor

The installer runs it automatically. To check again:

```bash
python3 ~/.claude/skills/anki-gen/scripts/doctor.py
```

It reports the version, Python, libraries, PDF/video tools, FTS5, the Gemini key,
the Anki app, and the platform-specific fix for anything missing. Exit 1 means
the core text path is not ready.

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

> make flashcards from the PDFs or PowerPoints in this folder

Text-first is the default. For a video:

> make flashcards from this playlist

The agent asks once whether to pull diagram stills. It auto-selects frames and may
reuse a shared diagram on several related cards; the main model never reads the
images. Ambiguous frames go to the separate image-vision pass.

Review is a local 1–5 page on `127.0.0.1`. Open it on the same machine. Scope is
sampled, not the whole deck. Then **File → Import** the `.apkg` into Anki.

New cards are ordered by source topic, with each topic's concept card first. To
follow that exact order, set **New Card Sort Order** to **Order gathered**.

## Update

Extract a newer handoff zip and run `bash install.sh` again. It prints the old and
new versions and leaves a timestamped backup under
`~/.local/share/anki-gen/backups/`.
No auto-downloader or background updater.

## Notes

- Text-first is the default; images are opt-in.
- `image-vision`/Gemini is optional and external.
- Local audio is optional: faster-whisper or whisper.cpp; the model downloads on first use. YouTube captions and sidecar VTT/SRT work without it.
- Anki desktop is not installed by this skill.
- `vision-sidecar/` folders are safe to delete.
