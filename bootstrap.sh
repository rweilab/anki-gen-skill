#!/usr/bin/env bash
# Download the repo archive and run the installer without requiring Git.
set -euo pipefail

REPO="${ANKI_GEN_REPO:-rweilab/anki-gen-skill}"
BRANCH="${ANKI_GEN_BRANCH:-main}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

URL="https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"
echo "Downloading ${REPO} (${BRANCH})..."
curl -fsSL "$URL" -o "$TMP/src.tar.gz"
tar -xzf "$TMP/src.tar.gz" -C "$TMP"
SRC="$TMP/$(basename "$REPO")-${BRANCH}"

if [ ! -d "$SRC" ]; then
  echo "Downloaded archive did not contain $SRC" >&2
  exit 1
fi

cd "$SRC"
bash install.sh
