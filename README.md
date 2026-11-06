# anki-gen

Turn PDFs, lecture slides, notes, homework, and videos into evidence-based Anki decks, then proofread, score, and comment on the cards in a local review page before importing.

It runs in opencode and builds an `.apkg` that you import into Anki Desktop.

## Prerequisites

- **opencode** installed (<https://opencode.ai>). Free models work without signing in.
- **Anki Desktop** (<https://apps.ankiweb.net/>) for import and revision. Install it separately; this tool never installs Anki.
- **Python 3.10+**. The installer handles it where possible.
- **macOS:** Homebrew (<https://brew.sh>) recommended; it supplies Python and system tools. **Linux:** `sudo` available, so the installer can add missing system tools.
- Optional: a Gemini key for handwriting or ambiguous images, plus video and local-transcription tools. Missing optional features do not block text decks.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/rweilab/anki-gen-skill/main/bootstrap.sh | bash
```

The installer sets up the skills and their dependencies, then checks the setup. It does not install Homebrew or Anki. Restart or reload opencode when it finishes.

If that does not work, download the repository ZIP from GitHub, extract it, and run `bash install.sh`.

To update, re-run the same command. Your existing config is kept.

## Supported systems

First-class support: **Apple Silicon Macs** and mainstream Linux distributions — Ubuntu, Debian, Linux Mint, Pop!_OS, Fedora/RHEL-family, and Arch/Manjaro.

## Make your first deck

1. Put your PDFs, slides, and notes in one folder.
2. Open a terminal in that folder and start opencode.
3. Ask in plain English. For example:
   - "Make flashcards from the PDFs in this folder."
   - "Make a deck from these lecture slides. Call it BIO 101."
   - "Make flashcards from this video: <URL>."
4. Answer the one or two questions it asks, then wait. It writes the deck, starts a local review page, and gives you the link.
5. Open the review page, proofread the cards on the page, score them, and comment on anything wrong. Finish the review when you are done.
6. Import the `.apkg` with **File → Import** in Anki. The file is in the folder you started from.

Do the review. It is where bad cards get fixed before they reach Anki. If no human is available, the deck is marked "not manually reviewed"; automatic checks and the second AI reviewer still run when available.

## What you can give it

- PDFs, PowerPoint `.pptx`, notes, homework, and textbooks.
- Scanned pages and handwriting through the bundled `image-vision` skill. Quality depends on legibility.
- YouTube videos and playlists.
- Local audio and video recordings. Recordings without captions use local transcription, and the transcription model downloads on first use.

You do not need Microsoft Office or LibreOffice. If a file cannot be extracted, the tool reports it instead of converting it.

Images are on by default for slides, video, and figure-heavy PDFs. You can say no. For video, it asks before pulling frames. Cards get one image by default, or two when both are needed.

## Updating an existing deck

Open Anki Desktop, leave it running, then ask "revise my imported deck." The skill uses AnkiConnect, a local add-on inside Anki, to update the deck while keeping your scheduling. It never edits Anki's database directly.

Check the connection with:

```bash
python3 ~/.claude/skills/anki-gen/scripts/anki_connect.py
```

## Privacy

- Deck building and the review page run on your machine. Your PDFs, slides, and recordings are not uploaded as files.
- Your opencode model provider receives the text opencode reads, under its own terms.
- Normally, the skill sends images only for the optional Gemini check on handwriting or ambiguous frames. If image-vision is unavailable, a necessary image may go through your opencode model provider instead.
- YouTube content is fetched from YouTube. Local recordings are not uploaded.
- The review page is temporary and reachable only from your computer. No account, telemetry, or cloud deck storage.

Gemini is optional. Without a key, text decks and ordinary slide or frame images still work; handwriting and ambiguous images are skipped. To set a key:

```bash
mkdir -p ~/.config/anki-gen && chmod 700 ~/.config/anki-gen
read -rsp "Gemini key: " KEY; printf '\n'
printf '%s\n' "$KEY" > ~/.config/anki-gen/gemini.key
chmod 600 ~/.config/anki-gen/gemini.key
```

Never paste the key into chat.

## Troubleshooting

- **Something is missing:** run `python3 ~/.claude/skills/anki-gen/scripts/doctor.py`; it names the missing library or tool and the platform fix.
- **Skill not found after install:** restart or reload opencode. Check that `~/.claude/skills/anki-gen/SKILL.md` exists, or set `ANKI_GEN_SKILLS_DIR`.
- **Installer warns about missing optional features:** core text decks still work. Re-run setup after fixing the warnings: `bash ~/.claude/skills/anki-gen/scripts/setup.sh`
- **macOS cannot find Python or Homebrew tools:** install Homebrew, then launch opencode from Terminal so it sees `/opt/homebrew/bin`.
- **AnkiConnect is not responding:** open Anki, then run the check command above. The skill can help install the add-on when asked.
- **Images are missing:** the source may be text-only, you may have declined images, or the frame needs `image-vision`.
- **A file will not extract:** report the source. Do not install Office or LibreOffice, and do not write your own converter.

For help, open a GitHub issue and include your OS and architecture, the `doctor.py` output, and the command that failed. Do not include API keys or private course files.

## Maintainers

See `anki-gen/AGENTS.md` for the maintainer workflow and `anki-gen/MAINTAINERS.md` for the quality contract.
