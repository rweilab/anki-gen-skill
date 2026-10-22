#!/usr/bin/env python3
"""Print a compact figure index for card authoring.

Reads the `figures.json` files written by extract_pdf.py under a work directory
and prints one line per figure: relative path, page, dimensions, size, caption.
No image data, no full manifest -- this is the token-light way for a model to
choose a figure (or for a human to audit candidates).

    python3 media_index.py .anki-gen-temp/<topic>
    python3 media_index.py .anki-gen-temp/<topic> --json --limit 40
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Compact figure index for a work directory.")
    ap.add_argument("root")
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"media_index.py: not a directory: {args.root}", file=sys.stderr)
        return 2
    rows = []
    for f in sorted(root.rglob("figures.json")):
        try:
            figs = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        prefix = f.parent.relative_to(root).as_posix()
        for g in figs:
            if not isinstance(g, dict) or not g.get("file"):
                continue
            rows.append({
                "path": f"{prefix}/{g['file']}",
                "page": g.get("page"),
                "width": g.get("width"),
                "height": g.get("height"),
                "bytes": g.get("bytes"),
                "quality": g.get("quality") or "unknown",
                "flags": g.get("flags") or [],
                "caption": g.get("caption") or "",
                "title": g.get("title") or "",
            })
    quality_rank = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
    rows.sort(key=lambda r: (quality_rank.get(r["quality"], 3),
                             r["page"] or 0, r["path"]))
    if args.limit > 0:
        rows = rows[:args.limit]
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    for r in rows:
        kb = (r["bytes"] or 0) / 1000
        dim = f'{r["width"]}x{r["height"]}' if r["width"] else "?"
        cap = r["caption"][:60]
        title = r["title"][:50]
        flags = ",".join(r["flags"])
        print(f'{r["path"]}  p{r["page"]}  {dim}  {kb:.0f}KB  '
              f'{r["quality"]}  {flags}  {title}  {cap}')
    if not rows:
        print("no figures found", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
