"""Resolve Homebrew tools when opencode is launched outside a terminal.

macOS GUI apps often inherit a minimal PATH. Prepending the two standard
Homebrew bin directories costs nothing on other platforms and keeps the
declared ffmpeg/poppler tools discoverable.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_tool_paths() -> None:
    if sys.platform != "darwin":
        return
    current = os.environ.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    missing = [c for c in ("/opt/homebrew/bin", "/usr/local/bin")
               if Path(c).is_dir() and c not in parts]
    if missing:
        os.environ["PATH"] = os.pathsep.join(missing + parts)
