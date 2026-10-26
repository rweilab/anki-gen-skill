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
cp "$SKILLS/install.sh" "$W/stage/install.sh"
cp "$SKILLS/README.md" "$W/stage/INSTALL.md"
cp "$ROOT/VERSION" "$W/stage/VERSION"
printf 'test-key\n' > "$W/home/.config/anki-gen/gemini.key"
# Simulate an old discoverable backup under the skills tree.
mkdir -p "$W/home/.claude/skills/.backups/anki-gen"
printf 'name: anki-gen\n' > "$W/home/.claude/skills/.backups/anki-gen/SKILL.md"

run_install() {
  HOME="$W/home" ANKI_GEN_SKILLS_DIR="$W/home/.claude/skills" \
    bash "$W/stage/install.sh" --no-setup >/dev/null
}
grep -q '^faster-whisper' "$W/stage/anki-gen/requirements-optional.txt" || exit 1
! grep -q '^faster-whisper' "$W/stage/anki-gen/requirements.txt" || exit 1
grep -q 'requirements-optional.txt' "$W/stage/anki-gen/scripts/setup.sh" || exit 1
grep -q 'Full feature set' "$W/stage/anki-gen/scripts/setup.sh" || exit 1
bash "$W/stage/anki-gen/scripts/setup.sh" --print-only > "$W/print-only.txt"
grep -q 'requirements-optional.txt' "$W/print-only.txt" || exit 1
run_install
test -f "$W/home/.claude/skills/anki-gen/SKILL.md" || exit 1
test -f "$W/home/.local/share/anki-gen/backups/legacy-anki-gen/SKILL.md.bak" || exit 1
test ! -e "$W/home/.claude/skills/.backups/anki-gen/SKILL.md" || exit 1
test -f "$W/home/.claude/skills/image-vision/SKILL.md" || exit 1
test "$(cat "$W/home/.claude/skills/anki-gen/VERSION")" = "$(cat "$ROOT/VERSION")" || exit 1
run_install
test "$(cat "$W/home/.config/anki-gen/gemini.key")" = "test-key" || exit 1
ls -d "$W/home/.local/share/anki-gen/backups"/anki-gen-* >/dev/null || exit 1
if find "$W/home/.local/share/anki-gen/backups" -name SKILL.md | grep -q .; then exit 1; fi
echo "ok    installer/upgrade"

# A setup failure must still leave the skill installed and must not abort install.sh.
printf '#!/usr/bin/env bash\nexit 1\n' > "$W/stage/anki-gen/scripts/setup.sh"
HOME="$W/home" ANKI_GEN_SKILLS_DIR="$W/home/.claude/skills" \
  bash "$W/stage/install.sh" > "$W/setup-fail.log" 2>&1
grep -q "setup is incomplete" "$W/setup-fail.log" || exit 1
test -f "$W/home/.claude/skills/anki-gen/SKILL.md" || exit 1
echo "ok    installer survives setup failure"
