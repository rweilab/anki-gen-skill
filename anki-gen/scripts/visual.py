#!/usr/bin/env python3
"""One visual-quality score for video frames and extracted figures.

The old picker ranked by OCR word count, so a wall of text beat an image-only
diagram. This scores structure instead: edge density, how concentrated those
edges are, colour, and background. Words still matter, but only as evidence of
a text wall when the structure is also flat.

Everything here is offline and depends only on Pillow. Callers supply the OCR
word count when they have one; `extract_pdf` does not need OCR.
"""
from __future__ import annotations

from pathlib import Path

# Tuned against a real 129-card video deck: good image-only diagrams had edge
# 0.014-0.021, focus 2.5-3.7, and few words. A text wall has spread-out edges
# (focus near 1) even when its edge density is high.
BLANK_EDGE = 0.005
BLANK_COLOR = 0.015
STRONG_EDGE = 0.010
STRONG_FOCUS = 1.80
STRONG_COLOR = 0.10
PLAUSIBLE_EDGE = 0.008
PLAUSIBLE_FOCUS = 1.50
PLAUSIBLE_COLOR = 0.05
TEXT_WALL_WORDS = 40
TEXT_WALL_FOCUS = 1.50
TEXT_WALL_COLOR = 0.05
TEXT_LIKE_EDGE = 0.030
TEXT_LIKE_FOCUS = 1.40
TEXT_LIKE_COLOR = 0.05


def analyze(path) -> dict | None:
    """Return visual metrics, or None when Pillow is missing/unreadable."""
    try:
        from PIL import Image, ImageFilter
    except ImportError:
        return None

    path = Path(path)
    try:
        size = path.stat().st_size
        with Image.open(path) as source:
            im = source.convert("RGB")
            width, height = im.size
            work = im.copy()
    except (OSError, ValueError):
        return None

    try:
        work.thumbnail((640, 640))
        gray = work.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)
        hist = edges.histogram()
        edge = sum(hist[32:]) / max(1, sum(hist))

        w, h = edges.size
        cells = []
        for gy in range(4):
            for gx in range(4):
                cell = edges.crop((gx * w // 4, gy * h // 4,
                                   (gx + 1) * w // 4, (gy + 1) * h // 4))
                ch = cell.histogram()
                cells.append(sum(ch[32:]) / max(1, sum(ch)))
        mean = sum(cells) / max(1, len(cells))
        focus = max(cells) / mean if mean else 1.0

        sat = work.convert("HSV").getchannel("S").histogram()
        total = max(1, sum(sat))
        # Weighted mean saturation, normalised to 0-1. Counting saturated pixels
        # instead would call a tiny coloured logo a very colourful frame.
        color = sum(i * n for i, n in enumerate(sat) if i >= 40) / (total * 255)

        small = work.resize((80, 45))
        colors = small.getcolors(maxcolors=100000) or []
        background = (max(colors)[0] / (80 * 45)) if colors else 0.0

        # 8x8 difference hash; no numpy.
        dh = im.convert("L").resize((9, 8), Image.LANCZOS)
        px = dh.load()
        bits = 0
        for y in range(8):
            for x in range(8):
                bits = (bits << 1) | (1 if px[x, y] > px[x + 1, y] else 0)

        return {
            "width": width,
            "height": height,
            "bytes": size,
            "edge": round(edge, 4),
            "focus": round(focus, 3),
            "color": round(color, 4),
            "background": round(background, 3),
            "dhash": bits,
        }
    except Exception:
        return None
    finally:
        for image in (im, work):
            try:
                image.close()
            except Exception:
                pass


def classify(metrics: dict | None, words: int | None = None,
             strong_cue: bool = False) -> dict:
    """Turn metrics into quality/attach advice.

    quality: high | medium | low
    attach:  direct | confirm | skip
    confirm means "use image-vision if available; otherwise attach only when
    the cue is explicit and the visual evidence is strong".
    """
    if not metrics:
        return {"quality": "low", "confidence": "low", "attach": "skip",
                "needs_vision": False, "blank": False, "text_wall": False,
                "text_like": False, "reason": "no metrics"}

    edge = float(metrics.get("edge", 0))
    focus = float(metrics.get("focus", 1))
    color = float(metrics.get("color", 0))
    blank = edge < BLANK_EDGE and color < BLANK_COLOR
    text_wall = (words is not None and int(words) >= TEXT_WALL_WORDS
                 and focus < TEXT_WALL_FOCUS and color < TEXT_WALL_COLOR)
    text_like = (edge >= TEXT_LIKE_EDGE and focus < TEXT_LIKE_FOCUS
                 and color < TEXT_LIKE_COLOR)
    strong = edge >= STRONG_EDGE and (focus >= STRONG_FOCUS or color >= STRONG_COLOR)
    plausible = (edge >= PLAUSIBLE_EDGE
                 and (focus >= PLAUSIBLE_FOCUS or color >= PLAUSIBLE_COLOR))

    if blank or text_wall:
        quality, reason = "low", "blank" if blank else "text wall"
    elif strong:
        quality, reason = "high", "strong visual"
    elif plausible:
        quality, reason = "medium", "plausible visual"
    else:
        quality, reason = "low", "weak visual"

    if quality == "high":
        attach = "direct"
    elif quality == "medium" and strong_cue:
        attach = "confirm"
    else:
        attach = "skip"
    return {
        "quality": quality,
        "confidence": quality,   # kept for callers that still read this name
        "attach": attach,
        "needs_vision": attach == "confirm",
        "blank": blank,
        "text_wall": text_wall,
        "text_like": text_like,
        "reason": reason,
    }


def rank(row: dict) -> tuple:
    """Order candidates; best first. Ties keep the caller's source order."""
    quality = row.get("quality") or row.get("confidence")
    strength = {"high": 2, "medium": 1}.get(quality, 0)
    edge = float(row.get("edge", 0) or 0)
    focus = float(row.get("focus", 1) or 1)
    return (
        0 if row.get("text_wall") else 1,
        strength,
        edge * focus,
        float(row.get("color", 0) or 0),
        float(row.get("background", 0) or 0),
    )


def dhash_distance(a: int, b: int) -> int:
    return (int(a) ^ int(b)).bit_count()
