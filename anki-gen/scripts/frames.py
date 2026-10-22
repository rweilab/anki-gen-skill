#!/usr/bin/env python3
"""Extract and rank 720p video frames for card backs.

Transcript cues select candidate windows. A cheap visual probe shortlists the
windows, then a second pass samples around them and scores structure, colour,
and OCR text. One best frame is kept per cue; ambiguous frames are marked for
optional image-vision confirmation. No vision calls happen here.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_paths import ensure_tool_paths  # noqa: E402
ensure_tool_paths()
import visual  # noqa: E402
import ytdlp  # noqa: E402

# Visual nouns are broad on purpose; the scorer decides whether the frame is
# actually a diagram. Generic phrases stay out of STRONG so they need more
# visual evidence before confirmation.
CUT_DISTANCE = 18
SCAN_INTERVAL = 10.0
SCAN_MAX = 240
CUE_OFFSETS = (-2, 0, 2, 4, 6)
PROBE_OFFSET = 2.0
VISUAL_WORDS = (
    "diagram|figure|illustration|picture|image|flow ?chart|state machine|"
    "block diagram|timing diagram|schematic|architecture|chart|graph|table|"
    "structure|model|orbital|molecule|arrangement|circuit|map|timeline")
CUE = re.compile(
    rf"\b({VISUAL_WORDS}|this slide|as you can see|here'?s the|shown here)\b", re.I)
STRONG_CUE = re.compile(rf"\b({VISUAL_WORDS})\b", re.I)


def run(cmd, timeout=300):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def ts(value: str) -> float:
    parts = [float(p) for p in value.split(":")]
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
    existing = sorted(target.parent.glob(f"{vid}.mp4.*"))
    if existing:
        return existing[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    r = ytdlp.run(
        ("-f", "bv*[height<=720]+ba/b[height<=720]",
         "--no-playlist", "--no-progress", "-o", str(target), url),
        timeout=600)
    if not target.is_file():
        matches = sorted(target.parent.glob(f"{vid}.mp4.*"))
        if matches:
            return matches[0]
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


def ocr_words(path: Path) -> int:
    try:
        r = run(["tesseract", str(path), "stdout", "--psm", "6"], timeout=20)
        return len(re.findall(r"\b\w+\b", r.stdout)) if r.returncode == 0 else 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return 0


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
        if CUE.search(text):
            rows.append({"start": float(r.get("start", 0)),
                         "end": float(r.get("end", 0)),
                         "text": text,
                         "strong": bool(STRONG_CUE.search(text))})
    return rows


def probe(video: Path, vid: str, at: float, work: Path):
    out = media_path(work, vid, at)
    try:
        grab(video, at, out)
    except RuntimeError as e:
        print(f"frames.py: {e}", file=sys.stderr)
        return None, None
    return out, visual.analyze(out)


def make_row(vid: str, title: str, at: float, path: Path, metrics: dict,
             q: dict, words: int, cue: dict, cue_id: int,
             source_label: str, source_url: str, work: Path) -> dict:
    return {
        "id": f"vf-{vid}-{int(at):06d}",
        "video_id": vid, "time": at, "timecode": fmt(at),
        "file": str(path.relative_to(work)),
        "caption": cue["text"][:180],
        "source": f"{source_label or title} @ {fmt(at)}",
        "source_url": with_time(source_url, at),
        "confidence": q.get("confidence", q["quality"]),
        "quality": q["quality"], "attach": q["attach"],
        "needs_vision": q["needs_vision"], "blank": q["blank"],
        "text_wall": q["text_wall"], "text_like": q["text_like"],
        "reason": q["reason"], "strong_cue": cue["strong"],
        "ocr_words": words, "edge": metrics["edge"], "focus": metrics["focus"],
        "color": metrics["color"], "background": metrics["background"],
        "dhash": metrics["dhash"], "best": False, "cue_id": cue_id,
    }


def _tier(row: dict) -> int:
    return {"high": 3, "medium": 2}.get(row.get("quality"), 1)


def late_best(rows: list[dict]) -> dict | None:
    """Latest high/confirm frame inside the strongest visual shot."""
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: r["time"])
    shots, current = [], []
    for row in rows:
        if (current and visual.dhash_distance(current[-1]["dhash"], row["dhash"])
                > CUT_DISTANCE):
            shots.append(current)
            current = []
        current.append(row)
    if current:
        shots.append(current)
    shot = max(shots, key=lambda s: max(visual.rank(r) for r in s))
    return max(shot, key=lambda r: (_tier(r), r["time"], visual.rank(r)))


def duration(video: Path) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(video)], timeout=30)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def coarse_scan(video: Path, vid: str, title: str, work: Path,
                source_label: str, source_url: str) -> list[dict]:
    """Visual-only fallback for videos with no useful transcript cues."""
    total = duration(video)
    if total <= 0:
        return []
    limit = min(SCAN_MAX, max(30, int(total / SCAN_INTERVAL)))
    step = max(4.0, total / limit)
    cue = {"text": "visual scan", "strong": True}
    rows, cluster, last_hash = [], -1, None
    at = 0.0
    while at < total and len(rows) < limit:
        path, metrics = probe(video, vid, at, work)
        if metrics is not None:
            words = ocr_words(path)
            q = visual.classify(metrics, words=words, strong_cue=True)
            if not q["blank"] and not q["text_wall"]:
                if last_hash is None or visual.dhash_distance(last_hash,
                                                              metrics["dhash"]) > CUT_DISTANCE:
                    cluster += 1
                last_hash = metrics["dhash"]
                rows.append(make_row(vid, title, at, path, metrics, q, words, cue,
                                     f"scan-{cluster}", source_label, source_url,
                                     work))
        at += step
    return rows


def auto(video: Path, vid: str, title: str, cues: list[dict], work: Path,
         duration: float = 0, source_label: str = "", source_url: str = "") -> list[dict]:
    rows = []
    for cue_id, cue in enumerate(cues):
        # Pass 1: one cheap probe decides whether this cue is worth the full window.
        at = max(0.0, cue["start"] + PROBE_OFFSET)
        if duration and at > duration:
            continue
        path, metrics = probe(video, vid, at, work)
        if metrics is None:
            continue
        first = visual.classify(metrics, words=None, strong_cue=cue["strong"])
        if first["blank"]:
            continue
        if not cue["strong"] and first["quality"] == "low":
            continue

        # Pass 2: sample around the cue, OCR only this shortlist.
        for offset in CUE_OFFSETS:
            t = max(0.0, round(cue["start"] + offset, 1))
            if duration and t > duration:
                continue
            if abs(t - at) < 0.01:
                p, m = path, metrics
            else:
                p, m = probe(video, vid, t, work)
            if m is None:
                continue
            words = ocr_words(p)
            q = visual.classify(m, words=words, strong_cue=cue["strong"])
            if q["blank"] or q["text_wall"]:
                continue
            rows.append(make_row(vid, title, t, p, m, q, words, cue, cue_id,
                                 source_label, source_url, work))

    # One best frame per cue; collapse near-identical frames inside that cue only.
    groups = defaultdict(list)
    for row in rows:
        groups[row["cue_id"]].append(row)
    kept = []
    for group in groups.values():
        group.sort(key=visual.rank, reverse=True)
        unique = []
        for row in group:
            if any(visual.dhash_distance(row["dhash"], other["dhash"]) <= 2
                   for other in unique):
                continue
            unique.append(row)
        best = late_best(unique)
        if best:
            best["best"] = True
        kept.extend(unique)
    kept.sort(key=lambda r: r["time"])
    return kept


def refresh(work: Path) -> list[dict]:
    """Deduplicate the append-only log, recompute best, and write a compact MD."""
    p = work / "frames.jsonl"
    rows = []
    if p.is_file():
        for line in p.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    by_id = {r["id"]: r for r in rows if r.get("id")}
    rows = list(by_id.values())
    groups = defaultdict(list)
    for row in rows:
        cue_id = row.get("cue_id")
        key = (row.get("video_id"), cue_id if cue_id is not None else row["id"])
        groups[key].append(row)
    for group in groups.values():
        for row in group:
            row["best"] = False
        best = late_best(group)
        if best:
            best["best"] = True
    rows.sort(key=lambda r: (r.get("video_id", ""), r.get("time", 0)))
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))

    shown = [r for r in rows if r.get("best") and
             (r.get("attach") in ("direct", "confirm") or
              r.get("confidence") == "manual")]
    lines = [
        "# Video frame candidates",
        "",
        "`direct` = attach. `confirm` = use image-vision when available, otherwise",
        "attach only with a strong visual cue. `skip` and non-best candidates stay",
        "in frames.jsonl.",
        "",
    ]
    for r in shown:
        lines.append(
            f"- {r['video_id']} {r['timecode']} {r.get('confidence', '?')}/"
            f"{r.get('attach', '?')} `{r['file']}`  {r.get('caption', '')[:100]}  "
            f"{r.get('source_url', '')}")
    if not shown:
        lines.append("- no attachable candidates")
    lines.append("")
    lines.append(f"{len(rows)} candidate(s), {len(shown)} shown.")
    (work / "frames.md").write_text("\n".join(lines) + "\n")
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
    ap.add_argument("--max", type=int, default=0,
                    help="keep the N best candidates; 0 = no cap")
    args = ap.parse_args()
    work = Path(args.work)
    try:
        video = Path(args.video_file) if args.video_file else download(args.url, work, args.video_id)
        if args.at:
            at = ts(args.at)
            path = grab(video, at, media_path(work, args.video_id, at))
            metrics = visual.analyze(path)
            words = ocr_words(path)
            cue = {"text": "manual frame", "strong": True}
            if metrics is None:
                raise RuntimeError("could not read the extracted frame")
            q = visual.classify(metrics, words=words, strong_cue=True)
            q = {**q, "quality": "high", "confidence": "manual",
                 "attach": "direct", "needs_vision": False, "reason": "manual"}
            row = make_row(args.video_id, args.title, at, path, metrics, q, words,
                           cue, None, args.source_label, args.source_url, work)
            row["id"] = f"vf-manual-{args.video_id}-{int(at):06d}"
            row["best"] = True
            rows = [row]
        else:
            cues = transcript_cues(Path(args.transcript))
            rows = auto(video, args.video_id, args.title, cues, work,
                        source_label=args.source_label, source_url=args.source_url)
            if not any(r.get("attach") in ("direct", "confirm") for r in rows):
                rows += coarse_scan(video, args.video_id, args.title, work,
                                    args.source_label, args.source_url)
            if args.max and len(rows) > args.max:
                rows = sorted(rows, key=visual.rank, reverse=True)[:args.max]
                rows.sort(key=lambda r: r["time"])
    except Exception as e:
        print(f"frames.py: {e}", file=sys.stderr)
        return 1
    out = work / "frames.jsonl"
    with out.open("a") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    total = len(refresh(work))
    print(f"frames.py: {len(rows)} new candidate(s), {total} total -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
