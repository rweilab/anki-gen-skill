# Handoff — anki-gen + image-vision

The builder creates an `.apkg`; importing it into Anki is manual.

## If you received `anki-gen-handoff.zip`

1. Extract it.
2. Run `bash install.sh` (or ask opencode to install it).
3. Restart/reload opencode.

The installer upgrades safely: it stages both skills, verifies `SKILL.md`, backs
up the old install, preserves `~/.config/anki-gen`, installs the missing
dependencies, and runs the doctor. It never installs Homebrew or Anki.

Dependency setup, the OS matrix, Gemini key, update steps, and usage are in
`INSTALL.md` inside the handoff zip.
