#!/usr/bin/env python3
"""
Extract text and images from PDF, text, URL, or directory sources.
Uses: pdftotext, pymupdf (fitz), tesseract, curl, pandoc

ONE SOURCE
    extract_pdf.py <source> <output_dir> [--tag NAME] [--date-filter FILTER]
    Writes <output_dir>/<tag>.md (default `source.md`) + media/, and prints one
    result object as JSON on stdout. `-` as the source reads stdin.

MANY SOURCES (batch)
    extract_pdf.py --batch <source> [<source> ...] --out <output_dir>
    Writes one <tag>.md PER SOURCE plus manifest.json, so extracting three
    lectures leaves three files to cite instead of one overwritten `source.md`.
    `<tag>` is the source's filename stem, sanitised and de-duplicated; it is the
    name the manifest and every card's `source` locator should use.

WHY STDOUT IS KEPT CLEAN
    stdout carries the JSON result and nothing else -- a caller parses it. Both
    this script's own messages and pymupdf's internal chatter must stay off it:
    the script already prints warnings to stderr, and the pymupdf noise is
    suppressed below. Do not "fix" the stderr prints; they were never the problem.
"""
import argparse
import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from typing import Dict, Any, List, Optional


def run_cmd(cmd: List[str], cwd: str = None, input: str = None,
            timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, input=input, capture_output=True, text=True,
                          check=False, timeout=timeout)


# ------------------------------------------------------------------ pymupdf noise
# pymupdf writes parse warnings straight to the process's stdout from C ("MuPDF
# error: cannot load ..."). That is not a Python print, so it cannot be fixed by
# touching this file's own output calls -- and it corrupts the JSON a caller is
# trying to parse. Two layers: ask mupdf to be quiet, and hold stdout closed for
# the duration of the fitz work in case it talks anyway.
def _fitz():
    """Import pymupdf quietly, or return None if it is not installed.

    The import itself is inside _quiet(): pymupdf's legacy `fitz` shim prints
    "warning: The `fitz` API is deprecated ..." to STDOUT at import time, which
    lands in the caller's JSON before a single page is read. Preferring the
    `pymupdf` name avoids the notice in the first place; the redirect is there for
    builds where even that talks.
    """
    with _quiet():
        try:
            import pymupdf as fitz
        except ImportError:
            try:
                import fitz
            except ImportError:
                return None
        for setter in ("mupdf_display_errors", "mupdf_display_warnings"):
            try:
                getattr(fitz.TOOLS, setter)(False)
            except Exception:
                pass      # older/newer builds without the switch; the redirect covers it
    return fitz


@contextlib.contextmanager
def _quiet():
    """Swallow anything written to stdout inside this block.

    Used around the pymupdf calls only. Everything this script means to say goes
    to stderr or to the single JSON print at the end of main().
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield buf


# ------------------------------------------------------------------ tags
def safe_tag(name: str) -> str:
    """A filename-safe tag for a source: `Ch 4 - Lec 10.pdf` -> `Ch-4-Lec-10`.

    Cards cite `source` strings like "Ch 4 · Lec 10 Q7", so the tag wants to stay
    recognisable rather than be slugged to death -- it is the handle a human will
    type again in a citation.
    """
    tag = re.sub(r"[^\w.\- ]+", "", str(name or "")).strip()
    tag = re.sub(r"\s+", "-", tag).strip(".-")
    return tag or "source"


def tag_for(source: str) -> str:
    if source in ("-", "stdin"):
        return "stdin"
    if source.startswith(("http://", "https://")):
        parts = urlsplit(source)
        name = Path(parts.path).stem if parts.path else parts.netloc
        return safe_tag(name or "url")
    p = Path(source)
    return safe_tag(p.stem if p.suffix else p.name)


def unique_tag(tag: str, taken: set) -> str:
    if tag not in taken:
        taken.add(tag)
        return tag
    i = 2
    while f"{tag}-{i}" in taken:
        i += 1
    tag = f"{tag}-{i}"
    taken.add(tag)
    return tag


def _page_title(page) -> str:
    """Best-effort slide title: first substantive line, skipping headers/numbers."""
    skip = re.compile(r"^(ME-UY-\d|Fall \d{4}|Spring \d{4}|Rakesh|Lecture #|"
                      r"Date$|Day$|Topics$|Chapter$|Assessment$|\d+$|"
                      r"\d{1,2}/\d{1,2}/\d{2,4}$|"
                      r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2}$|"
                      r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*$)",
                      re.I)
    for line in page.get_text().splitlines():
        text = line.strip()
        if text and not skip.match(text):
            return text[:120]
    return ""


def _figure_caption(page) -> str:
    """One caption-like line on the page, or empty when ambiguous/missing."""
    lines = [ln.strip() for ln in page.get_text().splitlines()
             if re.match(r"^(figure|fig\.?)\s*\d", ln.strip(), re.I)]
    return lines[0] if len(lines) == 1 else ""


def _pdf_text(pdf_path: str) -> str:
    """Text via the first available extractor.

    Order is by ubiquity and quality: poppler's pdftotext, then pymupdf (a pip
    dependency with wheels on macOS/Linux), then mupdf-tools, then ghostscript.
    If none exists, say so instead of writing an empty extract.
    """
    tried = False
    if shutil.which("pdftotext"):
        tried = True
        r = run_cmd(["pdftotext", pdf_path, "-"])
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    fitz = _fitz()
    if fitz is not None:
        tried = True
        try:
            with _quiet():
                doc = fitz.open(pdf_path)
                text = "\n".join(page.get_text() for page in doc)
                doc.close()
            if text.strip():
                return text
        except Exception as e:
            print(f"Warning: pymupdf text failed for {pdf_path}: {e}", file=sys.stderr)
    if shutil.which("mutool"):
        tried = True
        r = run_cmd(["mutool", "draw", "-F", "txt", "-o", "-", pdf_path])
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    if shutil.which("gs"):
        tried = True
        r = run_cmd(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=txtwrite",
                     "-sOutputFile=-", pdf_path])
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    if not tried:
        raise ValueError(
            "no PDF text extractor available. Install one: poppler (pdftotext) on "
            "macOS/Linux, pymupdf via pip, mupdf-tools (mutool), or ghostscript (gs).")
    return ""


def extract_pdf(pdf_path: str, output_dir: Path, stem: str = "source") -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    media_dir = Path(output_dir) / "media"
    media_dir.mkdir(exist_ok=True)

    text_file = Path(output_dir) / f"{stem}.md"
    text_content = _pdf_text(pdf_path)
    if not text_content.strip():
        print(f"Warning: {pdf_path} has no text layer (likely a scanned or "
              f"handwritten PDF); the extracted text will be empty", file=sys.stderr)
    text_file.write_text(text_content)

    images = []
    figures = []
    fitz = _fitz()
    if fitz is not None:
        try:
            # _quiet(): pymupdf's C layer prints parse warnings to stdout, which is
            # where the caller's JSON lives. See the note at the top of this file.
            with _quiet():
                doc = fitz.open(pdf_path)
                for page_num in range(len(doc)):
                    page = doc[page_num]
                    images_list = page.get_images(full=True)
                    for img_idx, img in enumerate(images_list):
                        xref = img[0]
                        pix = fitz.Pixmap(doc, xref)
                        if pix.n < 5:
                            img_path = media_dir / f"fig_p{page_num}_{img_idx}.png"
                            pix.save(str(media_dir / img_path.name))
                            width, height = pix.width, pix.height
                        else:
                            pix1 = fitz.Pixmap(fitz.csRGB, pix)
                            img_path = media_dir / f"fig_p{page_num}_{img_idx}.png"
                            pix1.save(str(media_dir / img_path.name))
                            width, height = pix1.width, pix1.height
                            pix1 = None
                        images.append(str(img_path))
                        figures.append({
                            "file": f"media/{img_path.name}",
                            "page": page_num + 1,
                            "width": width,
                            "height": height,
                            "bytes": img_path.stat().st_size,
                            "caption": _figure_caption(page),
                            "title": _page_title(page),
                        })
                doc.close()
        except Exception as e:
            print(f"Image extraction warning: {e}", file=sys.stderr)

    (Path(output_dir) / "figures.json").write_text(json.dumps(figures, indent=2) + "\n")
    return {
        "content": text_content,
        "images": images,
        "figures": figures,
        "source_type": "pdf",
        "source_path": pdf_path
    }


def extract_text(text_path: str, output_dir: Path, stem: str = "source") -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    # Copied rather than referenced so the extracted tree keeps its own faithful
    # copy: the source file can be edited or deleted, and the deck's citations
    # still point at something that exists.
    dest = Path(output_dir) / f"{stem}.md"
    if Path(text_path).resolve() != dest.resolve():
        shutil.copy(text_path, dest)
    content = Path(text_path).read_text()
    return {
        "content": content,
        "images": [],
        "source_type": "text",
        "source_path": text_path
    }


def extract_url(url: str, output_dir: Path, stem: str = "source") -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    media_dir = Path(output_dir) / "media"
    media_dir.mkdir(exist_ok=True)

    result = run_cmd(["curl", "-sL", "--max-time", "30", url])
    html = result.stdout if result.returncode == 0 else ""

    if not html:
        raise ValueError(f"Failed to fetch URL: {url}")

    result = run_cmd(["pandoc", "-f", "html", "-t", "markdown"], input=html)
    md = result.stdout if result.returncode == 0 else html

    output_file = Path(output_dir) / f"{stem}.md"
    output_file.write_text(md)

    images = []
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        for i, img in enumerate(soup.find_all('img')):
            src = img.get('src') or img.get('data-src')
            if src:
                img_url = src if src.startswith('http') else url.rsplit('/', 1)[0] + '/' + src
                img_result = run_cmd(["curl", "-sL", "--max-time", "10", img_url])
                if img_result.returncode == 0 and img_result.stdout:
                    img_path = Path(output_dir) / "media" / f"web_img_{i}.png"
                    Path(output_dir / "media").mkdir(exist_ok=True)
                    Path(img_path).write_bytes(img_result.stdout)
                    images.append(str(img_path))
    except Exception:
        pass

    return {
        "content": md,
        "images": images,
        "source_type": "url",
        "source_path": url
    }


def extract_directory(dir_path: str, output_dir: Path, date_filter: str = None,
                      recursive: bool = True, stem: str = "source") -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    media_dir = Path(output_dir) / "media"
    media_dir.mkdir(exist_ok=True)

    cutoff_time = None
    if date_filter:
        cutoff_time = parse_date_filter(date_filter)

    exts = {'.pdf', '.txt', '.md', '.tex', '.html', '.htm'}

    all_content = []
    all_images = []
    processed_files = []

    dir_path = Path(dir_path)
    if not dir_path.exists():
        raise ValueError(f"Directory not found: {dir_path}")

    pattern = "**/*" if recursive else "*"
    for file_path in dir_path.glob(pattern):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in exts:
            continue

        if cutoff_time:
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            if mtime < cutoff_time:
                continue

        try:
            if file_path.suffix.lower() == '.pdf':
                result = extract_pdf(str(file_path), output_dir / file_path.stem)
            elif file_path.suffix.lower() in {'.txt', '.md', '.tex'}:
                result = extract_text(str(file_path), output_dir / file_path.stem)
            elif file_path.suffix.lower() in {'.html', '.htm'}:
                result = extract_url(file_path.as_uri(), output_dir / file_path.stem)
            else:
                continue

            all_content.append(f"# {file_path.name}\n\n{result['content']}")
            all_images.extend(result['images'])
            processed_files.append(str(file_path))
        except Exception as e:
            print(f"Warning: Failed to process {file_path}: {e}", file=sys.stderr)

    combined_content = "\n\n---\n\n".join(all_content)
    combined_file = Path(output_dir) / f"{stem}.md"
    combined_file.write_text(combined_content)

    return {
        "content": combined_content,
        "images": all_images,
        "source_type": "directory",
        "source_path": dir_path,
        "processed_files": processed_files
    }


def parse_date_filter(date_str: str) -> datetime:
    date_str = date_str.lower().strip()
    now = datetime.now()

    if date_str.startswith("after "):
        date_part = date_str[6:].strip()
        return parse_flexible_date(date_part, now)

    if date_str.startswith("since "):
        date_part = date_str[6:].strip()
        return parse_flexible_date(date_part, now)

    if "last week" in date_str:
        return now - timedelta(weeks=1)
    if "last month" in date_str:
        return now - timedelta(days=30)

    if "yesterday" in date_str:
        return now - timedelta(days=1)

    return parse_flexible_date(date_str, now)


def parse_flexible_date(date_str: str, now: datetime) -> datetime:
    date_str = date_str.strip()

    month_map = {
        'jan': 1, 'january': 1, 'feb': 2, 'february': 2,
        'mar': 3, 'march': 3, 'apr': 4, 'april': 4,
        'may': 5, 'jun': 6, 'june': 6, 'jul': 7, 'july': 7,
        'aug': 8, 'august': 8, 'sep': 9, 'sept': 9, 'september': 9,
        'oct': 10, 'october': 10, 'nov': 11, 'november': 11,
        'dec': 12, 'december': 12
    }

    for name, num in month_map.items():
        if date_str.startswith(name):
            day_match = re.search(r'\d+', date_str[len(name):])
            if day_match:
                day = int(day_match.group())
                year = now.year
                try:
                    dt = datetime(year, num, day)
                    if dt > now:
                        dt = datetime(year - 1, num, day)
                    return dt
                except ValueError:
                    pass

    for sep in ['/', '-']:
        if sep in date_str:
            parts = date_str.split(sep)
            if len(parts) == 2:
                try:
                    month = int(parts[0])
                    day = int(parts[1])
                    dt = datetime(now.year, month, day)
                    if dt > now:
                        dt = datetime(now.year - 1, month, day)
                    return dt
                except ValueError:
                    pass

    return now


def extract_pasted_content(stdin_content: str, output_dir: Path,
                           stem: str = "source") -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = Path(output_dir) / f"{stem}.md"
    output_file.write_text(stdin_content)
    return {
        "content": stdin_content,
        "images": [],
        "source_type": "pasted",
        "source_path": "stdin"
    }


def extract_source(source: str, output_dir: Path, date_filter: str = None,
                   stem: str = "source") -> Dict[str, Any]:
    """Route one source to its extractor. Writes `<output_dir>/<stem>.md`."""
    output_dir = Path(output_dir)
    if source == "-":
        return extract_pasted_content(sys.stdin.read(), output_dir, stem)
    elif source.startswith(("http://", "https://")):
        return extract_url(source, output_dir, stem)
    elif Path(source).is_dir():
        return extract_directory(source, output_dir, date_filter, True, stem)
    elif Path(source).is_file():
        low = source.lower()
        if low.endswith(".pdf"):
            return extract_pdf(source, output_dir, stem)
        elif low.endswith((".txt", ".md", ".tex")):
            return extract_text(source, output_dir, stem)
        else:
            raise ValueError(f"Unsupported file type: {source}")
    else:
        raise ValueError(f"Unknown source: {source}")


def run_batch(sources: List[str], out_dir: Path, date_filter: str = None,
              manifest_full: bool = False) -> Dict[str, Any]:
    """Extract every source into its own `<out_dir>/<tag>/`, plus a manifest.

    One directory per source, not one shared directory: two lectures both export
    `media/fig_p0_0.png`, and a flat layout would have the second overwrite the
    first while both cards cite the same filename.

    Failed sources do not abort the batch -- they are recorded with an `error` in
    the manifest, because a caller extracting six lectures wants the five that
    worked, not a rollback. The failures are also listed, so nothing is silently
    missing.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    taken: set = set()
    entries = []

    for src in sources:
        tag = unique_tag(tag_for(src), taken)
        sub = out_dir / tag
        entry: Dict[str, Any] = {"tag": tag, "source_path": src, "md": f"{tag}/{tag}.md"}
        try:
            result = extract_source(src, sub, date_filter, tag)
            entry["source_type"] = result.get("source_type")
            entry["chars"] = len(str(result.get("content") or ""))
            # Count + a sample, not the full list. A 10-lecture batch produced 1,218
            # paths here = 50,884 chars of manifest, nearly all of it filenames nothing
            # reads: the card writer cites a figure by name when it uses one, and the
            # files are on disk either way. `--manifest-full` restores the complete
            # list for anyone diagnosing extraction itself.
            imgs = [f"{tag}/media/{Path(p).name}" for p in result.get("images", [])]
            entry["images"] = len(imgs)
            if manifest_full:
                entry["image_paths"] = imgs
            elif imgs:
                entry["image_sample"] = imgs[:3]
            entry["processed_files"] = result.get("processed_files", [])
        except Exception as e:
            entry["md"] = None
            entry["error"] = str(e)
            print(f"Warning: failed to extract {src}: {e}", file=sys.stderr)
        entries.append(entry)

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "output_dir": str(out_dir.resolve()),
        "sources": entries,
        "failed": [e["source_path"] for e in entries if e.get("error")],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def public_view(result: Dict[str, Any]) -> Dict[str, Any]:
    """Cap printed lists; the full data stays in the extract files on disk."""
    out = dict(result)
    images = out.get("images")
    if isinstance(images, list):
        out["images_count"] = len(images)
        out["images"] = images[:3]
    figures = out.get("figures")
    if isinstance(figures, list):
        out["figures_count"] = len(figures)
        out.pop("figures", None)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="extract_pdf.py",
        description="Extract text and images from PDF, text, URL or directory sources.",
        epilog="One source:  extract_pdf.py <source> <output_dir> [--tag NAME]   "
               "|  Batch:  extract_pdf.py --batch <src> [<src> ...] --out <dir>",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+",
                    help="<source> <output_dir>, or with --batch just the sources "
                         "('-' reads stdin)")
    ap.add_argument("--batch", action="store_true",
                    help="extract every source into <out>/<tag>/ with a manifest.json, "
                         "instead of one combined tree")
    ap.add_argument("--out", default=None,
                    help="output directory; required for --batch, and an alternative "
                         "to the positional one otherwise")
    ap.add_argument("--tag", default=None,
                    help="name for the extracted markdown (<tag>.md). Default: "
                         "source.md, or, per source, the filename stem in --batch mode")
    ap.add_argument("--date-filter", default=None, metavar="FILTER",
                    help="only take directory sources newer than this, e.g. "
                         "'after sept 11' (directory sources only)")
    ap.add_argument("--manifest-full", action="store_true",
                    help="list every extracted image path in manifest.json instead of "
                         "a count plus a 3-name sample (batch only; only needed when "
                         "diagnosing extraction itself)")
    args = ap.parse_args(argv)

    try:
        if args.batch:
            if not args.out:
                print("--batch needs --out <dir>: the batch output directory is what "
                      "the manifest and every <tag>/ directory are named against.",
                      file=sys.stderr)
                return 2
            manifest = run_batch(args.paths, Path(args.out), args.date_filter,
                                 args.manifest_full)
            for entry in manifest["sources"]:
                files = entry.get("processed_files")
                if files:
                    entry["processed_count"] = len(files)
                    entry["processed_files"] = files[:10]
            print(json.dumps(manifest, indent=2))
            return 0

        source = args.paths[0]
        if args.out:
            output_dir = Path(args.out)
        elif len(args.paths) > 1:
            output_dir = Path(args.paths[1])
        else:
            print("Usage: extract_pdf.py <source> <output_dir> [--tag NAME] "
                  "[--date-filter <filter>]", file=sys.stderr)
            return 2

        tag = args.tag or "source"
        if source == "-":
            # Kept as the caller wrote it: stdin has no name to derive a directory from.
            result = extract_pasted_content(sys.stdin.read(), output_dir, tag)
        else:
            # The pipeline calls this with a topic directory and expects a temp tree
            # under the CURRENT WORKING DIRECTORY, so a fixed path like /tmp cannot
            # produce a permission error mid-run.
            output_dir = Path.cwd() / ".anki-gen-temp" / output_dir.name
            result = extract_source(source, output_dir, args.date_filter, tag)

        result["extracted_at"] = datetime.now().isoformat(timespec="seconds")
        result["md"] = str(output_dir / f"{tag}.md")
        print(json.dumps(public_view(result)))
        return 0

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())