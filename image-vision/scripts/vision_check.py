#!/usr/bin/env python3
"""Fast frame confirmation with a free-tier Gemini flash-lite model.

This is the shallow pass used before attaching a video frame: is it a usable
diagram, what does it show, and what labels are visible? The image-vision skill
is still the deep pass for relationships, handwriting, and unclear figures.

    vision_check.py frame1.png frame2.png ...

Uses GEMINI_API_KEY or ~/.config/anki-gen/gemini.key. Results are cached by
image hash, so re-running a deck does not spend the same calls again.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

MODEL = "gemini-flash-lite-latest"
RETRY_DELAYS = (2, 4, 8)
CACHE = Path(os.environ.get("ANKI_GEN_CACHE_DIR", Path.home() / ".cache" / "anki-gen")) / "vision.jsonl"
PROMPT = (
    "Read this still frame from an educational video. Return ONLY a JSON object "
    "with keys: kind (diagram, slide_text, code, photo, webpage, or talking_head), "
    "shows (at most 40 words describing what is actually shown), labels (at most "
    "12 visible labels/text, verbatim), quality (clean, cluttered, or partial), "
    "usable_as_card_image (true or false). Do not guess: if text is cut off or "
    "the frame is mostly a person, say so.")


def load_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    path = Path.home() / ".config" / "anki-gen" / "gemini.key"
    if path.is_file():
        return path.read_text().strip()
    raise SystemExit("vision_check: set GEMINI_API_KEY or write "
                     "~/.config/anki-gen/gemini.key")


def image_sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pick_model(names: list[str]) -> str | None:
    """Choose a flash-lite model from the API's model list."""
    short = [name.rsplit("/", 1)[-1] for name in names]
    lite = [name for name in short if "flash-lite" in name.lower()]
    for name in lite:
        if name.endswith("latest"):
            return name
    return lite[0] if lite else None


def parse_json_text(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return json.loads(text)


def list_models(key: str) -> list[str]:
    url = ("https://generativelanguage.googleapis.com/v1beta/models?"
           + urlencode({"key": key}))
    with urlopen(url, timeout=30) as response:
        data = json.load(response)
    return [m["name"] for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])]


def request(model: str, key: str, path: Path) -> dict:
    mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    body = {
        "contents": [{"parts": [
            {"text": PROMPT},
            {"inline_data": {"mime_type": mime,
                             "data": base64.b64encode(path.read_bytes()).decode()}},
        ]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "temperature": 0},
    }
    req = Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?"
        + urlencode({"key": key}),
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=90) as response:
        envelope = json.load(response)
    return parse_json_text(envelope["candidates"][0]["content"]["parts"][0]["text"])


def load_cache(path: Path) -> dict:
    rows = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
                rows[row["sha"]] = row
            except (KeyError, json.JSONDecodeError):
                continue
    return rows


def remember(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")


def confirm(path: Path, key: str, cache: dict, cache_path: Path) -> tuple[dict, bool]:
    sha = image_sha(path)
    if sha in cache:
        return cache[sha], True
    model, discovered = MODEL, False
    for attempt in range(3):
        try:
            result = request(model, key, path)
            row = {"file": str(path), "sha": sha, "result": result}
            cache[sha] = row
            remember(cache_path, row)
            return row, False
        except HTTPError as e:
            if e.code == 404 and not discovered:
                discovered = True
                choice = pick_model(list_models(key))
                if choice and choice != model:
                    model = choice
                    continue
            if e.code in (429, 503) and attempt < len(RETRY_DELAYS) - 1:
                time.sleep(RETRY_DELAYS[attempt])
                continue
            raise
        except (URLError, TimeoutError):
            if attempt < len(RETRY_DELAYS) - 1:
                time.sleep(RETRY_DELAYS[attempt])
                continue
            raise
    raise RuntimeError("vision_check: retries exhausted")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("images", nargs="+")
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--max", type=int, default=0,
                    help="stop after N uncached checks (0 = all supplied)")
    args = ap.parse_args()
    key = load_key()
    cache = load_cache(args.cache)
    stats = Counter()
    stopped = False
    for image in args.images:
        if args.max and stats["checked"] >= args.max:
            break
        path = Path(image)
        try:
            row, cached = confirm(path, key, cache, args.cache)
            kind = row.get("result", {}).get("kind", "?")
            usable = bool(row.get("result", {}).get("usable_as_card_image"))
            stats["cached" if cached else "checked"] += 1
            stats["usable" if usable else "unusable"] += 1
            stats[kind] += 1
            print(json.dumps({**row, "cached": cached}, ensure_ascii=False))
        except Exception as e:
            stats["errors"] += 1
            print(json.dumps({"file": str(path), "error": str(e)[:200]}))
            if "429" in str(e) or "quota" in str(e).lower():
                stopped = True
                break
    print(json.dumps({
        "checked": stats["checked"], "cached": stats["cached"],
        "usable": stats["usable"], "unusable": stats["unusable"],
        "errors": stats["errors"], "stopped": stopped,
        "kinds": {k: v for k, v in stats.items()
                  if k not in ("checked", "cached", "usable", "unusable", "errors")},
    }), file=sys.stderr)
    return 1 if stats["errors"] and not (stats["checked"] or stats["cached"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
