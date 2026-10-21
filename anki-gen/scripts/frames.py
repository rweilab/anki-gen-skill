#!/usr/bin/env python3
"""Extract and auto-pick 720p video frames for card backs.

Transcript cues select candidate windows. OCR + edge/slide scoring picks one
frame per cue; low-confidence windows are skipped. No vision calls by default.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

CUES = re.compile(
    r"\b(diagram|figure|flow ?chart|state machine|block diagram|timing diagram|"
    r"schematic|architecture|chart|graph|table|this slide|as you can see|"
    r"here'?s the|shown here)\b", re.I)


def run(cmd, timeout=300):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def ts(value: str) -> float:
    parts = value.split(":")
    parts = [float(p) for p in parts]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def fmt(value: float) -> str:
    value = max(0, int(value))
    return f"{value // 60:02d}:{value % 60:02d}"


def with_time(url: str, seconds: float) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["t"] = str(max(0, int(seconds)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(query), parts.fragment))


def media_path(work: Path, vid: str, at: float) -> Path:
    return work / "media" / f"video_{vid}_{int(at):06d}.png"


def download(url: str, work: Path, vid: str) -> Path:
    target = work / "video" / f"{vid}.mp4"
    if target.is_file() and target.stat().st_size > 0:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    r = run(["yt-dlp", "-f", "bv*[height<=720]+ba/b[height<=720]",
             "--no-playlist", "--no-progress", "-o", str(target), url], timeout=600)
    if r.returncode != 0 or not target.is_file():
        raise RuntimeError(f"yt-dlp frame download failed: {r.stderr[-500:]}")
    return target


def grab(video: Path, at: float, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(max(0, at)),
             "-i", str(video), "-frames:v", "1", "-vf", "scale=-2:720",
             "-y", str(out)], timeout=60)
    if r.returncode != 0 or not out.is_file():
        raise RuntimeError(f"ffmpeg frame extraction failed: {r.stderr[-500:]}")
    return out


def score(path: Path) -> tuple[int, float]:
    """Return (OCR word count, edge-density score)."""
    words = 0
    try:
        r = run(["tesseract", str(path), "stdout", "--psm", "6"], timeout=20)
        if r.returncode == 0:
            words = len(re.findall(r"\b\w+\b", r.stdout))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    edge = 0.0
    try:
        from PIL import Image, ImageFilter, ImageStat
        im = Image.open(path).convert("L").filter(ImageFilter.FIND_EDGES)
        h = im.histogram()
        edge = sum(h[32:]) / max(1, sum(h))
    except Exception:
        pass
    return words, edge


def transcript_cues(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        text = str(r.get("text", ""))
        if CUES.search(text):
            rows.append({"start": float(r.get("start", 0)), "end": float(r.get("end", 0)),
                         "text": text})
    return rows


def candidates(cues: list[dict], duration: float) -> list[tuple[float, str]]:
    out = []
    for cue in cues:
        for offset in (-2.0, 0.0, 2.0, 4.0):
            at = max(0.0, cue["start"] + offset)
            if duration and at > duration:
                continue
            out.append((at, cue["text"]))
    return out


def auto(video: Path, vid: str, title: str, cues: list[dict], work: Path,
         duration: float = 0, source_label: str = "", source_url: str = "") -> list[dict]:
    rows = []
    for at, cue in candidates(cues, duration):
        out = media_path(work, vid, at)
        try:
            grab(video, at, out)
        except RuntimeError as e:
            print(f"frames.py: {e}", file=sys.stderr)
            continue
        words, edge = score(out)
        # A slide/diagram usually has labels or a dense line structure. A webcam
        # frame with a little text is not enough on its own.
        confidence = "high" if words >= 8 and edge >= 0.035 else (
            "medium" if words >= 3 and edge >= 0.025 else "low")
        rows.append({
            "id": f"vf-{vid}-{int(at):06d}",
            "video_id": vid, "time": at, "timecode": fmt(at),
            "file": str(out.relative_to(work)),
            "caption": cue[:180],
            "source": f"{source_label or title} @ {fmt(at)}",
            "source_url": with_time(source_url, at),
            "confidence": confidence, "needs_vision": confidence != "high",
            "ocr_words": words, "edge": round(edge, 4), "best": False,
        })
    # One best frame per timestamp; keep low/medium for the web cross-section.
    dedup = {}
    for r in rows:
        old = dedup.get(r["time"])
        if old is None or (r["ocr_words"], r["edge"]) > (old["ocr_words"], old["edge"]):
            dedup[r["time"]] = r
    rows = sorted(dedup.values(), key=lambda r: r["time"])
    groups = {}
    for r in rows:
        groups.setdefault(r["caption"], []).append(r)
    for group in groups.values():
        group.sort(key=lambda r: (r["ocr_words"], r["edge"]), reverse=True)
        group[0]["best"] = True
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work", required=True)
    ap.add_argument("--video-id", required=True)
    ap.add_argument("--url", required=True)
    ap.add_argument("--video-file", default=None)
    ap.add_argument("--title", default="")
    ap.add_argument("--source-label", default="")
    ap.add_argument("--source-url", default="")
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--at", default=None, help="single timestamp mm:ss")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--max", type=int, default=0, help="0 = no cap")
    args = ap.parse_args()
    work = Path(args.work)
    path = media_path(work, args.video_id, ts(args.at) if args.at else 0)
    try:
        video = Path(args.video_file) if args.video_file else download(args.url, work, args.video_id)
        if args.at:
            grab(video, ts(args.at), path)
            rows = [{"id": f"vf-{args.video_id}-{int(ts(args.at)):06d}",
                     "video_id": args.video_id, "time": ts(args.at),
                     "timecode": fmt(ts(args.at)), "file": str(path.relative_to(work)),
                     "caption": "manual frame",
                     "source": f"{args.source_label or args.title} @ {args.at}",
                     "source_url": with_time(args.source_url, ts(args.at)),
                     "confidence": "manual", "needs_vision": False,
                     "ocr_words": 0, "edge": 0}]
        else:
            cues = transcript_cues(Path(args.transcript))
            rows = auto(video, args.video_id, args.title, cues, work,
                        source_label=args.source_label, source_url=args.source_url)
            if args.max and len(rows) > args.max:
                rows = rows[:args.max]
    except Exception as e:
        print(f"frames.py: {e}", file=sys.stderr)
        return 1
    out = work / "frames.jsonl"
    with out.open("a") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    md = work / "frames.md"
    md.write_text("# Video frame candidates\n\n"
        "Low/medium confidence: hand the frame path to the separate `image-vision`\n"
        "skill; attach only if it confirms a diagram. Do not attach low-confidence\n"
        "frames on OCR/edge alone.\n\n" + "\n".join(
        f"- {'BEST ' if r.get('best') else ''}{r['id']}  {r['timecode']}  {r['confidence']}  `{r['file']}`  {r['source']}  {r.get('source_url','')}"
        for r in rows) + "\n")
    print(f"frames.py: {len(rows)} candidate(s) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
