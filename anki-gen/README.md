# anki-gen — install and vendoring notes

This file is for setting the skill up once. The model does not need it during a normal run.

Maintainers: read `AGENTS.md` for the dev workflow and read order. It points to
`MAINTAINERS.md`, `maintainers/lessons.md`, and `maintainers/dossier-format.md`.
None are loaded by `SKILL.md` during a normal run. Tests: `bash scripts/smoke.sh`
now includes negative fixtures, a golden deck, sabotage/mutation probes from
`tests/hardening.py`, offline video fixtures from `tests/video_hardening.py`,
adversarial PPTX fixtures from `tests/slides_hardening.py`, local-media/pipeline
fixtures, and AnkiConnect revision/dossier fixtures from `tests/revision_hardening.py`
and `tests/context_hardening.py`. On failure it prints the line, work directory, relevant hints, and logs; use `KEEP_WORK=1` to keep the fixture and `SMOKE_DEBUG=1` for a trace.

**Python 3.10+ is required** (the `anki` package). On Homebrew Python,
`pip install --user` without `--break-system-packages` is blocked (PEP 668);
the macOS block is the supported route because GUI-launched opencode sees the
user site.

```bash
# setup.sh does this automatically.
# macOS (Homebrew must already be installed)
brew install python poppler pandoc ghostscript mupdf-tools ffmpeg tesseract
"$(brew --prefix)/bin/python3" -m pip install --user --break-system-packages \
  -r requirements.txt
# Optional image/video/local-audio libraries, best effort:
"$(brew --prefix)/bin/python3" -m pip install --user --break-system-packages \
  -r requirements-optional.txt

# Linux (setup.sh uses sudo for the package step)
sudo apt install python3 python3-pip poppler-utils pandoc \
  ghostscript mupdf-tools ffmpeg tesseract-ocr
python3 -m pip install --user --break-system-packages -r requirements.txt
# Optional image/video/local-audio libraries, best effort:
python3 -m pip install --user --break-system-packages -r requirements-optional.txt

# The Anki desktop app is separate and never installed by this skill.
```

`scripts/setup.sh` installs only the missing system packages for macOS,
Debian/Ubuntu, Fedora, or Arch, installs the Python libraries into the user site,
then runs the doctor. Core requires only `anki` and PyMuPDF. The optional
`requirements-optional.txt` adds image, YouTube, and local-audio support,
including `yt-dlp[default,deno]`/EJS, Pillow, and faster-whisper. Those are
installed one at a time and a failure is a warning, not an install failure. Setup
prints whether the full feature set is installed and lists any doctor gaps.
PyMuPDF is pinned below 2.0 for stable macOS/Linux wheels; runtime scripts also
add Homebrew's bin directories when opencode is GUI-launched. It never installs
Homebrew or Anki. On macOS a missing Homebrew is a warning; on Linux the package
step uses sudo when available. `scripts/setup_macos.sh` is a compatibility wrapper.
`scripts/doctor.py` checks the result and prints platform-specific fixes.
`INSTALL.md` in the handoff zip is the one-page user guide.

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

Local video/audio uses ffprobe + ffmpeg and either sidecar VTT/SRT, faster-whisper,
or whisper.cpp. faster-whisper is used when importable; otherwise setup.sh installs
whisper.cpp on Apple Silicon, and on Linux when faster-whisper is unavailable.
The whisper.cpp model downloads on first local transcription. Media is never
uploaded. Apple Silicon macOS and mainstream Linux are the supported local-audio
paths; Intel Macs are best-effort. PDF text is tried in this order: **poppler's `pdftotext` → pymupdf → mupdf-tools
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
| PowerPoint | `extract_slides.py` (stdlib) | no install | no install | no install | no install | text/notes/embedded images; vector slides cited |
| HTML → markdown | pandoc (optional) | `brew install pandoc` | `sudo apt install pandoc` | `sudo dnf install pandoc` | `sudo pacman -S pandoc` | raw HTML |
| Fetch URLs | curl | preinstalled / `brew install curl` | preinstalled | preinstalled | preinstalled | — |

`pymupdf` is already listed in the install block above; it is the one dependency
that works the same on every platform and covers both text (fallback) and images.

## Images (opt-in) and handwritten sources

**Text-first.** Image bundling is off unless the user asks. `extract_pdf.py` writes embedded
figures and tight page/slide crops for captioned vector diagrams; web extraction records
`alt`/`figcaption`/heading and a source URL. `media_index.py <workdir>` prints a compact
candidate list, or `--cards cards.jsonl` ranks the best few per card. Candidates are never
auto-attached. Build with
`build_apkg.py cards.jsonl Deck.apkg --deck-name NAME --media --media-root <workdir>`.
For the one-call path, `pipeline.py --work <workdir> --out-apkg Deck.apkg`; a `.apkg`
passed to `--work`/`--out` is rejected. Images
require Pillow; over-cap files are downscaled, not dropped.

For handwritten/scanned pages or a figure that is the only source for a fact, the separate
`image-vision` skill can read it with Gemini (free-tier flash-lite, `GEMINI_API_KEY`). That is a
comprehension aid; the builder stays text-first and attaches an image only when asked. See
`HANDOFF.md` for the key and GUI-launch notes.
Per image ≤1600 px / ≤1 MB, ≤2 per card; over-cap files are downscaled (Pillow) to fit and only
skipped if they are still over. Review serves
raster formats (png/jpeg/webp/gif) and samples image cards as a bounded cross-section. Wrong
images go in the review comment.

## Revising an imported deck

New decks are `.apkg` files and need no AnkiConnect. Revisions of an already-imported deck use
AnkiConnect only: open Anki first and check `python3 scripts/anki_connect.py` (the pinned add-on
can be installed with `--install --yes`). Never inspect the live collection DB, even read-only.
If AnkiConnect is unreachable these commands exit nonzero with a setup message; they never fall
back to raw SQLite, the `anki` library, or MCP. The compact
dossier lives under `${XDG_DATA_HOME:-~/.local/share}/anki-gen/decks/<deck-uuid>/`, not in Anki
notes/media, and can be moved with `revision.py context export|import`. Every apply takes an
AnkiConnect snapshot; `revision.py revert --deck "NAME" --last --yes` undoes it. Bulk field/tag
edits use `revision.py update` or `revision.py tags --lowercase`, both with snapshot and scheduling
verification. Full workflow: `references/revision.md`.

## Handing the skill to someone else

`bash scripts/package_handoff.sh [out.zip]` builds a zip containing both skills
(`anki-gen`, `image-vision`), `install.sh`, `INSTALL.md`, and a root `VERSION`
generated from `anki-gen/VERSION`.
The user extracts it and runs `bash install.sh` (or asks opencode to install it).
The installer also installs dependencies and runs the doctor. Re-running a newer
zip upgrades with a timestamped backup under `~/.local/share/anki-gen/backups/`. See
`HANDOFF.md`/`INSTALL.md`.

## Snapshots

`CHANGELOG.md` records complete working states by descriptor (not a version
series). It is not loaded by the skill.

