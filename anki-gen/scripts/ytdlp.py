#!/usr/bin/env python3
"""Run the yt-dlp installed in this Python environment.

A system `yt-dlp` on PATH can be a different install, without the EJS scripts
or Deno binary that `pip install "yt-dlp[default,deno]"` puts beside it. Going
through `sys.executable -m yt_dlp` keeps the command and its extras together.
The Deno path is explicit because pip's user-script directory is not always on
PATH.
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import site
import subprocess
import sys
import sysconfig
import time
from functools import lru_cache
from pathlib import Path

from platform_paths import ensure_tool_paths
ensure_tool_paths()

# Bound yt-dlp's own retry loop so it cannot sit for minutes.
RETRY_ARGS = ("--retries", "2", "--extractor-retries", "2",
              "--fragment-retries", "2")
TRANSIENT = re.compile(
    r"http error (?:429|5\d\d)|too many requests|temporar|timed out|timeout|"
    r"connection (?:reset|aborted|refused)|network is unreachable|"
    r"temporary failure in name resolution", re.I)
DELAYS = (2, 4, 8)


def deno_path() -> Path | None:
    candidates = []
    found = shutil.which("deno")
    if found:
        candidates.append(Path(found))
    candidates.append(Path(sysconfig.get_path("scripts")) / "deno")
    candidates.append(Path(site.getuserbase()) / "bin" / "deno")
    for path in candidates:
        if path.is_file():
            return path
    return None


def node_path() -> Path | None:
    found = shutil.which("node")
    if not found:
        return None
    try:
        r = subprocess.run([found, "--version"], capture_output=True, text=True,
                           timeout=5)
        major = int(r.stdout.strip().lstrip("v").split(".", 1)[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return Path(found) if major >= 22 else None


@lru_cache(maxsize=1)
def runtime() -> tuple[str, Path] | tuple[None, None]:
    deno = deno_path()
    if deno:
        return "deno", deno
    node = node_path()
    if node:
        return "node", node
    return None, None


def runtime_args() -> list[str]:
    name, path = runtime()
    return ["--js-runtimes", f"{name}:{path}"] if name else []


def available() -> bool:
    return importlib.util.find_spec("yt_dlp") is not None


def cmd(*args: str) -> list[str]:
    return [sys.executable, "-m", "yt_dlp", *RETRY_ARGS, *runtime_args(), *args]


def is_transient(stderr: str) -> bool:
    return bool(TRANSIENT.search(stderr or ""))


def run(args, timeout: int = 180, attempts: int = 3):
    """Run yt-dlp, retrying only transient failures with short pauses."""
    if not available():
        raise RuntimeError(
            "yt-dlp is not installed; run setup.sh. PDF and local paths still work.")
    full = cmd(*args)
    attempts = max(1, attempts)
    for attempt in range(attempts):
        try:
            result = subprocess.run(full, capture_output=True, text=True,
                                    timeout=timeout)
        except subprocess.TimeoutExpired:
            result = None
        if result is not None and (result.returncode == 0 or
                                   not is_transient(result.stderr)):
            return result
        if attempt == attempts - 1:
            if result is None:
                raise RuntimeError(f"yt-dlp timed out after {timeout}s")
            return result
        delay = DELAYS[min(attempt, len(DELAYS) - 1)]
        print(f"ytdlp: transient error, retrying in {delay}s",
              file=sys.stderr, flush=True)
        time.sleep(delay)
    return result
