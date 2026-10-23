#!/usr/bin/env bash
# One-command entry point. It does three things, in order:
#   1. download the GitHub archive for $ANKI_GEN_BRANCH (default: main)
#   2. extract it to a temporary directory
#   3. run install.sh, which copies the skills, moves old discoverable backups
#      out of ~/.claude/skills, and calls setup.sh (including faster-whisper
#      for local video/audio; models download on first transcription)
# AnkiConnect is a separate add-on inside Anki Desktop and is installed later,
# only when revising an imported deck.
# setup.sh is the only script that installs packages; install.sh --no-setup
# skips it. Both are plain bash and can be read before running this.
set -euo pipefail

REPO="${ANKI_GEN_REPO:-rweilab/anki-gen-skill}"
BRANCH="${ANKI_GEN_BRANCH:-main}"
TMP="$(mktemp -d)"
# Remove the temporary download on exit.
trap 'rm -rf "$TMP"' EXIT

URL="https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"
echo "Downloading ${REPO} (${BRANCH})..."
curl -fsSL "$URL" -o "$TMP/src.tar.gz"
tar -xzf "$TMP/src.tar.gz" -C "$TMP"
# GitHub names the archive root "<repo>-<branch>".
REPO_NAME="$(basename "$REPO")"
SRC="$TMP/$REPO_NAME-$BRANCH"

if [ ! -d "$SRC" ]; then
  echo "Downloaded archive did not contain $SRC" >&2
  exit 1
fi

bash "$SRC/install.sh" "$@"
