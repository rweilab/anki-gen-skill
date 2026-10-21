# anki-gen — install and vendoring notes

This file is for setting the skill up once. The model does not need it during a normal run.

Maintainers: read `AGENTS.md` for the dev workflow and `MAINTAINERS.md` before architectural or token-efficiency changes. Neither is loaded by `SKILL.md` during a normal run. Tests: `bash scripts/smoke.sh` now includes negative fixtures, a golden deck, sabotage probes from `tests/hardening.py`, and offline video fixtures from `tests/video_hardening.py`. On failure it prints the line, work directory, relevant hints, and logs; use `KEEP_WORK=1` to keep the fixture and `SMOKE_DEBUG=1` for a trace.

**Python 3.10+ is required** (the `anki` package). On Homebrew Python,
`pip install --user` without `--break-system-packages` is blocked (PEP 668);
the macOS block is the supported route because GUI-launched opencode sees the
user site.

```bash
# macOS
brew install python poppler pandoc ghostscript
"$(brew --prefix)/bin/python3" -m pip install --user --break-system-packages \
  anki pymupdf pillow beautifulsoup4
brew install --cask anki            # desktop app, for manual .apkg import

# Linux
python3 -m pip install --user anki pymupdf pillow beautifulsoup4 yt-dlp
# Fedora: sudo dnf install poppler-utils ffmpeg tesseract

# Optional video frames (macOS example)
# brew install ffmpeg tesseract
# python3 -m pip install --user --break-system-packages yt-dlp
```

`scripts/setup.sh` prints the system package commands for macOS, Debian/Ubuntu,
Fedora, or Arch and installs the Python libraries into the user site. It never
runs sudo. `scripts/setup_macos.sh` is a compatibility wrapper. `scripts/doctor.py`
checks the result and prints platform-specific fixes. `INSTALL.md` in the handoff
zip is the one-page user guide.

**`anki` is required for every build** — the builder creates the collection with Anki's own library,
which is what makes the package one Anki will open. **No `genanki`**: it is imported by nothing and
cannot build a cloze deck Anki 26 opens. No `requests`, no `lxml`. `review_server.py` needs only
stdlib `http.server` + `render.py`. **Do NOT install `katex` or `texlive-latex2svg`** — PyPI
`katex` is a Facebook image converter at 0.0.4, not a LaTeX renderer. Math is Anki's bundled MathJax.

**MathJax is vendored, not from a CDN.** `assets/mathjax/tex-svg.js` ships with the skill and the
server serves it from `/assets/...`, so the review page typesets with no network. Keep it that way —
a CDN works until you are offline, then every card turns into `\(d_{hkl}\)`. Use `tex-svg.js`
specifically: `tex-mml-chtml.js` resolves fonts relative to its own script URL, so copying just the
JS leaves every font 404ing, while `tex-svg.js` embeds glyphs as SVG paths — one file, no external
requests. Re-vendor with:
`curl -sL https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js -o .../assets/mathjax/tex-svg.js`.


## If a system tool is missing

PDF text is tried in this order: **poppler's `pdftotext` → pymupdf → mupdf-tools
(`mutool`) → ghostscript (`gs`)**. If none exists, `extract_pdf.py` fails with a
clear message instead of writing an empty extract. pymupdf is the cross-platform
pip fallback (wheels for macOS and Linux; no system packages).

| Need | Primary | macOS (brew) | Debian/Ubuntu | Fedora | Arch | Fallback |
|---|---|---|---|---|---|---|
| PDF text | poppler (`pdftotext`) | `brew install poppler` | `sudo apt install poppler-utils` | `sudo dnf install poppler-utils` | `sudo pacman -S poppler` | pymupdf, `mutool`, `gs` |
| PDF text + images | pymupdf + Pillow | `pip install pymupdf pillow` | `pip install pymupdf pillow` | `pip install pymupdf pillow` | `pip install pymupdf pillow` | `mutool`, `gs`; images need Pillow |
| Image downscale | Pillow | `pip install pillow` | `pip install pillow` | `pip install pillow` | `pip install pillow` | skip over-cap images |
| PDF text (alternate) | mupdf-tools (`mutool draw -F txt`) | `brew install mupdf-tools` | `sudo apt install mupdf-tools` | `sudo dnf install mupdf-tools` | `sudo pacman -S mupdf-tools` | `gs` |
| PDF text (last resort) | ghostscript (`gs -sDEVICE=txtwrite`) | `brew install ghostscript` | `sudo apt install ghostscript` | `sudo dnf install ghostscript` | `sudo pacman -S ghostscript` | clear error |
| HTML → markdown | pandoc (optional) | `brew install pandoc` | `sudo apt install pandoc` | `sudo dnf install pandoc` | `sudo pacman -S pandoc` | raw HTML |
| Fetch URLs | curl | preinstalled / `brew install curl` | preinstalled | preinstalled | preinstalled | — |

`pymupdf` is already listed in the install block above; it is the one dependency
that works the same on every platform and covers both text (fallback) and images.

## Images (opt-in) and handwritten sources

**Text-first.** Image bundling is off unless the user asks. `extract_pdf.py` writes figures and
`figures.json`; `media_index.py <workdir>` prints a compact candidate list. Build with
`build_apkg.py cards.json Deck.apkg --deck-name NAME --media --media-root <workdir>`. Images
require Pillow; over-cap files are downscaled, not dropped.

For handwritten/scanned pages or a figure that is the only source for a fact, the separate
`image-vision` skill can read it with Gemini (free-tier flash-lite, `GEMINI_API_KEY`). That is a
comprehension aid; the builder stays text-first and attaches an image only when asked. See
`HANDOFF.md` for the key and GUI-launch notes.
Per image ≤1600 px / ≤1 MB, ≤2 per card; over-cap files are downscaled (Pillow) to fit and only
skipped if they are still over. Review serves
raster formats (png/jpeg/webp/gif) and samples image cards as a bounded cross-section. Wrong
images go in the review comment.

## Handing the skill to someone else

`bash scripts/package_handoff.sh [out.zip]` builds a zip containing both skills
(`anki-gen`, `image-vision`), `install.sh`, `INSTALL.md`, and `VERSION` at the root.
The user extracts it and runs `bash install.sh` (or asks opencode to install it),
then `bash ~/.claude/skills/anki-gen/scripts/setup.sh`. Re-running a newer zip
upgrades with a timestamped backup under `~/.claude/skills/.backups/`. See `HANDOFF.md`/`INSTALL.md`.

## Snapshots

`CHANGELOG.md` records complete working states by descriptor (not a version
series). It is not loaded by the skill.

