#!/usr/bin/env python3
"""Card media: one normal form, one path guard, one HTML snippet, one resize.

`media` in cards.json accepts either a string (legacy: file only) or
`{file, side, caption, source}`. Both the builder and the review page read the
same list here, so a string cannot mean one thing in the deck and another in
review. Attaching is opt-in at the build (`--media`); this module does not decide
whether an image is relevant, only how to carry one.

Over-cap images are downscaled with Pillow before they are dropped. Pillow is
needed only for image builds; a text-only run never imports it.
"""
from __future__ import annotations

import html
from pathlib import Path

DEFAULT_SIDE = "back"
MAX_PER_CARD = 2
MAX_BYTES = 1_000_000
MAX_PX = 1600


def items(card: dict) -> list[dict]:
    """Normalize a card's media list to [{file, side, caption, source}]."""
    out = []
    for m in card.get("media") or []:
        if isinstance(m, str):
            out.append({"file": m, "side": DEFAULT_SIDE, "caption": "", "source": ""})
        elif isinstance(m, dict) and str(m.get("file") or "").strip():
            side = str(m.get("side") or DEFAULT_SIDE).lower()
            out.append({
                "file": str(m["file"]).strip(),
                "side": side if side in ("front", "back") else DEFAULT_SIDE,
                "caption": str(m.get("caption") or "").strip(),
                "source": str(m.get("source") or "").strip(),
            })
    return out


def resolve(root, rel: str) -> Path:
    """Resolve a card-relative path and refuse anything outside the media root."""
    base = Path(root).resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError(f"media path escapes the media root: {rel!r}")
    return target


def _save_jpeg(im, out: Path, quality: int) -> None:
    im.save(out, "JPEG", quality=quality, optimize=True, progressive=True)


def prepare(path: Path, workdir: Path) -> tuple[Path | None, str]:
    """Return (path, note). A smaller within-cap file is returned untouched.

    Over-cap files are shrunk to MAX_PX and re-encoded; only a file still over
    MAX_BYTES after that is skipped (None). Any decode/save failure skips the one
    file rather than failing the build.
    """
    try:
        size = path.stat().st_size
    except OSError as e:
        return None, f"skipped: {e}"
    try:
        from PIL import Image, ImageOps
        resample = getattr(Image, "Resampling", Image).LANCZOS
    except ImportError:
        raise RuntimeError("images need Pillow: pip install pillow")
    im = None
    try:
        im = Image.open(path)
        im.load()
        im = ImageOps.exif_transpose(im)
        try:
            im.seek(0)
        except Exception:
            pass
        has_alpha = (im.mode in ("RGBA", "LA")
                     or (im.mode == "P" and "transparency" in im.info))
        width, height = im.size
        if size <= MAX_BYTES and max(width, height) <= MAX_PX:
            return path, ""
        im = im.convert("RGBA" if has_alpha else "RGB")
        im.thumbnail((MAX_PX, MAX_PX), resample)
        workdir.mkdir(parents=True, exist_ok=True)
        if has_alpha:
            out = workdir / f"{path.stem}-web.png"
            im.save(out, "PNG", optimize=True)
            if out.stat().st_size > MAX_BYTES:
                flat = Image.new("RGB", im.size, (255, 255, 255))
                flat.paste(im, mask=im.split()[-1])
                out = workdir / f"{path.stem}-web.jpg"
                _save_jpeg(flat, out, 85)
        else:
            out = workdir / f"{path.stem}-web.jpg"
            _save_jpeg(im, out, 80)
            if out.stat().st_size > MAX_BYTES:
                _save_jpeg(im, out, 60)
        if out.stat().st_size > MAX_BYTES:
            return None, (f"skipped: still {out.stat().st_size // 1000} KB "
                          f"after re-encoding")
        return out, (f"downscaled {width}x{height} -> {im.width}x{im.height}, "
                     f"{size // 1000} KB -> {out.stat().st_size // 1000} KB")
    except Exception as e:
        return None, f"skipped: {type(e).__name__}: {str(e)[:80]}"
    finally:
        if im is not None:
            try:
                im.close()
            except Exception:
                pass


def img_html(url: str, caption: str = "", missing: bool = False) -> str:
    """The one image snippet used by both the deck and the review page."""
    if missing:
        return f'<div class="media-missing">MISSING IMAGE — {html.escape(url)}</div>'
    alt = html.escape(caption or "figure", quote=True)
    cap = f'<div class="media-caption">{html.escape(caption)}</div>' if caption else ""
    return (f'<div class="media"><img src="{html.escape(url, quote=True)}" '
            f'alt="{alt}" loading="lazy"></div>{cap}')


def source_notes(items_: list[dict]) -> list[str]:
    """Compact `Image: <source>` lines for the card's existing footer."""
    return [f"Image: {m['source']}" for m in items_ if m.get("source")]
