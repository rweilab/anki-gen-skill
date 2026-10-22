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
SKILLS_PARENT="$(dirname "$SKILL_DIR")"              # .../skills
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
cp "$SCRIPT_DIR/handoff/install.sh" "$STAGE/install.sh"
cp "$SCRIPT_DIR/handoff/INSTALL.md" "$STAGE/INSTALL.md"
cp "$SKILL_DIR/VERSION" "$STAGE/VERSION"
chmod +x "$STAGE/install.sh"

# No junk, no secrets, no scratch.
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '.DS_Store' -delete 2>/dev/null || true
find "$STAGE" -name '*.bak' -delete 2>/dev/null || true
find "$STAGE" -name '.backup*' -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '.anki-gen-temp' -prune -exec rm -rf {} + 2>/dev/null || true

for f in anki-gen/SKILL.md image-vision/SKILL.md \
         image-vision/scripts/vision_check.py \
         anki-gen/assets/mathjax/tex-svg.js anki-gen/VERSION \
         anki-gen/requirements.txt anki-gen/scripts/setup.sh \
         anki-gen/scripts/setup_macos.sh anki-gen/scripts/doctor.py \
         anki-gen/scripts/visual.py anki-gen/scripts/ytdlp.py \
         anki-gen/scripts/extract_slides.py anki-gen/scripts/media_transcribe.py \
         anki-gen/scripts/preflight.py anki-gen/scripts/pipeline.py \
         anki-gen/scripts/platform_paths.py anki-gen/scripts/anki_connect.py \
         anki-gen/scripts/deck_context.py anki-gen/scripts/revision.py \
         anki-gen/references/slides.md anki-gen/references/revision.md \
         anki-gen/scripts/handoff/install.sh anki-gen/HANDOFF.md \
         anki-gen/AGENTS.md install.sh INSTALL.md VERSION; do
  if [ ! -f "$STAGE/$f" ]; then
    echo "Packaging check failed: missing $f" >&2
    exit 1
  fi
done

if [ "$CHECK" = "1" ]; then
  echo "package check ok: both skills, installer, setup, doctor, docs, VERSION"
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
