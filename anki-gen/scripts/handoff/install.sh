#!/usr/bin/env bash
# Install or upgrade anki-gen + image-vision into ~/.claude/skills/.
# Safe upgrade: stage, verify, back up the old directories, then replace.
# After the copy it runs setup.sh (packages + doctor) unless --no-setup is given.
set -euo pipefail

# Directory containing this script, and the skills directory it installs into.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${ANKI_GEN_SKILLS_DIR:-$HOME/.claude/skills}"
BACKUP_ROOT="${ANKI_GEN_BACKUP_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/anki-gen/backups}"
NEW_VERSION="$(cat "$HERE/anki-gen/VERSION" 2>/dev/null || echo unknown)"
OLD_VERSION="$(cat "$DEST/anki-gen/VERSION" 2>/dev/null || echo none)"
STAGE=""
BACKUP=""

cleanup() {
  if [ -n "$STAGE" ]; then
    rm -rf "$STAGE"
  fi
  # Remove the backup directory only if it stayed empty (rmdir refuses non-empty).
  if [ -n "$BACKUP" ]; then
    rmdir "$BACKUP" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [ "${1:-}" = "--version" ]; then
  echo "anki-gen $NEW_VERSION"
  exit 0
fi
NO_SETUP=0
if [ "${1:-}" = "--no-setup" ]; then
  NO_SETUP=1
fi

if [ ! -f "$HERE/anki-gen/SKILL.md" ] || [ ! -f "$HERE/image-vision/SKILL.md" ]; then
  echo "Missing anki-gen/ or image-vision/ next to install.sh — re-extract the zip." >&2
  exit 1
fi

mkdir -p "$DEST"

# Backups used to live under ~/.claude/skills/.backups, where skill discovery
# could load an old SKILL.md. Move them out and make them non-discoverable.
if [ -d "$DEST/.backups" ]; then
  mkdir -p "$BACKUP_ROOT"
  for old in "$DEST"/.backups/*; do
    [ -e "$old" ] || continue
    target="$BACKUP_ROOT/legacy-$(basename "$old")"
    if [ -e "$target" ]; then target="$target-$(date +%s)"; fi
    mv "$old" "$target"
    find "$target" -name 'SKILL.md' -type f -exec mv {} {}.bak \; 2>/dev/null || true
  done
  rmdir "$DEST/.backups" 2>/dev/null || true
  echo "Moved legacy backups to $BACKUP_ROOT"
fi

STAGE="$(mktemp -d "$DEST/.anki-install.XXXXXX")"
cp -R "$HERE/anki-gen" "$STAGE/anki-gen"
cp -R "$HERE/image-vision" "$STAGE/image-vision"
# Drop editor/OS junk from the staged copy.
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '.DS_Store' -delete 2>/dev/null || true
for name in anki-gen image-vision; do
  if [ ! -f "$STAGE/$name/SKILL.md" ]; then
    echo "Install check failed: $name/SKILL.md missing after copy" >&2
    exit 1
  fi
done

# Do not replace a skill with itself (running from the installed tree).
# -ef is true when both paths point at the same directory, even through a symlink.
for name in anki-gen image-vision; do
  if [ "$HERE/$name" -ef "$DEST/$name" ]; then
    echo "Refusing to install $name onto itself: $DEST/$name" >&2
    exit 1
  fi
done

# Keep the old install as a timestamped backup before replacing it.
if [ -e "$DEST/anki-gen" ] || [ -e "$DEST/image-vision" ]; then
  BACKUP="$BACKUP_ROOT/anki-gen-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$BACKUP"
  for name in anki-gen image-vision; do
    if [ -e "$DEST/$name" ]; then
      mv "$DEST/$name" "$BACKUP/$name"
    fi
  done
  # Defence in depth: a backup under the skills tree is not a loadable skill.
  find "$BACKUP" -name 'SKILL.md' -type f -exec mv {} {}.bak \; 2>/dev/null || true
  echo "Backup: $BACKUP"
fi

for name in anki-gen image-vision; do
  mv "$STAGE/$name" "$DEST/$name"
  echo "Installed $name  ->  $DEST/$name"
done

echo
echo "anki-gen $OLD_VERSION -> $NEW_VERSION"
echo "User config and keys in ~/.config/anki-gen were not touched."
if [ "$NO_SETUP" = "1" ]; then
  echo "Skipped dependency setup (--no-setup)."
else
  echo
  bash "$DEST/anki-gen/scripts/setup.sh"
fi
echo
echo "Done. Restart/reload opencode so it discovers the skills."
