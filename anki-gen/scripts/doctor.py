#!/usr/bin/env python3
"""Preflight for a fresh machine (especially macOS) before using anki-gen.

Run this once after setup, and again whenever a command fails with a missing
module or tool. It answers one question: can this machine build a text deck,
and what is missing for images, handwriting, or Anki?

    python3 scripts/doctor.py

Exit 0 when the core text path is ready; 1 when something required is missing.
Image, video, Anki-app and Gemini checks are warnings: the text path does not need
them.
"""
from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def os_id() -> str:
    if sys.platform == "darwin":
        return "macos"
    try:
        text = Path("/etc/os-release").read_text()
        for line in text.splitlines():
            if line.startswith("ID="):
                ident = line.split("=", 1)[1].strip().strip('"')
                if ident in ("ubuntu", "debian", "linuxmint", "pop"):
                    return "debian"
                if ident in ("fedora", "rhel", "centos"):
                    return "fedora"
                if ident in ("arch", "manjaro"):
                    return "arch"
    except OSError:
        pass
    return "linux"


def pkg_fix(package: str) -> str:
    os_name = os_id()
    if os_name == "macos":
        return f"brew install {package}"
    if os_name == "debian":
        return f"sudo apt install {package}"
    if os_name == "fedora":
        return f"sudo dnf install {package}"
    if os_name == "arch":
        return f"sudo pacman -S {package}"
    return f"install {package} with your package manager"


def has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def line(label: str, ok: bool, detail: str, fix: str = "", core: bool = False,
         warn_only: bool = False) -> bool:
    mark = "ok   " if ok else ("warn " if warn_only else "MISS ")
    print(f"{mark} {label:<30} {detail}")
    if not ok and fix:
        print(f"       fix: {fix}")
    return ok or (warn_only) or not core


def main() -> int:
    print(f"anki-gen doctor · {os_id()} · {platform.machine()}")
    print("=" * 72)
    version = (ROOT / "VERSION").read_text().strip() if (ROOT / "VERSION").is_file() else "unknown"
    print(f"installed version: {version}")
    core_ok = True

    py_ok = sys.version_info >= (3, 10)
    core_ok &= line("Python >= 3.10", py_ok, sys.version.split()[0],
                    pkg_fix("python3"), core=True)
    line("python3 path", True, sys.executable, warn_only=True)
    if sys.platform == "darwin" and sys.executable.startswith("/usr/bin/"):
        print("       warning: macOS system Python, not Homebrew's. A GUI-launched\n"
              "       opencode may have a PATH without /opt/homebrew/bin; launch it from\n"
              "       Terminal (opencode web) or fix the app's PATH.")

    for mod, label, fix, core in (
        ("anki", "anki library (build)", "pip install --user --break-system-packages anki", True),
        ("pymupdf", "pymupdf (PDF text/images)", "pip install --user --break-system-packages pymupdf", True),
        ("PIL", "Pillow (image downscale)", "pip install --user --break-system-packages pillow", False),
        ("bs4", "beautifulsoup4 (web images)", "pip install --user --break-system-packages beautifulsoup4", False),
    ):
        core_ok &= line(label, has_module(mod), "importable" if has_module(mod) else "missing",
                        fix, core=core, warn_only=not core)

    for cmd, label, fix, warn in (
        ("pdftotext", "pdftotext (fast PDF text)", pkg_fix("poppler"), True),
        ("pdfimages", "pdfimages (image-vision)", pkg_fix("poppler"), True),
        ("pandoc", "pandoc (HTML -> markdown)", pkg_fix("pandoc"), True),
        ("gs", "ghostscript (PDF fallback)", pkg_fix("ghostscript"), True),
        ("mutool", "mutool (PDF fallback)", pkg_fix("mupdf-tools"), True),
        ("curl", "curl (URLs)", pkg_fix("curl"), True),
        ("yt-dlp", "yt-dlp (video transcripts/stills)",
         "python3 -m pip install --user --break-system-packages yt-dlp", True),
        ("ffmpeg", "ffmpeg (video frames)", pkg_fix("ffmpeg"), True),
        ("tesseract", "tesseract (frame OCR)", pkg_fix("tesseract"), True),
    ):
        path = shutil.which(cmd)
        line(label, bool(path), path or "missing", fix, warn_only=warn)

    try:
        con = sqlite3.connect(":memory:")
        con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        con.close()
        line("SQLite FTS5", True, "available", core=True)
    except Exception as e:
        core_ok &= line("SQLite FTS5", False, str(e),
                        "use a Python build with SQLite FTS5", core=True)

    mathjax = ROOT / "assets" / "mathjax" / "tex-svg.js"
    core_ok &= line("MathJax asset", mathjax.is_file(), str(mathjax),
                    "re-copy the skill folder; the asset ships with it", core=True)

    skill = Path.home() / ".claude" / "skills" / "anki-gen" / "SKILL.md"
    core_ok &= line("anki-gen skill", skill.is_file(), str(skill),
                    "copy anki-gen into ~/.claude/skills/", core=True)

    vision = Path.home() / ".claude" / "skills" / "image-vision" / "SKILL.md"
    line("image-vision skill", vision.is_file(), str(vision),
         "copy image-vision into ~/.claude/skills/ (for handwritten/figures)",
         warn_only=True)

    if os_id() == "macos":
        anki_app = Path("/Applications/Anki.app")
        anki_ok = anki_app.exists()
        anki_detail = str(anki_app) if anki_ok else "not installed"
        anki_fix = "brew install --cask anki (the pip 'anki' library is not the app)"
    else:
        anki_path = shutil.which("anki")
        anki_ok = bool(anki_path)
        anki_detail = anki_path or "not installed"
        anki_fix = "install Anki desktop separately for manual .apkg import"
    line("Anki desktop (manual import)", anki_ok, anki_detail, anki_fix,
         warn_only=True)

    key_env = bool(os.environ.get("GEMINI_API_KEY"))
    key_file = Path.home() / ".config" / "anki-gen" / "gemini.key"
    key_ok = key_env or key_file.is_file()
    where = ("env" if key_env else
             (str(key_file) if key_file.is_file() else "not set"))
    line("Gemini key (images/handwriting)", key_ok, where,
         "set GEMINI_API_KEY, or write ~/.config/anki-gen/gemini.key (chmod 600)",
         warn_only=True)
    if key_file.is_file() and (key_file.stat().st_mode & 0o077):
        print("       warning: the key file is readable by others; run: chmod 600 "
              f"{key_file}")

    print("=" * 72)
    if not core_ok:
        print("Core text path is NOT ready — fix the MISS lines above.")
        return 1
    print("Core text path is ready.")
    print("Warnings are optional: images (Pillow), handwriting (image-vision), "
          "web images (bs4), video (yt-dlp/ffmpeg/tesseract), and the Anki app.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
