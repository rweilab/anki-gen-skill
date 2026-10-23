"""Adaptive dossier previews. Previews are indexes, never card media."""
from __future__ import annotations

from pathlib import Path

LINE_ART = {"diagram", "schematic", "page-crop", "slide-crop", "table",
            "figure", "frame"}


def long_edge(kind: str = "", labels=None, contact_sheet: bool = False) -> int:
    if contact_sheet:
        return 320
    count = len(labels or [])
    if count >= 8:
        return 1024
    if count >= 3 or str(kind).lower() in LINE_ART:
        return 768
    return 640


def make(src: Path, out_dir: Path, digest: str, kind: str,
         labels: list[str]) -> tuple[str, dict]:
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return "", {"error": "Pillow is not installed"}
    target = long_edge(kind, labels)
    try:
        with Image.open(src) as raw:
            im = ImageOps.exif_transpose(raw).convert("RGB")
        im.thumbnail((target, target), Image.LANCZOS)
        ext = ".png" if str(kind).lower() in LINE_ART else ".jpg"
        path = out_dir / f"{digest[:12]}_{target}{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        if ext == ".png":
            im.save(path, "PNG", optimize=True)
        else:
            im.save(path, "JPEG", quality=86, optimize=True, progressive=True)
        width, height = im.size
        return path.relative_to(out_dir.parent).as_posix(), {
            "width": width, "height": height, "target": target,
            "low_res": target > max(width, height)}
    except Exception as e:
        return "", {"error": str(e)}
