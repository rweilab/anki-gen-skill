#!/usr/bin/env python3
"""Extract text, notes, and embedded images from a PowerPoint (.pptx) source.

No Office/LibreOffice install and no slide rendering: the PPTX is a ZIP of XML,
so text and notes are read directly, and only images already embedded in the
file are copied out. Vector-only diagrams are cited, not rendered.

    extract_slides.py slides.pptx out_dir [--tag NAME]
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import visual  # noqa: E402

NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
REL_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
SLIDE = re.compile(r"ppt/slides/slide(\d+)\.xml$")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


def _texts(xml: bytes) -> list[str]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise ValueError(f"invalid slide XML: {e}") from e
    out = []
    for p in root.findall(".//a:p", NS):
        line = "".join(t.text or "" for t in p.findall(".//a:t", NS)).strip()
        if line:
            out.append(line)
    return out


def _rels(z: zipfile.ZipFile, slide: int) -> list[tuple[str, str]]:
    path = f"ppt/slides/_rels/slide{slide}.xml.rels"
    if path not in z.namelist():
        return []
    root = ET.fromstring(z.read(path))
    return [(el.get("Type", ""), el.get("Target", "")) for el in root]


def _target(target: str) -> str:
    rel = posixpath.normpath(posixpath.join("ppt/slides", target.lstrip("/")))
    return rel if rel.startswith("ppt/") else ""


def extract_pptx(pptx_path: str, output_dir: Path, stem: str = "source") -> dict:
    output_dir = Path(output_dir)
    media_dir = output_dir / "media"
    output_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(pptx_path) as z:
        slides = sorted(
            (int(m.group(1)), name) for name in z.namelist()
            if (m := SLIDE.match(name))
        )
        if not slides:
            raise ValueError(f"no slides found in {pptx_path}")

        sections, images, figures = [], [], []
        for number, name in slides:
            body = _texts(z.read(name))
            title = body[0] if body else f"Slide {number}"
            notes = []
            image_rows = []
            image_index = 0
            for rel_type, target in _rels(z, number):
                rel = _target(target)
                if not rel:
                    continue
                if "notesSlide" in Path(rel).name and rel.endswith(".xml"):
                    if rel in z.namelist():
                        notes = [t for t in _texts(z.read(rel)) if t.strip()]
                    continue
                if not rel_type.endswith("/image"):
                    continue
                ext = Path(rel).suffix.lower()
                if ext not in IMAGE_EXT or rel not in z.namelist():
                    continue
                image_index += 1
                dest = media_dir / f"slide{number:02d}_img{image_index}{ext}"
                dest.write_bytes(z.read(rel))
                metrics = visual.analyze(dest)
                quality = visual.classify(metrics)
                if quality["attach"] == "skip":
                    dest.unlink(missing_ok=True)
                    continue
                rel_path = f"media/{dest.name}"
                images.append(str(dest))
                image_rows.append({
                    "file": rel_path,
                    "page": number,
                    "slide": number,
                    "width": (metrics or {}).get("width"),
                    "height": (metrics or {}).get("height"),
                    "bytes": dest.stat().st_size,
                    "quality": quality["quality"],
                    "flags": [k for k in ("blank", "text_wall", "text_like")
                              if quality.get(k)],
                    "caption": " ".join(body[1:3])[:160],
                    "title": title,
                })
            figures.extend(image_rows)
            section = [f"## Slide {number} — {title}"]
            if len(body) > 1:
                section.append("\n".join(body[1:]))
            if notes:
                section.append("**Speaker notes:** " + " ".join(notes))
            for row in image_rows:
                section.append(f"![{row['caption'] or row['file']}]({row['file']})")
            sections.append("\n\n".join(section))

        content = f"# {stem}\n\n" + "\n\n---\n\n".join(sections) + "\n"
        md = output_dir / f"{stem}.md"
        md.write_text(content)
        (output_dir / "figures.json").write_text(json.dumps(figures, indent=2) + "\n")

    return {
        "content": content,
        "images": images,
        "figures": figures,
        "source_type": "pptx",
        "source_path": str(pptx_path),
        "md": str(md),
        "extracted_at": datetime.now().isoformat(timespec="seconds"),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pptx")
    ap.add_argument("output_dir", nargs="?")
    ap.add_argument("--out", default=None)
    ap.add_argument("--tag", default="source")
    args = ap.parse_args(argv)
    out = Path(args.out or args.output_dir or ".")
    try:
        result = extract_pptx(args.pptx, out, args.tag)
    except Exception as e:
        print(f"extract_slides.py: {e}", file=sys.stderr)
        return 2
    print(json.dumps({**result, "images_count": len(result["images"]),
                      "images": result["images"][:3]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
