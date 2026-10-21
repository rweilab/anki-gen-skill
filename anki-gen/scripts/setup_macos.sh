#!/usr/bin/env bash
# Backward-compatible entry point. The cross-platform setup lives in setup.sh.
exec bash "$(dirname "${BASH_SOURCE[0]}")/setup.sh" "$@"
