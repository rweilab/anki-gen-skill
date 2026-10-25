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
import subprocess
import sys
from pathlib import Path

from platform_paths import ensure_tool_paths
ensure_tool_paths()

import ytdlp
import media_transcribe as mt  # noqa: E402

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


def anki_app() -> str | None:
    """Find the desktop app even when it was dragged into Applications by hand."""
    if os_id() == "macos":
        candidates = (Path("/Applications/Anki.app"),
                      Path.home() / "Applications/Anki.app")
        for path in candidates:
            if path.exists():
                return str(path)
        mdfind = shutil.which("mdfind")
        if mdfind:
            try:
                out = subprocess.run([mdfind, "kMDItemFSName == 'Anki.app'"],
                                     capture_output=True, text=True, timeout=5)
                for line in out.stdout.splitlines():
                    if line.strip():
                        return line.strip()
            except (OSError, subprocess.SubprocessError):
                pass
        return None
    path = shutil.which("anki")
    if path:
        return path
    flatpak = shutil.which("flatpak")
    if flatpak:
        try:
            out = subprocess.run([flatpak, "list", "--app", "--columns=application"],
                                 capture_output=True, text=True, timeout=5)
            if "net.ankiweb.Anki" in out.stdout:
                return "flatpak"
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def line(label: str, ok: bool, detail: str, fix: str = "", core: bool = False,
         warn_only: bool = False) -> bool:
    mark = "ok   " if ok else ("warn " if warn_only else "MISS ")
    print(f"{mark} {label:<30} {detail}")
    if not ok and fix:
        print(f"       fix: {fix}")
    if ok or warn_only:
        return True
    return not core


def main() -> int:
    print(f"anki-gen doctor · {os_id()} · {platform.machine()}")
    if os_id() == "macos" and platform.machine() != "arm64":
        print("warn  Intel Mac local transcription is best-effort; PDF/YouTube paths still work")
    print("=" * 72)
    version = (ROOT / "VERSION").read_text().strip() if (ROOT / "VERSION").is_file() else "unknown"
    print(f"installed version: {version}")
    core_ok = True

    py_ok = sys.version_info >= (3, 10)
    # `&=` runs every check (no short-circuit) and keeps any failure.
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
        ("yt_dlp", "yt-dlp module (video)", 'pip install --user --break-system-packages "yt-dlp[default,deno]"', False),
        ("yt_dlp_ejs", "yt-dlp EJS (YouTube)", "pip install --user --break-system-packages yt-dlp-ejs", False),
    ):
        found = has_module(mod)
        core_ok &= line(label, found, "importable" if found else "missing",
                        fix, core=core, warn_only=not core)

    faster_ok = mt._faster_whisper_available()
    whisper_cli = mt.whisper_cli_path()
    whisper_model = mt.whisper_cpp_model_cached()
    if faster_ok:
        detail = "faster-whisper"
        local_ok = True
    elif whisper_cli:
        detail = "whisper.cpp" + ("" if whisper_model
                                  else " (model downloads on first use)")
        local_ok = True
    else:
        detail = "off"
        local_ok = False
    line("local audio", local_ok, detail,
         "run setup.sh; captions and YouTube still work without local audio",
         warn_only=True)

    for cmd, label, fix, warn in (
        ("pdftotext", "pdftotext (fast PDF text)", pkg_fix("poppler"), True),
        ("pdfimages", "pdfimages (image-vision)", pkg_fix("poppler"), True),
        ("pandoc", "pandoc (HTML -> markdown)", pkg_fix("pandoc"), True),
        ("gs", "ghostscript (PDF fallback)", pkg_fix("ghostscript"), True),
        ("mutool", "mutool (PDF fallback)", pkg_fix("mupdf-tools"), True),
        ("curl", "curl (URLs)", pkg_fix("curl"), True),
        ("ffmpeg", "ffmpeg (video frames/audio)", pkg_fix("ffmpeg"), True),
        ("ffprobe", "ffprobe (local media metadata)", pkg_fix("ffmpeg"), True),
        ("tesseract", "tesseract (frame OCR)", pkg_fix("tesseract"), True),
    ):
        path = shutil.which(cmd)
        line(label, bool(path), path or "missing", fix, warn_only=warn)

    runtime, runtime_path = ytdlp.runtime()
    line("JS runtime (yt-dlp)", bool(runtime),
         f"{runtime}: {runtime_path}" if runtime else "missing",
         "pip install --user --break-system-packages deno; or install Node 22+",
         warn_only=True)

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

    skill = ROOT / "SKILL.md"
    core_ok &= line("anki-gen skill", skill.is_file(), str(skill),
                    "copy anki-gen into your skills directory (default ~/.claude/skills/)",
                    core=True)

    vision = ROOT.parent / "image-vision" / "SKILL.md"
    line("image-vision skill", vision.is_file(), str(vision),
         "copy image-vision beside anki-gen (for handwritten/figures)",
         warn_only=True)

    legacy = ROOT.parent / ".backups"
    stale = list(legacy.rglob("SKILL.md")) if legacy.is_dir() else []
    line("Backups outside skills", not stale,
         f"{len(stale)} discoverable backup(s)" if stale else "ok",
         "run install.sh to migrate, or rename backup SKILL.md to SKILL.md.bak",
         warn_only=True)

    anki_detail = anki_app()
    anki_fix = "install Anki desktop separately for manual .apkg import"
    if os_id() == "macos":
        anki_fix += " (brew install --cask anki)"
    line("Anki desktop (manual import)", bool(anki_detail),
         anki_detail or "not installed", anki_fix, warn_only=True)

    key_env = bool(os.environ.get("GEMINI_API_KEY"))
    key_file = Path.home() / ".config" / "anki-gen" / "gemini.key"
    key_ok = key_env or key_file.is_file()
    if key_env:
        where = "env"
    elif key_file.is_file():
        where = str(key_file)
    else:
        where = "not set"
    line("Gemini key (images/handwriting)", key_ok, where,
         "set GEMINI_API_KEY, or write ~/.config/anki-gen/gemini.key (chmod 600)",
         warn_only=True)
    if key_file.is_file() and (key_file.stat().st_mode & 0o077):
        print("       warning: the key file is readable by others; run: chmod 600 "
              f"{key_file}")

    if faster_ok:
        stt = "faster-whisper" + (" (whisper.cpp fallback available)"
                                  if whisper_cli else "")
    elif whisper_cli:
        stt = "whisper.cpp" + ("" if whisper_model
                               else " (model downloads on first use)")
    else:
        stt = "off (captions and YouTube still work)"
    print(f"Local transcription: {stt}")

    print("=" * 72)
    if not core_ok:
        print("Core text path is NOT ready — fix the MISS lines above.")
        return 1
    print("Core text path is ready.")
    print("Warnings are optional: images (Pillow), handwriting (image-vision), "
          "web images (bs4), video (yt-dlp/EJS/Deno/ffmpeg/tesseract), "
          "local audio, and the Anki app.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
