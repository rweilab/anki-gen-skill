#!/usr/bin/env bash
# Cross-platform setup: install core Python libraries, then best-effort feature
# support. Missing optional tools or wheels never abort the skill install.
# Homebrew and Anki are never installed.
# Run: bash scripts/setup.sh [--print-only]
set -euo pipefail

# Directory containing this script, and the skill root above it.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
CORE_REQ="$ROOT/requirements.txt"
OPT_REQ="$ROOT/requirements-optional.txt"
PRINT_ONLY=0
if [ "${1:-}" = "--print-only" ]; then
  PRINT_ONLY=1
fi
# A curl-launched shell may not have Homebrew on PATH yet.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

# Linux fallback binaries for whisper.cpp. The package manager path is first;
# this tarball is used only when the distro has no package.
WHISPER_VERSION="1.9.5"
WHISPER_TARBALL_TAG="b5454"
WHISPER_SHA_X64="a72becf15d7917f990f6313867a52638b82b7f9ef237fb0c980dac56a135781c"
WHISPER_SHA_ARM64="6b95ebfc60447df48e70ef00a73bdc3f41679ed2d01ef465827206a2ff325149"

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
  macos)  PY_PKG=python;  PIP_PKG="";          POPPLER=poppler;       TESSERACT=tesseract; WHISPER_PKG=whisper.cpp ;;
  debian) PY_PKG=python3; PIP_PKG=python3-pip; POPPLER=poppler-utils; TESSERACT=tesseract-ocr; WHISPER_PKG=whisper.cpp-tools ;;
  fedora) PY_PKG=python3; PIP_PKG=python3-pip; POPPLER=poppler-utils; TESSERACT=tesseract; WHISPER_PKG=whisper-cpp ;;
  arch)   PY_PKG=python;  PIP_PKG=python-pip;  POPPLER=poppler;       TESSERACT=tesseract; WHISPER_PKG=whisper-cpp ;;
  *)      PY_PKG=python3; PIP_PKG="";          POPPLER="";            TESSERACT=""; WHISPER_PKG="" ;;
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
  echo "System packages (best effort):"
  if [ -n "$PKGS" ]; then
    for pkg in $PKGS; do echo "  $pkg"; done
  else
    echo "  none missing"
  fi
  if [ -n "$WHISPER_PKG" ]; then
    if [ "$OS" = "macos" ] && [ "$(uname -m)" = "arm64" ]; then
      echo "  $WHISPER_PKG (Apple Silicon full-feature path)"
    else
      echo "  $WHISPER_PKG (only if faster-whisper is unavailable)"
    fi
  fi
  echo
  echo "Core Python libraries:"
  echo "  PIP_BREAK_SYSTEM_PACKAGES=1 python3 -m pip install --user -r \"$CORE_REQ\""
  echo
  echo "Optional Python libraries (best effort, one at a time):"
  echo "  install each non-comment line in \"$OPT_REQ\" with:"
  echo "    PIP_BREAK_SYSTEM_PACKAGES=1 python3 -m pip install --user --only-binary=:all: <requirement>"
  echo
  echo "Local transcription:"
  echo "  faster-whisper when importable; otherwise whisper.cpp."
  echo "  The whisper.cpp model downloads on first use (~142 MB)."
  exit 0
fi

SUDO=""
if [ "$EUID" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    SUDO="__missing__"
  fi
fi

try_pkg() {
  pkg="$1"
  if [ "$OS" = "macos" ]; then
    command -v brew >/dev/null 2>&1 || return 1
    if brew list --formula "$pkg" >/dev/null 2>&1; then return 0; fi
    brew install "$pkg"
    return $?
  fi
  [ "$SUDO" != "__missing__" ] || return 1
  case "$OS" in
    debian) $SUDO apt-get install -y "$pkg" ;;
    fedora) $SUDO dnf install -y "$pkg" ;;
    arch)   $SUDO pacman -S --noconfirm --needed "$pkg" ;;
    *)      return 1 ;;
  esac
}

if [ -n "$PKGS" ]; then
  echo "Installing missing system packages (best effort)..."
  if [ "$OS" = "macos" ] && ! command -v brew >/dev/null 2>&1; then
    echo "warn: Homebrew not found; skipping system packages. Core Python can still work." >&2
  elif [ "$OS" != "macos" ] && [ "$SUDO" = "__missing__" ]; then
    echo "warn: sudo not available; skipping system packages. Core Python can still work." >&2
  else
    if [ "$OS" = "debian" ]; then
      $SUDO apt-get update || true
    fi
    for pkg in $PKGS; do
      if ! try_pkg "$pkg"; then
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
  echo "warn: python3 not found. Install Python 3.10+ and re-run setup." >&2
  exit 1
fi
if ! "$PY" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit(f"Python 3.10+ required; found {sys.version.split()[0]}")
print("Python", sys.version.split()[0])
PY
then
  exit 1
fi

if ! "$PY" -m pip --version >/dev/null 2>&1; then
  echo "pip missing; trying ensurepip..."
  "$PY" -m ensurepip --user >/dev/null 2>&1 || true
fi

CORE_OK=1
echo
echo "Installing core Python libraries..."
# The env var bypasses PEP 668 on new pip and is ignored by old pip.
if ! PIP_BREAK_SYSTEM_PACKAGES=1 "$PY" -m pip install --user -r "$CORE_REQ"; then
  cat >&2 <<TXT

Core pip install failed. Try a venv instead:
  python3 -m venv "$HOME/.local/share/anki-gen/venv"
  "$HOME/.local/share/anki-gen/venv/bin/python" -m pip install -r "$CORE_REQ"
Then launch opencode from a terminal with that venv activated, or ask a maintainer.
TXT
fi

STT_STATUS="off"
if [ -f "$OPT_REQ" ]; then
  echo
  echo "Installing optional Python libraries (best effort)..."
  while IFS= read -r req; do
    case "$req" in ""|\#*) continue ;; esac
    if ! PIP_BREAK_SYSTEM_PACKAGES=1 "$PY" -m pip install --user \
        --only-binary=:all: "$req"; then
      echo "warn: optional dependency not installed: $req" >&2
    fi
  done < "$OPT_REQ"
fi
if "$PY" -c 'import faster_whisper' >/dev/null 2>&1; then
  STT_STATUS="faster-whisper"
fi

whisper_cli() {
  command -v whisper-cli >/dev/null 2>&1 || command -v whisper-cpp >/dev/null 2>&1
}

install_whisper_tarball() {
  [ "$OS" = "macos" ] && return 1
  case "$(uname -m)" in
    x86_64|amd64) arch=x64; sha="$WHISPER_SHA_X64" ;;
    aarch64|arm64) arch=arm64; sha="$WHISPER_SHA_ARM64" ;;
    *) return 1 ;;
  esac
  command -v curl >/dev/null 2>&1 || return 1
  command -v tar >/dev/null 2>&1 || return 1
  dest="$HOME/.local/share/anki-gen/whisper.cpp/$WHISPER_VERSION"
  if [ -x "$dest/whisper-cli" ]; then return 0; fi
  tmp="$(mktemp -d "${TMPDIR:-/tmp}/anki-whisper.XXXXXX")"
  url="https://github.com/ggml-org/whisper.cpp/releases/download/$WHISPER_TARBALL_TAG/whisper-bin-ubuntu-$arch.tar.gz"
  echo "Downloading whisper.cpp fallback..."
  if ! curl -fL --retry 2 -o "$tmp/whisper.tar.gz" "$url"; then
    rm -rf "$tmp"; return 1
  fi
  actual="$("$PY" - "$tmp/whisper.tar.gz" <<'PY'
import hashlib, sys
print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())
PY
)"
  if [ "$actual" != "$sha" ]; then
    echo "warn: whisper.cpp checksum mismatch" >&2
    rm -rf "$tmp"; return 1
  fi
  mkdir -p "$tmp/unpack"
  if ! tar -xzf "$tmp/whisper.tar.gz" -C "$tmp/unpack"; then
    rm -rf "$tmp"; return 1
  fi
  src="$tmp/unpack/whisper-bin-ubuntu-$arch"
  if [ ! -x "$src/whisper-cli" ]; then
    rm -rf "$tmp"; return 1
  fi
  rm -rf "$dest"
  mkdir -p "$dest"
  cp -R "$src"/. "$dest"/
  if ! LD_LIBRARY_PATH="$dest" "$dest/whisper-cli" --help >/dev/null 2>&1; then
    echo "warn: whisper.cpp binary cannot run on this system" >&2
    rm -rf "$dest" "$tmp"; return 1
  fi
  ln -sfn "$dest" "$HOME/.local/share/anki-gen/whisper.cpp/current"
  rm -rf "$tmp"
  return 0
}

install_whisper_cpp() {
  whisper_cli && return 0
  if [ -n "$WHISPER_PKG" ] && try_pkg "$WHISPER_PKG" && whisper_cli; then
    return 0
  fi
  install_whisper_tarball
}

if [ "$OS" = "macos" ] && [ "$(uname -m)" = "arm64" ]; then
  if ! whisper_cli; then
    echo "Installing whisper.cpp (full local transcription on Apple Silicon)..."
    install_whisper_cpp || echo "warn: whisper.cpp not installed; local transcription is off" >&2
  fi
elif [ "$STT_STATUS" != "faster-whisper" ]; then
  echo "faster-whisper unavailable; trying whisper.cpp..."
  install_whisper_cpp || echo "warn: whisper.cpp not installed; local transcription is off" >&2
fi

DOCTOR_LOG="${TMPDIR:-/tmp}/anki-gen-doctor.log"
if "$PY" "$ROOT/scripts/doctor.py" >"$DOCTOR_LOG" 2>&1; then
  echo "Core text path is ready."
  GAPS="$(grep '^warn ' "$DOCTOR_LOG" || true)"
  LOCAL="$(grep '^Local transcription:' "$DOCTOR_LOG" || true)"
  if [ -n "$GAPS" ]; then
    echo "Full feature set: NOT installed. Optional gaps:"
    printf '%s\n' "$GAPS" | sed 's/^warn  */  /'
    echo "Core decks still work. Run doctor for fixes."
  else
    echo "Full feature set: installed."
  fi
  if [ -n "$LOCAL" ]; then
    printf '%s\n' "$LOCAL"
  fi
else
  cat "$DOCTOR_LOG" >&2
  echo "Doctor found a core problem; details above. Log: $DOCTOR_LOG" >&2
  CORE_OK=0
fi

echo
if [ "$CORE_OK" = "1" ]; then
  echo "Setup complete. Restart/reload opencode so it discovers the skills."
  exit 0
fi
echo "Setup incomplete: the skill is installed, but the core path is not ready."
exit 1
