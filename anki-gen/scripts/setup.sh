#!/usr/bin/env bash
# Cross-platform setup: install missing system tools and Python libraries, then
# run the doctor. Homebrew and Anki are never installed.
# Run: bash scripts/setup.sh [--print-only]
set -euo pipefail

# Directory containing this script, and the skill root above it.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
PRINT_ONLY=0
if [ "${1:-}" = "--print-only" ]; then
  PRINT_ONLY=1
fi
# A curl-launched shell may not have Homebrew on PATH yet.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

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

# Space-separated package list: works on macOS's bash 3.2 without arrays.
PKGS=""
add_pkg() { PKGS="$PKGS $1"; }

# Package names differ by OS. Empty POPPLER means an unknown Linux: do not guess.
case "$OS" in
  macos)  PY_PKG=python;  PIP_PKG="";          POPPLER=poppler;       TESSERACT=tesseract ;;
  debian) PY_PKG=python3; PIP_PKG=python3-pip; POPPLER=poppler-utils; TESSERACT=tesseract-ocr ;;
  fedora) PY_PKG=python3; PIP_PKG=python3-pip; POPPLER=poppler-utils; TESSERACT=tesseract ;;
  arch)   PY_PKG=python;  PIP_PKG=python-pip;  POPPLER=poppler;       TESSERACT=tesseract ;;
  *)      PY_PKG=python3; PIP_PKG="";          POPPLER="";            TESSERACT="" ;;
esac

# On macOS, /usr/bin/python3 is a stub until the Xcode command-line tools exist.
has_python310() {
  command -v python3 >/dev/null 2>&1 || return 1
  if [ "$OS" = "macos" ] && ! xcode-select -p >/dev/null 2>&1; then
    return 1
  fi
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null
}
has_python310 || add_pkg "$PY_PKG"

# pip is a separate package on some Linux distributions.
if [ -n "$PIP_PKG" ] && ! python3 -m pip --version >/dev/null 2>&1; then
  add_pkg "$PIP_PKG"
fi

check_tool() {
  command -v "$1" >/dev/null 2>&1 || add_pkg "$2"
}
if [ -n "$POPPLER" ]; then
  check_tool pdftotext "$POPPLER"
  check_tool pandoc pandoc
  check_tool gs ghostscript
  check_tool mutool mupdf-tools
  check_tool ffmpeg ffmpeg
  check_tool tesseract "$TESSERACT"
fi

echo "anki-gen setup — $OS"
echo

if [ "$PRINT_ONLY" = "1" ]; then
  echo "System packages:"
  if [ -n "$PKGS" ]; then
    for pkg in $PKGS; do echo "  $pkg"; done
  else
    echo "  none missing"
  fi
  echo
  echo "Python libraries:"
  echo "  PIP_BREAK_SYSTEM_PACKAGES=1 python3 -m pip install --user -r \"$ROOT/requirements.txt\""
  exit 0
fi

if [ -n "$PKGS" ]; then
  echo "Installing missing system packages..."
  if [ "$OS" = "macos" ]; then
    if ! command -v brew >/dev/null 2>&1; then
      cat >&2 <<'TXT'
Homebrew is required to install the missing tools. Install it yourself with:
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
Then re-run the install command. This installer never installs Homebrew.
TXT
      exit 1
    fi
    for pkg in $PKGS; do
      if ! brew list --formula "$pkg" >/dev/null 2>&1; then
        brew install "$pkg" || echo "warn: brew install $pkg failed" >&2
      fi
    done
  else
    SUDO=""
    if [ "$EUID" -ne 0 ]; then
      if ! command -v sudo >/dev/null 2>&1; then
        echo "sudo is required to install system packages; install them yourself." >&2
        exit 1
      fi
      SUDO="sudo"   # empty when the script is already running as root
    fi
    install_system_pkg() {
      case "$OS" in
        debian) $SUDO apt-get install -y "$1" ;;
        fedora) $SUDO dnf install -y "$1" ;;
        arch)   $SUDO pacman -S --noconfirm --needed "$1" ;;
        *)      return 1 ;;
      esac
    }
    if [ "$OS" = "debian" ]; then
      $SUDO apt-get update || true
    fi
    for pkg in $PKGS; do
      if ! install_system_pkg "$pkg"; then
        echo "warn: could not install $pkg" >&2
      fi
    done
  fi
  echo
fi

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
echo "Installing Python libraries..."
# The env var bypasses PEP 668 on new pip and is ignored by old pip.
if ! PIP_BREAK_SYSTEM_PACKAGES=1 "$PY" -m pip install --user -r "$ROOT/requirements.txt"; then
  cat >&2 <<TXT

pip install failed. Try a venv instead:
  python3 -m venv "$HOME/.local/share/anki-gen/venv"
  "$HOME/.local/share/anki-gen/venv/bin/python" -m pip install -r "$ROOT/requirements.txt"
Then launch opencode from a terminal with that venv activated, or ask a maintainer.
TXT
  exit 1
fi

echo
DOCTOR_LOG="${TMPDIR:-/tmp}/anki-gen-doctor.log"
if "$PY" "$ROOT/scripts/doctor.py" >"$DOCTOR_LOG" 2>&1; then
  echo "Doctor: core text path is ready."
else
  cat "$DOCTOR_LOG" >&2
  echo "Doctor found a problem; details above. Log: $DOCTOR_LOG" >&2
  exit 1
fi
echo
echo "Setup complete. Restart/reload opencode so it discovers the skills."
