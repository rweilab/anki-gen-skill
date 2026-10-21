# Handoff — anki-gen + image-vision

The builder creates an `.apkg`; importing it into Anki is manual.

## If you received `anki-gen-handoff.zip`

1. Extract it.
2. Run `bash install.sh` (or ask opencode to install it).
3. Restart/reload opencode.
4. Run `bash ~/.claude/skills/anki-gen/scripts/setup.sh`.
5. Run `python3 ~/.claude/skills/anki-gen/scripts/doctor.py` from Terminal and
   from inside opencode.

The installer upgrades safely: it stages both skills, verifies `SKILL.md`, backs
up the old install, and preserves `~/.config/anki-gen`.

Platform setup, the OS matrix, Gemini key, update steps, and usage are in
`INSTALL.md` inside the handoff zip.
