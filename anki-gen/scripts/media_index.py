#!/usr/bin/env python3
"""Print a compact figure/frame index for card authoring.

Reads the `figures.json` files written by extract_pdf/extract_slides and the
`frames.jsonl` written by frames.py. No image data, no full manifest -- this is
the token-light way for a model to choose a figure.

    python3 media_index.py .anki-gen-temp/<topic>
    python3 media_index.py .anki-gen-temp/<topic> --cards cards.jsonl --per-card 3
    python3 media_index.py .anki-gen-temp/<topic> --json --limit 40
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cardid import load_cards  # noqa: E402

STOP = {"the", "and", "for", "with", "that", "this", "from", "what", "why",
        "how", "does", "are", "was", "were", "into", "one", "two", "its"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{3,}", text.lower()) if w not in STOP}


def _vision(root: Path) -> dict[str, dict]:
    out = {}
    for f in sorted(root.rglob("vision*.jsonl")):
        try:
            lines = f.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            result = row.get("result")
            if isinstance(result, dict) and row.get("file"):
                out[Path(row["file"]).name] = result
    return out


def _vision_fields(vision: dict[str, dict], path) -> dict:
    result = vision.get(Path(str(path or "")).name)
    if not result:
        return {}
    return {"vision_kind": result.get("kind", ""),
            "vision_usable": result.get("usable_as_card_image"),
            "vision_shows": result.get("shows", ""),
            "vision_labels": result.get("labels", [])}


def _rows(root: Path, *, include_risky: bool = False) -> list[dict]:
    rows = []
    vision = _vision(root)
    for f in sorted(root.rglob("figures.json")):
        try:
            figs = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        prefix = f.parent.relative_to(root).as_posix()
        for g in figs:
            if not isinstance(g, dict) or not g.get("file"):
                continue
            path = f"{prefix}/{g['file']}" if prefix != "." else g["file"]
            rows.append({
                "path": path, "kind": g.get("kind") or "figure",
                "page": g.get("page"), "slide": g.get("slide"),
                "width": g.get("width"), "height": g.get("height"),
                "bytes": g.get("bytes"), "quality": g.get("quality") or "unknown",
                "flags": g.get("flags") or [], "caption": g.get("caption") or "",
                "title": g.get("heading") or g.get("title") or "",
                "nearby_text": g.get("nearby_text") or "",
                "source": g.get("source") or "",
                "source_url": g.get("source_url") or "",
                "attach": g.get("attach") or "",
                "title_like": False,
                **_vision_fields(vision, g.get("file")),
            })
    for f in sorted(root.rglob("frames.jsonl")):
        try:
            lines = f.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not r.get("best") or r.get("attach") not in ("direct", "confirm"):
                continue
            rows.append({
                "path": r.get("file", ""), "kind": "frame",
                "page": None, "slide": None, "width": None, "height": None,
                "bytes": None, "quality": r.get("quality") or "unknown",
                "flags": [], "caption": r.get("caption") or "",
                "title": r.get("timecode") or "",
                "nearby_text": "", "source": r.get("source") or "",
                "source_url": r.get("source_url") or "",
                "attach": r.get("attach") or "",
                "canonical": bool(r.get("canonical")),
                "title_like": bool(r.get("title_like")),
                "ocr_sample": r.get("ocr_sample", ""),
                **_vision_fields(vision, r.get("file")),
            })
    if include_risky:
        return rows
    return [row for row in rows
            if row.get("attach") != "skip" and not row.get("title_like")]


def _rank(row: dict) -> tuple:
    quality = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
    return (quality.get(row["quality"], 3), row["page"] or 0, row["path"])


def _score(card: dict, row: dict) -> tuple[float, list[str]]:
    csource = str(card.get("source") or card.get("source_ref") or "").lower()
    rsource = str(row.get("source") or "").lower()
    reasons = []
    loc = 0
    page = row.get("page") or row.get("slide")
    if rsource and (rsource in csource or csource in rsource):
        loc = max(loc, 2)
        reasons.append("same source")
    if page and re.search(rf"\b(?:p|page|slide)\.?\s*{page}\b", csource):
        loc = max(loc, 3)
        reasons.append(f"same page/slide {page}")
    if row["path"] and Path(row["path"]).stem.lower() in csource:
        loc = max(loc, 2)
        reasons.append("same file")
    ctext = " ".join(str(card.get(k) or "") for k in ("topic", "front", "back"))
    rtext = " ".join(str(row.get(k) or "") for k in
                     ("caption", "title", "nearby_text", "source"))
    cw, rw = _words(ctext), _words(rtext)
    overlap = len(cw & rw) / max(1, len(cw))
    matches = len(cw & rw)
    if overlap >= 0.08:
        reasons.append(f"{matches} matching word(s)")
    quality = {"high": 3, "medium": 2, "low": 1}.get(row["quality"], 0)
    if row.get("vision_kind") == "diagram":
        quality += 3
        reasons.append("vision: diagram")
    elif row.get("vision_kind") in ("code", "webpage"):
        quality -= 1
        reasons.append(f"vision: {row['vision_kind']}")
    if row.get("vision_usable") is False:
        quality -= 4
        reasons.append("vision: unusable")
    if row.get("canonical"):
        quality += 1
        reasons.append("canonical frame")
    if matches < 2:
        quality -= 2
        reasons.append("weak caption match")
    if row.get("title_like"):
        quality -= 6
        reasons.append("title/outline")
    if row.get("attach") == "confirm" and not row.get("vision_usable"):
        quality -= 6
        reasons.append("needs vision")
    return loc * 4 + overlap * 3 + quality, reasons


def _line(row: dict) -> str:
    page = row.get("page") or row.get("slide")
    dim = f'{row["width"]}x{row["height"]}' if row.get("width") else "?"
    kb = (row["bytes"] or 0) / 1000
    loc = f"p{page}" if page else "-"
    vision = row.get("vision_kind")
    vis = f'  vision={vision}' if vision else ""
    shows = f'  {row.get("vision_shows", "")[:50]}' if row.get("vision_shows") else ""
    return (f'{row["path"]}  {loc}  {dim}  {kb:.0f}KB  {row["quality"]}  '
            f'{row.get("attach", "")}  {",".join(row["flags"])}  '
            f'{row["title"][:50]}  {row["caption"][:60]}{vis}{shows}')


def audit_cards(cards: list[dict], root) -> list[dict]:
    """Return media choices that are obviously unsafe to attach."""
    root = Path(root)
    rows = _rows(root, include_risky=True)
    by_path = {row["path"]: row for row in rows}
    risks = []
    for n, card in enumerate(cards, 1):
        front = str(card.get("front") or "")
        media = card.get("media") or []
        has_front = any(isinstance(m, dict)
                        and str(m.get("side") or "back").lower() == "front"
                        for m in media)
        if (re.search(r"\b(the|this|that)\s+(slide|circuit|figure|diagram|graph|example)|"
                      r"slide's example|shown\s+(above|below)", front, re.I)
                and not has_front):
            risks.append({"card": n, "file": "", "risk": "front reference without front media"})
        for item in media:
            path = str(item.get("file") if isinstance(item, dict) else item)
            row = by_path.get(path)
            if row is None:
                continue
            if row.get("title_like"):
                risks.append({"card": n, "file": path, "risk": "title/outline image"})
            if row.get("attach") == "confirm" and not row.get("vision_usable"):
                risks.append({"card": n, "file": path, "risk": "confirm crop without vision"})
            if row.get("attach") == "skip":
                risks.append({"card": n, "file": path, "risk": "candidate marked skip"})
            caption = str(item.get("caption") if isinstance(item, dict) else "")
            if re.search(r"\b(lecture|outline|agenda|intro|title|overview)\b",
                         caption, re.I):
                risks.append({"card": n, "file": path, "risk": "generic caption"})
    return risks


def main() -> int:
    ap = argparse.ArgumentParser(description="Compact figure/frame index.")
    ap.add_argument("root")
    ap.add_argument("--limit", type=int, default=40,
                    help="flat-index cap; 0 = all")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cards", default=None,
                    help="rank candidates per card instead of a flat index")
    ap.add_argument("--per-card", type=int, default=2)
    ap.add_argument("--all-cards", action="store_true",
                    help="rank every card, including cards that already have media")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"media_index.py: not a directory: {args.root}", file=sys.stderr)
        return 2
    rows = sorted(_rows(root), key=_rank)
    if args.limit > 0 and not args.cards:
        rows = rows[:args.limit]

    if args.cards:
        cards = load_cards(args.cards)
        out = []
        for n, c in enumerate(cards, 1):
            if c.get("media") and not args.all_cards:
                continue
            ranked = []
            for row in rows:
                score, reasons = _score(c, row)
                if score > 0:
                    ranked.append((score, row, reasons))
            ranked.sort(key=lambda t: t[0], reverse=True)
            picks = [{"score": round(s, 2), "reasons": why, **row}
                     for s, row, why in ranked[:max(1, args.per_card)]]
            out.append({"card": n, "topic": c.get("topic", ""),
                        "candidates": picks})
        if args.json:
            print(json.dumps(out, indent=2))
            return 0
        for item in out:
            print(f'card {item["card"]}  [{item["topic"]}]')
            if not item["candidates"]:
                print("  no candidate")
            for cand in item["candidates"]:
                print(f'  {cand["score"]:>5}  {_line(cand)}'
                      + (f'  ({"; ".join(cand["reasons"])})'
                         if cand["reasons"] else ""))
        return 0

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    for row in rows:
        print(_line(row))
    if not rows:
        print("no figures found", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
