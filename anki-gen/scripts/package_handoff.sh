#!/usr/bin/env bash
# Build the handoff zip: both skills + install.sh + INSTALL.md at the zip root.
#
#   bash scripts/package_handoff.sh [output.zip]
#   bash scripts/package_handoff.sh --check   # stage + verify, build no zip
#   default output: ~/Downloads/anki-gen-handoff.zip
#
# The handoff person runs this; the Mac user just downloads the zip and asks
# opencode to install it. No secrets, no test decks, no backups in the zip.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"                 # .../anki-gen
SKILLS_PARENT="$(dirname "$SKILL_DIR")"              # repo root (contains image-vision/, install.sh)
CHECK=0
if [ "${1:-}" = "--check" ]; then CHECK=1; shift; fi
OUT="${1:-$HOME/Downloads/anki-gen-handoff.zip}"

if [ ! -d "$SKILLS_PARENT/image-vision" ]; then
  echo "image-vision not found at $SKILLS_PARENT/image-vision" >&2
  echo "Keep both skills side by side before packaging." >&2
  exit 1
fi

STAGE="$(mktemp -d "${TMPDIR:-/tmp}/anki-gen-handoff.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT

cp -R "$SKILL_DIR" "$STAGE/anki-gen"
cp -R "$SKILLS_PARENT/image-vision" "$STAGE/image-vision"
cp "$SKILLS_PARENT/install.sh" "$STAGE/install.sh"
cp "$SKILLS_PARENT/README.md" "$STAGE/INSTALL.md"
cp "$SKILL_DIR/VERSION" "$STAGE/VERSION"
chmod +x "$STAGE/install.sh"

# No junk, no secrets, no scratch.
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '.DS_Store' -delete 2>/dev/null || true
find "$STAGE" -name '*.bak' -delete 2>/dev/null || true
find "$STAGE" -name '.backup*' -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '.anki-gen-temp' -prune -exec rm -rf {} + 2>/dev/null || true

for f in anki-gen/SKILL.md image-vision/SKILL.md install.sh INSTALL.md VERSION \
         anki-gen/AGENTS.md anki-gen/MAINTAINERS.md \
         anki-gen/maintainers/lessons.md anki-gen/maintainers/dossier-format.md; do
  if [ ! -f "$STAGE/$f" ]; then
    echo "Packaging check failed: missing $f" >&2
    exit 1
  fi
done

junk="$(find "$STAGE" \( -name '__pycache__' -o -name '.DS_Store' -o -name '*.bak' \
     -o -name '.anki-gen-temp' -o -name '.git' \) -print)"
if [ -n "$junk" ]; then
  echo "Packaging check failed: junk or work files in stage" >&2
  exit 1
fi
secrets="$(find "$STAGE" -type f \( -name '*.key' -o -name 'gemini.key' \
     -o -name '.env' -o -name '.env.*' \) -print)"
if [ -n "$secrets" ]; then
  echo "Packaging check failed: secret-looking file in stage" >&2
  exit 1
fi

if [ "$CHECK" = "1" ]; then
  echo "package check ok: both skills, installer, docs, VERSION"
  exit 0
fi

mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"
# Python's zipfile, not the `zip` binary: Python is already a hard requirement,
# and this keeps the packaging identical on macOS and Linux.
PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "python3 is required to build the zip" >&2
  exit 1
fi
"$PY" - "$STAGE" "$OUT" <<'PY'
import sys, zipfile
from pathlib import Path
stage, out = Path(sys.argv[1]), Path(sys.argv[2])
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted(stage.rglob("*")):
        if p.is_file():
            z.write(p, p.relative_to(stage).as_posix())
print(f"Wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")
PY
