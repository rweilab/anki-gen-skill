#!/usr/bin/env bash
# Cross-platform setup: install Python libraries, print system package commands.
# Never runs sudo. Run: bash scripts/setup.sh [--print-only]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
PRINT_ONLY=0
[ "${1:-}" = "--print-only" ] && PRINT_ONLY=1

os_id() {
  if [ "$(uname -s)" = "Darwin" ]; then echo macos; return; fi
  if [ -r /etc/os-release ]; then
    . /etc/os-release
    case "${ID:-}" in
      ubuntu|debian|linuxmint|pop) echo debian ;;
      fedora|rhel|centos) echo fedora ;;
      arch|manjaro) echo arch ;;
      *) echo linux ;;
    esac
  else
    echo linux
  fi
}
OS="$(os_id)"

echo "anki-gen setup — $OS"
echo
case "$OS" in
  macos)
    cat <<'TXT'
System packages (run these yourself; this script does not use sudo):
  brew install python poppler ffmpeg tesseract
Optional: brew install pandoc ghostscript
Anki desktop app: brew install --cask anki
TXT
    ;;
  debian)
    cat <<'TXT'
System packages (run these yourself; this script does not use sudo):
  sudo apt install python3 python3-pip python3-venv poppler-utils ffmpeg tesseract-ocr
Optional: sudo apt install pandoc ghostscript
Anki desktop app: use the official AppImage or Flathub; import the .apkg manually.
TXT
    ;;
  fedora)
    cat <<'TXT'
System packages (run these yourself; this script does not use sudo):
  sudo dnf install python3 python3-pip poppler-utils ffmpeg tesseract
  # ffmpeg may need RPM Fusion on Fedora:
  # https://rpmfusion.org/Configuration
Optional: sudo dnf install pandoc ghostscript
Anki desktop app: use the official AppImage or Flathub; import the .apkg manually.
TXT
    ;;
  arch)
    cat <<'TXT'
System packages (run these yourself; this script does not use sudo):
  sudo pacman -S python python-pip poppler ffmpeg tesseract
Optional: sudo pacman -S pandoc ghostscript
Anki desktop app: install the official package/AUR and import the .apkg manually.
TXT
    ;;
  *)
    cat <<'TXT'
Install Python 3.10+, poppler/pdftotext, ffmpeg, and tesseract with your system
package manager. Install Anki desktop separately for manual .apkg import.
TXT
    ;;
esac

echo
PY="python3"
if [ "$OS" = "macos" ] && command -v brew >/dev/null 2>&1; then
  BREW_PY="$(brew --prefix)/bin/python3"
  if [ -x "$BREW_PY" ]; then PY="$BREW_PY"; fi
fi
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "python3 not found. Install Python 3.10+ first." >&2
  exit 1
fi
"$PY" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(f"Python 3.10+ required; found {sys.version.split()[0]}")
print("Python", sys.version.split()[0])
PY

echo
echo "Python libraries:"
echo "  $PY -m pip install --user --break-system-packages -r \"$ROOT/requirements.txt\""
if [ "$PRINT_ONLY" = "1" ]; then
  echo "Print-only mode: not installing Python libraries."
  exit 0
fi
if ! "$PY" -m pip install --user --break-system-packages -r "$ROOT/requirements.txt"; then
  cat >&2 <<TXT

pip install failed. Try a venv instead:
  python3 -m venv "$HOME/.local/share/anki-gen/venv"
  "$HOME/.local/share/anki-gen/venv/bin/python" -m pip install -r "$ROOT/requirements.txt"
Then launch opencode from a terminal with that venv activated, or ask a maintainer.
TXT
  exit 1
fi

echo
echo "Python libraries installed. Next:"
echo "  $PY $ROOT/scripts/doctor.py"
echo "  restart/reload opencode"
echo "  install Anki desktop separately; import the .apkg manually"
