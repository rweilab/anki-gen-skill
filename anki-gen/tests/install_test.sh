#!/usr/bin/env bash
# Offline installer/upgrade test. Builds a fake handoff folder, never a zip.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS="$(dirname "$ROOT")"
W="$(mktemp -d "${TMPDIR:-/tmp}/anki-install-test.XXXXXX")"
trap 'rm -rf "$W"' EXIT
mkdir -p "$W/stage" "$W/home/.config/anki-gen" "$W/home/.claude/skills"
cp -R "$ROOT" "$W/stage/anki-gen"
cp -R "$SKILLS/image-vision" "$W/stage/image-vision"
cp "$ROOT/scripts/handoff/install.sh" "$W/stage/install.sh"
cp "$ROOT/scripts/handoff/INSTALL.md" "$W/stage/INSTALL.md"
cp "$ROOT/VERSION" "$W/stage/VERSION"
printf 'test-key\n' > "$W/home/.config/anki-gen/gemini.key"

run_install() {
  HOME="$W/home" ANKI_GEN_SKILLS_DIR="$W/home/.claude/skills" \
    bash "$W/stage/install.sh" --no-setup >/dev/null
}
run_install
test -f "$W/home/.claude/skills/anki-gen/SKILL.md" || exit 1
test -f "$W/home/.claude/skills/image-vision/SKILL.md" || exit 1
test "$(cat "$W/home/.claude/skills/anki-gen/VERSION")" = "$(cat "$ROOT/VERSION")" || exit 1
run_install
test "$(cat "$W/home/.config/anki-gen/gemini.key")" = "test-key" || exit 1
ls -d "$W/home/.claude/skills"/.backups/anki-gen-* >/dev/null || exit 1
echo "ok    installer/upgrade"
