#!/usr/bin/env python3
"""Fast frame/figure confirmation with a free-tier Gemini flash-lite model.

This is the shallow pass used before attaching a frame or figure: is it a usable
image, what does it show, and what labels are visible? The image-vision skill is
still the deep pass for relationships, handwriting, and unclear figures.

    vision_check.py frame1.png frame2.png ... --report vision.jsonl

Uses GEMINI_API_KEY or ~/.config/anki-gen/gemini.key. Results are cached by image
hash + mode + prompt version, so re-running a deck does not spend the same calls
again. Every result is flushed to stdout and to the report as it completes.
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

PROMPT_VERSION = "vision-check-2"
DEFAULT_MODEL = "gemini-flash-lite-latest"
API_VERSION = os.environ.get("GEMINI_API_VERSION", "v1beta")
RETRY_DELAYS = (1, 2)
DEFAULT_DELAY = 12.0          # 5 RPM, below the free-tier flash-lite burst limit
MODEL_TTL = 7 * 24 * 3600
CACHE = Path(os.environ.get("ANKI_GEN_CACHE_DIR", Path.home() / ".cache" / "anki-gen")) / "vision.jsonl"
MODEL_CACHE = CACHE.parent / "vision-models.json"
PROMPT_FRAME = (
    "Read this still frame from an educational video. Return ONLY a JSON object "
    "with keys: kind (diagram, slide_text, code, photo, webpage, or talking_head), "
    "shows (at most 40 words describing what is actually shown), labels (at most "
    "12 visible labels/text, verbatim), quality (clean, cluttered, or partial), "
    "usable_as_card_image (true or false). Do not guess: if text is cut off or "
    "the frame is mostly a person, say so.")
PROMPT_FIGURE = (
    "Read this textbook or lecture figure. Return ONLY a JSON object with keys: "
    "kind (diagram, graph, table, photo, or slide), shows (at most 40 words), "
    "labels (at most 12 visible labels/text, verbatim), quality (clean, cluttered, "
    "or partial), usable_as_card_image (true or false). Do not solve the problem "
    "and do not invent labels.")


class RateLimited(RuntimeError):
    pass


def prompt(mode: str, caption: str = "") -> str:
    base = PROMPT_FIGURE if mode == "figure" else PROMPT_FRAME
    return f"{base}\nCaption/context: {caption}" if caption else base


def load_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    path = Path.home() / ".config" / "anki-gen" / "gemini.key"
    if path.is_file():
        lines = path.read_text().splitlines()
        if lines and lines[0].strip():
            return lines[0].strip()
    raise SystemExit("vision_check: set GEMINI_API_KEY or write "
                     "~/.config/anki-gen/gemini.key")


def image_sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cache_key(sha: str, mode: str) -> str:
    return f"{sha}:{mode}:{PROMPT_VERSION}"


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
    url = (f"https://generativelanguage.googleapis.com/{API_VERSION}/models?"
           + urlencode({"key": key}))
    with urlopen(url, timeout=20) as response:
        data = json.load(response)
    return [m["name"] for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])]


def resolve_model(key: str, requested: str | None = None,
                  force: bool = False) -> str:
    """Resolve a flash-lite model; cache the discovered list for a week."""
    if requested and requested != "auto":
        return requested
    env = os.environ.get("GEMINI_VISION_MODEL")
    if env:
        return env
    now = time.time()
    cached = {}
    if MODEL_CACHE.is_file() and not force:
        try:
            cached = json.loads(MODEL_CACHE.read_text())
        except (OSError, json.JSONDecodeError):
            cached = {}
    if cached.get("at") and now - float(cached["at"]) < MODEL_TTL:
        choice = pick_model(cached.get("models") or [])
        if choice:
            return choice
    if not force:
        # Try the documented alias first; only a 404 pays for discovery. This
        # keeps the normal path offline and avoids a model-list call per run.
        return DEFAULT_MODEL
    models = list_models(key)
    MODEL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    MODEL_CACHE.write_text(json.dumps({"at": now, "models": models}) + "\n")
    choice = pick_model(models)
    if not choice:
        raise RuntimeError("vision_check: no flash-lite model found; refusing "
                           "to fall back to a paid/high-quota model")
    return choice


def request(model: str, key: str, path: Path, mode: str = "frame",
            caption: str = "", timeout: float = 20) -> dict:
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif"}.get(
                path.suffix.lower(), "image/png")
    body = {
        "contents": [{"parts": [
            {"text": prompt(mode, caption)},
            {"inline_data": {"mime_type": mime,
                             "data": base64.b64encode(path.read_bytes()).decode()}},
        ]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "temperature": 0},
    }
    req = Request(
        f"https://generativelanguage.googleapis.com/{API_VERSION}/models/{model}:"
        "generateContent?" + urlencode({"key": key}),
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=timeout) as response:
        envelope = json.load(response)
    return parse_json_text(envelope["candidates"][0]["content"]["parts"][0]["text"])


def load_cache(path: Path) -> dict:
    rows = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = row.get("key") or row.get("sha")
            if key:
                rows[key] = row
    return rows


def remember(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def confirm(path: Path, key: str, cache: dict, cache_path: Path,
            mode: str = "frame", caption: str = "", model: str | None = None,
            timeout: float = 20, retries: int = 2, delay: float = 0.5,
            retry_429: bool = False) -> tuple[dict, bool]:
    sha = image_sha(path)
    ckey = cache_key(sha, mode)
    if ckey in cache:
        return cache[ckey], True
    if sha in cache:                         # legacy cache row
        return cache[sha], True
    model = model or resolve_model(key)
    attempts = max(0, retries) + 1
    for attempt in range(attempts):
        try:
            started = time.monotonic()
            result = request(model, key, path, mode, caption, timeout)
            row = {"file": str(path), "sha": sha, "key": ckey, "mode": mode,
                   "model": model, "prompt_version": PROMPT_VERSION,
                   "elapsed": round(time.monotonic() - started, 2),
                   "result": result}
            cache[ckey] = row
            remember(cache_path, row)
            return row, False
        except HTTPError as e:
            if e.code == 429:
                message = (f"429 rate limit for {model}; Gemini free-tier RPM/RPD "
                           "may be exhausted. Check the dashboard, use a flash-lite "
                           "model, lower --max, or retry later")
                if not retry_429 or attempt + 1 >= attempts:
                    raise RateLimited(message) from e
                # One bounded retry at a slower rate, then stop. Never loop.
                time.sleep(max(delay * 2, DEFAULT_DELAY))
                continue
            if e.code == 404:
                try:
                    model = resolve_model(key, force=True)
                except Exception:
                    raise
                if attempt + 1 < attempts:
                    continue
            if e.code == 503 and attempt + 1 < attempts:
                time.sleep(delay)
                continue
            raise
        except (URLError, TimeoutError):
            if attempt + 1 < attempts:
                time.sleep(delay)
                continue
            raise
    raise RuntimeError("vision_check: retries exhausted")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("images", nargs="+")
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--report", type=Path, default=CACHE.parent / "vision-report.jsonl",
                    help="per-image report written incrementally")
    ap.add_argument("--max", type=int, default=0,
                    help="stop after N uncached checks (0 = all supplied)")
    ap.add_argument("--mode", choices=("frame", "figure"), default="frame")
    ap.add_argument("--caption", default="", help="figure caption/context")
    ap.add_argument("--model", default=None,
                    help="flash-lite model; default env/discovery")
    ap.add_argument("--timeout", type=float, default=20,
                    help="seconds per image request")
    ap.add_argument("--max-seconds", type=float, default=600,
                    help="global deadline; stop with a partial report")
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                    help="pause between uncached calls; 12s ~= 5 RPM")
    ap.add_argument("--retries", type=int, default=2,
                    help="retries for transient 503/network errors")
    ap.add_argument("--retry-429", action="store_true",
                    help="retry a 429 once at a doubled delay, then stop")
    ap.add_argument("--stop-after-errors", type=int, default=2)
    args = ap.parse_args()
    key = load_key()
    cache = load_cache(args.cache)
    stats = Counter()
    stopped = ""
    start = time.monotonic()
    try:
        model = resolve_model(key, args.model)
    except Exception as e:
        print(json.dumps({"error": str(e), "stopped": "model"}), flush=True)
        return 2
    for image in args.images:
        if time.monotonic() - start > args.max_seconds:
            stopped = "deadline"
            break
        if args.max and stats["checked"] >= args.max:
            stopped = "max"
            break
        if stats["errors"] >= args.stop_after_errors:
            stopped = "errors"
            break
        path = Path(image)
        try:
            row, cached = confirm(
                path, key, cache, args.cache, args.mode, args.caption,
                model, args.timeout, args.retries, args.delay, args.retry_429)
            kind = row.get("result", {}).get("kind", "?")
            usable = bool(row.get("result", {}).get("usable_as_card_image"))
            stats["cached" if cached else "checked"] += 1
            stats["usable" if usable else "unusable"] += 1
            stats[kind] += 1
            report = {**row, "cached": cached}
            remember(args.report, report)
            print(json.dumps(report, ensure_ascii=False), flush=True)
            if not cached and args.delay:
                time.sleep(args.delay)
        except RateLimited as e:
            stats["errors"] += 1
            stopped = "rate_limited"
            row = {"file": str(path), "error": str(e), "stopped": stopped}
            remember(args.report, row)
            print(json.dumps(row), flush=True)
            break
        except Exception as e:
            stats["errors"] += 1
            row = {"file": str(path), "error": str(e)[:200]}
            remember(args.report, row)
            print(json.dumps(row), flush=True)
            if "429" in str(e) or "quota" in str(e).lower():
                stopped = "rate_limited"
                break
            if stats["errors"] >= args.stop_after_errors:
                stopped = "errors"
                break
    summary = {
        "checked": stats["checked"], "cached": stats["cached"],
        "usable": stats["usable"], "unusable": stats["unusable"],
        "errors": stats["errors"], "stopped": stopped,
        "model": model if "model" in locals() else "",
        "elapsed": round(time.monotonic() - start, 1),
        "report": str(args.report),
        "kinds": {k: v for k, v in stats.items()
                  if k not in ("checked", "cached", "usable", "unusable", "errors")},
    }
    remember(args.report, {"summary": summary})
    print(json.dumps(summary), file=sys.stderr, flush=True)
    return 2 if stopped else (1 if stats["errors"] and not (stats["checked"] or stats["cached"]) else 0)


if __name__ == "__main__":
    raise SystemExit(main())
