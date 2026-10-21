#!/usr/bin/env bash
# Install or upgrade anki-gen + image-vision into ~/.claude/skills/.
# Safe upgrade: stage, verify, back up the old directories, then replace.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${ANKI_GEN_SKILLS_DIR:-$HOME/.claude/skills}"
NEW_VERSION="$(cat "$HERE/anki-gen/VERSION" 2>/dev/null || echo unknown)"
OLD_VERSION="$(cat "$DEST/anki-gen/VERSION" 2>/dev/null || echo none)"
STAGE=""
BACKUP=""

cleanup() {
  if [ -n "$STAGE" ]; then rm -rf "$STAGE"; fi
  if [ -n "$BACKUP" ] && [ -d "$BACKUP" ] && [ -z "$(ls -A "$BACKUP" 2>/dev/null)" ]; then
    rmdir "$BACKUP" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [ "${1:-}" = "--version" ]; then
  echo "anki-gen $NEW_VERSION"
  exit 0
fi

if [ ! -f "$HERE/anki-gen/SKILL.md" ] || [ ! -f "$HERE/image-vision/SKILL.md" ]; then
  echo "Missing anki-gen/ or image-vision/ next to install.sh — re-extract the zip." >&2
  exit 1
fi

mkdir -p "$DEST"
STAGE="$(mktemp -d "$DEST/.anki-install.XXXXXX")"
cp -R "$HERE/anki-gen" "$STAGE/anki-gen"
cp -R "$HERE/image-vision" "$STAGE/image-vision"
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '.DS_Store' -delete 2>/dev/null || true
for name in anki-gen image-vision; do
  if [ ! -f "$STAGE/$name/SKILL.md" ]; then
    echo "Install check failed: $name/SKILL.md missing after copy" >&2
    exit 1
  fi
done

# Do not replace a skill with itself (running from the installed tree).
for name in anki-gen image-vision; do
  if [ "$(cd "$HERE/$name" && pwd -P)" = "$(cd "$DEST/$name" 2>/dev/null && pwd -P)" ]; then
    echo "Refusing to install $name onto itself: $DEST/$name" >&2
    exit 1
  fi
done

if [ -e "$DEST/anki-gen" ] || [ -e "$DEST/image-vision" ]; then
  BACKUP="$DEST/.backups/anki-gen-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$BACKUP"
  for name in anki-gen image-vision; do
    [ -e "$DEST/$name" ] && mv "$DEST/$name" "$BACKUP/$name"
  done
  echo "Backup: $BACKUP"
fi

for name in anki-gen image-vision; do
  mv "$STAGE/$name" "$DEST/$name"
  echo "Installed $name  ->  $DEST/$name"
done

echo
echo "anki-gen $OLD_VERSION -> $NEW_VERSION"
echo "User config and keys in ~/.config/anki-gen were not touched."
echo
echo "Next:"
echo "  1. Restart/reload opencode so it discovers the skills."
echo "  2. Run the platform setup:"
echo "       bash $DEST/anki-gen/scripts/setup.sh"
echo "  3. Run the doctor from Terminal and from inside opencode:"
echo "       python3 $DEST/anki-gen/scripts/doctor.py"
echo "  4. Install the Anki desktop app separately; import the .apkg manually."
