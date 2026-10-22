#!/usr/bin/env python3
"""
Extract text and images from PDF, text, URL, or directory sources.
Uses: pdftotext, pymupdf (fitz), tesseract, curl, pandoc; .pptx is routed to
extract_slides.py (no Office).

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
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from typing import Dict, Any, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_paths import ensure_tool_paths  # noqa: E402
ensure_tool_paths()
import visual  # noqa: E402

# Tiny logos and blank page fills are never useful card images. Keep this
# conservative: a small but meaningful diagram should still survive.
MIN_PX = 96
MIN_BYTES = 4000
CAPTION_RE = re.compile(
    r"^\s*(Figure|Fig\.?|Table|Scheme|Exhibit|Panel)\s*\d", re.I)
PAGE_CROP_DPI = 150
MAX_PAGE_CROPS = 120


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


def _text_blocks(page) -> list[tuple]:
    """Line-level (x0, y0, x1, y1, text) tuples.

    Block-level text merges adjacent captions ("Figure 1 ... Figure 2 ..."), so
    two figures get the same caption. Line spans keep each caption separate and
    give a tighter bbox for association.
    """
    try:
        data = page.get_text("dict")
    except Exception:
        return []
    out = []
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(str(s.get("text", "")) for s in line.get("spans", [])).strip()
            if text:
                x0, y0, x1, y1 = line.get("bbox", (0, 0, 0, 0))
                out.append((x0, y0, x1, y1, text))
    return out


def _caption(blocks: list[tuple], bbox: tuple) -> tuple[str, tuple | None]:
    """Nearest short text block, preferring a real Figure/Table caption."""
    x0, y0, x1, y1 = bbox
    candidates = []
    for b in blocks:
        text = " ".join(str(b[4]).split())
        if len(text) < 3 or len(text) > 220 or re.fullmatch(r"\d+", text):
            continue
        bx0, by0, bx1, by1 = (float(v) for v in b[:4])
        dx = 0.0 if bx1 >= x0 and bx0 <= x1 else min(abs(bx0 - x1), abs(x0 - bx1))
        dy = min(abs(by0 - y1), abs(y0 - by1))
        distance = dx + dy
        rank = (0 if CAPTION_RE.match(text) else 1, distance, text,
                (bx0, by0, bx1, by1))
        candidates.append(rank)
    if not candidates:
        return "", None
    _, _, text, box = min(candidates, key=lambda c: (c[0], c[1]))
    return text, box


def _nearby_text(blocks: list[tuple], bbox: tuple, caption_box=None) -> str:
    x0, y0, x1, y1 = bbox
    parts = []
    for b in blocks:
        text = " ".join(str(b[4]).split())
        if not text:
            continue
        box = tuple(float(v) for v in b[:4])
        if caption_box and box == caption_box:
            continue
        if min(abs(box[1] - y1), abs(y0 - box[3])) > 180:
            continue
        parts.append(text)
    return " ".join(parts)[:500]


def _drawing_bbox(page):
    """Union of non-background drawing rects, or None when the page is text-only."""
    rects = []
    page_area = max(1.0, page.rect.width * page.rect.height)
    try:
        drawings = page.get_drawings()
    except Exception:
        return None
    for d in drawings:
        rect = d.get("rect")
        if rect is None:
            continue
        area = max(0.0, rect.width) * max(0.0, rect.height)
        if area > page_area * 0.85:          # full-page fill/background
            continue
        rects.append(rect)
    if len(rects) < 3:
        return None
    x0 = min(r.x0 for r in rects)
    y0 = min(r.y0 for r in rects)
    x1 = max(r.x1 for r in rects)
    y1 = max(r.y1 for r in rects)
    if (x1 - x0) * (y1 - y0) < page_area * 0.01:
        return None
    return (x0 - 10, y0 - 10, x1 + 10, y1 + 10)


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


def _figure_entry(img_path: Path, page: int, kind: str, bbox, caption: str,
                  caption_box, nearby: str, heading: str, source: str,
                  seen_hashes: set, attach: str | None = None) -> dict | None:
    metrics = visual.analyze(img_path)
    digest = hashlib.sha256(img_path.read_bytes()).hexdigest()
    if digest in seen_hashes:
        img_path.unlink(missing_ok=True)
        return None
    seen_hashes.add(digest)
    entry = {
        "file": f"media/{img_path.name}", "page": page, "kind": kind,
        "bbox": [round(float(v), 1) for v in bbox] if bbox else None,
        "caption": caption, "caption_bbox": (
            [round(float(v), 1) for v in caption_box] if caption_box else None),
        "nearby_text": nearby, "heading": heading, "title": heading,
        "source": source, "width": (metrics or {}).get("width"),
        "height": (metrics or {}).get("height"),
        "bytes": img_path.stat().st_size, "sha256": digest,
    }
    if metrics is None:
        entry.update({"quality": "unknown", "flags": []})
        entry["attach"] = attach or "confirm"
        return entry
    q = visual.classify(metrics)
    flags = [name for name in ("blank", "text_wall", "text_like") if q.get(name)]
    entry.update({
        "quality": q["quality"], "flags": flags,
        "edge": metrics["edge"], "focus": metrics["focus"],
        "color": metrics["color"], "background": metrics["background"],
        "attach": attach or q["attach"],
    })
    return entry


def extract_pdf(pdf_path: str, output_dir: Path, stem: str = "source",
                page_crops: str = "auto") -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    media_dir = Path(output_dir) / "media"
    media_dir.mkdir(exist_ok=True)

    text_file = Path(output_dir) / f"{stem}.md"
    text_content = _pdf_text(pdf_path)
    if not text_content.strip():
        print(f"Warning: {pdf_path} has no text layer (likely a scanned or "
              f"handwritten PDF); the extracted text will be empty", file=sys.stderr)
    text_file.write_text(text_content)

    images, figures = [], []
    seen_hashes = set()
    dropped = crops = 0
    fitz = _fitz()
    if fitz is not None:
        try:
            # _quiet(): pymupdf's C layer prints parse warnings to stdout, which is
            # where the caller's JSON lives. See the note at the top of this file.
            with _quiet():
                doc = fitz.open(pdf_path)
                try:
                    for page_num in range(len(doc)):
                        page = doc[page_num]
                        page_no = page_num + 1
                        blocks = _text_blocks(page)
                        heading = _page_title(page)
                        source = f"{Path(pdf_path).name} p.{page_no}"
                        images_list = page.get_images(full=True)
                        for img_idx, img in enumerate(images_list):
                            try:
                                xref = img[0]
                                bbox = tuple(page.get_image_bbox(img))
                                pix = fitz.Pixmap(doc, xref)
                                if pix.n >= 5:
                                    pix = fitz.Pixmap(fitz.csRGB, pix)
                                img_path = media_dir / f"fig_p{page_no}_{img_idx}.png"
                                pix.save(str(img_path))
                                width, height = pix.width, pix.height
                                size = img_path.stat().st_size
                                if (width < MIN_PX or height < MIN_PX
                                        or size < MIN_BYTES):
                                    img_path.unlink(missing_ok=True)
                                    dropped += 1
                                    continue
                                cap, cap_box = _caption(blocks, bbox)
                                entry = _figure_entry(
                                    img_path, page_no, "embedded", bbox, cap,
                                    cap_box, _nearby_text(blocks, bbox, cap_box),
                                    heading, source, seen_hashes)
                                if entry is None:
                                    dropped += 1
                                    continue
                                images.append(str(img_path))
                                figures.append(entry)
                            except Exception as e:
                                print(f"extract_pdf.py: figure skip {pdf_path} "
                                      f"p.{page_no}: {e}", file=sys.stderr)

                        if page_crops == "off" or crops >= MAX_PAGE_CROPS:
                            continue
                        draw_box = _drawing_bbox(page)
                        cap, cap_box = _caption(
                            blocks, (page.rect.x0, page.rect.y0,
                                     page.rect.x1, page.rect.y1))
                        slide_like = (page.rect.width > page.rect.height
                                      and len(page.get_text().strip()) < 2200)
                        cap_like = bool(cap and CAPTION_RE.match(cap))
                        want = (page_crops == "all" and (draw_box or cap_like)) or \
                               (slide_like and draw_box) or \
                               (cap_like and bool(draw_box) and not images_list)
                        if not want:
                            continue
                        if draw_box:
                            x0, y0, x1, y1 = draw_box
                        elif cap_box:
                            x0, y0, x1, y1 = (0, 0, page.rect.width, cap_box[1] - 4)
                        else:
                            continue
                        rect = fitz.Rect(max(0, x0), max(0, y0),
                                         min(page.rect.width, x1),
                                         min(page.rect.height, y1))
                        if rect.width < 80 or rect.height < 60:
                            continue
                        try:
                            pix = page.get_pixmap(clip=rect, dpi=PAGE_CROP_DPI)
                            kind = "slide-crop" if slide_like else "page-crop"
                            crop_path = media_dir / f"{kind}_p{page_no}_{crops}.png"
                            pix.save(str(crop_path))
                            entry = _figure_entry(
                                crop_path, page_no, kind,
                                (rect.x0, rect.y0, rect.x1, rect.y1), cap, cap_box,
                                _nearby_text(blocks, (rect.x0, rect.y0,
                                                      rect.x1, rect.y1), cap_box),
                                heading, source, seen_hashes, attach="confirm")
                            if entry is None:
                                continue
                            images.append(str(crop_path))
                            figures.append(entry)
                            crops += 1
                        except Exception as e:
                            print(f"extract_pdf.py: page crop skip {pdf_path} "
                                  f"p.{page_no}: {e}", file=sys.stderr)
                finally:
                    doc.close()
        except Exception as e:
            print(f"Image extraction warning: {e}", file=sys.stderr)
    if dropped:
        print(f"extract_pdf.py: skipped {dropped} tiny/duplicate image(s) "
              f"in {pdf_path}", file=sys.stderr)

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


def _web_src(img) -> str:
    src = img.get("data-src") or img.get("src")
    if str(src or "").startswith("data:"):
        src = img.get("data-original") or img.get("data-src") or src
    if not src and img.get("srcset"):
        src = str(img["srcset"]).split(",", 1)[0].strip().split(" ", 1)[0]
    return str(src or "").strip()


def _web_ext(content_type: str, image_url: str) -> str:
    ext = {
        "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
        "image/gif": ".gif", "image/bmp": ".bmp",
    }.get((content_type or "").lower())
    if ext:
        return ext
    suffix = Path(urlsplit(image_url).path).suffix.lower()
    return suffix if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"} else ""


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

    images, figures = [], []
    seen_hashes = set()
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for i, img in enumerate(soup.find_all("img")):
            src = _web_src(img)
            if not src or src.startswith(("data:", "javascript:")):
                continue
            image_url = urljoin(url, src)
            try:
                req = Request(image_url, headers={"User-Agent": "anki-gen/1.4.1"})
                with urlopen(req, timeout=15) as response:
                    data = response.read(2_000_001)
                    content_type = response.headers.get_content_type()
            except Exception as e:
                print(f"extract_pdf.py: web image skip {image_url}: {e}",
                      file=sys.stderr)
                continue
            if len(data) > 2_000_000:
                print(f"extract_pdf.py: web image over 2 MB skipped: {image_url}",
                      file=sys.stderr)
                continue
            if len(data) < 2000:                 # icons, spacers, tracking pixels
                continue
            ext = _web_ext(content_type, image_url)
            if not ext:                         # SVG/icons are not Anki images
                continue
            img_path = media_dir / f"web_img_{i}{ext}"
            img_path.write_bytes(data)
            figure = img.find_parent("figure")
            caption = ""
            if figure:
                node = figure.find("figcaption")
                caption = node.get_text(" ", strip=True) if node else ""
            caption = (caption or img.get("alt") or img.get("title") or "").strip()
            heading = ""
            node = img.find_previous(lambda t: t.name in ("h1", "h2", "h3", "h4"))
            if node:
                heading = node.get_text(" ", strip=True)
            parent = img.parent
            nearby = (parent.get_text(" ", strip=True) if parent else "")[:500]
            entry = _figure_entry(
                img_path, 0, "web", None, caption, None, nearby, heading,
                url, seen_hashes, attach="confirm")
            if entry is None:
                continue
            entry["source_url"] = image_url
            images.append(str(img_path))
            figures.append(entry)
    except Exception as e:
        print(f"extract_pdf.py: web figure extraction failed: {e}", file=sys.stderr)

    (Path(output_dir) / "figures.json").write_text(json.dumps(figures, indent=2) + "\n")
    return {
        "content": md,
        "images": images,
        "figures": figures,
        "source_type": "url",
        "source_path": url
    }


def extract_directory(dir_path: str, output_dir: Path, date_filter: str = None,
                      recursive: bool = True, stem: str = "source",
                      page_crops: str = "auto") -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    media_dir = Path(output_dir) / "media"
    media_dir.mkdir(exist_ok=True)

    cutoff_time = None
    if date_filter:
        cutoff_time = parse_date_filter(date_filter)

    exts = {'.pdf', '.pptx', '.txt', '.md', '.tex', '.html', '.htm'}

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
                result = extract_pdf(str(file_path), output_dir / file_path.stem,
                                     page_crops=page_crops)
            elif file_path.suffix.lower() == '.pptx':
                from extract_slides import extract_pptx
                result = extract_pptx(str(file_path), output_dir / file_path.stem,
                                      file_path.stem)
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

    m = re.search(r"\blast\s+(\d+)\s*(day|week|month)s?\b", date_str)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        return now - (timedelta(days=n) if unit == "day" else
                      timedelta(weeks=n) if unit == "week" else
                      timedelta(days=30 * n))
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

    raise ValueError(f"could not parse date filter: {date_str!r}; try "
                     "'after sept 11', 'last week', or 'last 7 days'")


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
                   stem: str = "source", page_crops: str = "auto") -> Dict[str, Any]:
    """Route one source to its extractor. Writes `<output_dir>/<stem>.md`."""
    output_dir = Path(output_dir)
    if source == "-":
        return extract_pasted_content(sys.stdin.read(), output_dir, stem)
    elif source.startswith(("http://", "https://")):
        return extract_url(source, output_dir, stem)
    elif Path(source).is_dir():
        return extract_directory(source, output_dir, date_filter, True, stem,
                                 page_crops)
    elif Path(source).is_file():
        low = source.lower()
        if low.endswith(".pdf"):
            return extract_pdf(source, output_dir, stem, page_crops)
        elif low.endswith(".pptx"):
            from extract_slides import extract_pptx
            return extract_pptx(source, output_dir, stem)
        elif low.endswith((".txt", ".md", ".tex")):
            return extract_text(source, output_dir, stem)
        elif low.endswith((".html", ".htm")):
            return extract_url(Path(source).resolve().as_uri(), output_dir, stem)
        else:
            raise ValueError(f"Unsupported file type: {source}")
    else:
        raise ValueError(f"Unknown source: {source}")


def run_batch(sources: List[str], out_dir: Path, date_filter: str = None,
              manifest_full: bool = False, page_crops: str = "auto") -> Dict[str, Any]:
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
            result = extract_source(src, sub, date_filter, tag, page_crops)
            entry["source_type"] = result.get("source_type")
            entry["chars"] = len(str(result.get("content") or ""))
            # Count + a sample, not the full list. A 10-lecture batch produced 1,218
            # paths here = 50,884 chars of manifest, nearly all of it filenames nothing
            # reads: the card writer cites a figure by name when it uses one, and the
            # files are on disk either way. `--manifest-full` restores the complete
            # list for anyone diagnosing extraction itself.
            imgs = [f"{tag}/media/{Path(p).name}" for p in result.get("images", [])]
            if not str(result.get("content") or "").strip() and not imgs:
                raise ValueError("no text or images extracted")
            if not str(result.get("content") or "").strip():
                entry["warning"] = ("no text layer; figures are available but "
                                    "need image-vision to build cards")
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
        description="Extract text and images from PDF, PPTX, text, URL or directory sources.",
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
    ap.add_argument("--page-crops", choices=("auto", "all", "off"), default="auto",
                    help="render vector/slide figures as page crops (default: auto, "
                         "captioned pages and slide-like pages only)")
    args = ap.parse_args(argv)

    try:
        if args.batch:
            if not args.out:
                print("--batch needs --out <dir>: the batch output directory is what "
                      "the manifest and every <tag>/ directory are named against.",
                      file=sys.stderr)
                return 2
            manifest = run_batch(args.paths, Path(args.out), args.date_filter,
                                 args.manifest_full, args.page_crops)
            for entry in manifest["sources"]:
                files = entry.get("processed_files")
                if files:
                    entry["processed_count"] = len(files)
                    entry["processed_files"] = files[:10]
            print(json.dumps(manifest, indent=2))
            return 0

        source = args.paths[0]
        explicit_out = args.out is not None
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
            # A positional directory keeps the historical .anki-gen-temp layout;
            # an explicit --out is the caller's path and is honoured as written.
            if not explicit_out:
                output_dir = Path.cwd() / ".anki-gen-temp" / output_dir.name
            result = extract_source(source, output_dir, args.date_filter, tag,
                                    args.page_crops)

        result["extracted_at"] = datetime.now().isoformat(timespec="seconds")
        result["md"] = str(output_dir / f"{tag}.md")
        print(json.dumps(public_view(result)))
        return 0

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())