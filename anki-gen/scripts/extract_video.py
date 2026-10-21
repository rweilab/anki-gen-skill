#!/usr/bin/env python3
"""Ingest YouTube video/playlist transcripts into the skill's source index.

No Whisper: manual captions first, auto captions fallback. Optional 720p frames
are extracted by frames.py through the normal media path.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

CUE = re.compile(
    r"\b(diagram|figure|flow ?chart|state machine|block diagram|timing diagram|"
    r"schematic|architecture|chart|graph|table|this slide|as you can see|"
    r"here'?s the|shown here)\b", re.I)


def run(cmd, timeout=300):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def video_url(vid: str, seconds: float = 0, playlist_id: str = "") -> str:
    base = f"https://www.youtube.com/watch?v={vid}"
    if playlist_id:
        base += f"&list={playlist_id}"
    return f"{base}&t={max(0, int(seconds))}"


def source_label(channel: str, title: str, playlist: str = "", index: int = 0) -> str:
    if playlist and index:
        return f"{channel} - {playlist} {index:02d} - {title}"
    return f"{channel} - {title}"


def with_time(url: str, seconds: float) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["t"] = str(max(0, int(seconds)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(query), parts.fragment))


def fmt(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def seconds(stamp: str) -> float:
    parts = [float(p) for p in stamp.replace(",", ".").split(":")]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def parse_items(value: str, count: int) -> list[int]:
    if not value:
        return list(range(count))
    out = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return [i - 1 for i in out if 1 <= i <= count]


def metadata(url: str, playlist: bool) -> dict:
    cmd = ["yt-dlp", "-J", "--skip-download", "--no-warnings"]
    cmd += ["--flat-playlist"] if playlist else ["--no-playlist"]
    cmd.append(url)
    r = run(cmd, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"yt-dlp metadata failed: {r.stderr[-500:]}")
    return json.loads(r.stdout)


def entries(meta: dict, whole: bool, items: str) -> list[dict]:
    rows = meta.get("entries") or []
    if meta.get("_type") == "playlist" and (whole or items):
        picked = parse_items(items, len(rows))
        return [rows[i] for i in picked if i < len(rows)]
    if meta.get("_type") == "playlist":
        return rows[:1]
    return [meta]


def prefer_vtt(files: list[Path], vid: str) -> Path | None:
    if not files:
        return None
    # Prefer a normal .en.vtt over YouTube's .en-orig auto track.
    files = sorted(files, key=lambda p: ("orig" in p.name, len(p.name)))
    return files[0]


def get_vtt(entry: dict, work: Path, lang: str) -> Path | None:
    vid = str(entry.get("id"))
    url = entry.get("webpage_url") or entry.get("url") or f"https://www.youtube.com/watch?v={vid}"
    outdir = work / "transcripts"
    outdir.mkdir(parents=True, exist_ok=True)
    pattern = outdir / f"{vid}.%(ext)s"
    cmd = ["yt-dlp", "--skip-download", "--no-playlist", "--no-progress",
           "--write-subs", "--write-auto-subs", "--sub-langs", lang,
           "--sub-format", "vtt", "-o", str(pattern), url]
    r = run(cmd, timeout=180)
    files = list(outdir.glob(f"{vid}*.vtt"))
    path = prefer_vtt(files, vid)
    if path is None:
        print(f"extract_video.py: no captions for {vid} ({r.stderr[-200:]})",
              file=sys.stderr)
    return path


def parse_vtt(path: Path) -> list[dict]:
    text = path.read_text(errors="replace").replace("\r\n", "\n")
    lines = text.splitlines()
    cues = []
    i = 0
    stamp = re.compile(r"(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})\s*-->\s*"
                       r"(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})")
    while i < len(lines):
        m = stamp.search(lines[i])
        if not m:
            i += 1
            continue
        start, end = seconds(m.group(1)), seconds(m.group(2))
        i += 1
        body = []
        while i < len(lines) and lines[i].strip():
            body.append(re.sub(r"<[^>]+>", "", lines[i]).strip())
            i += 1
        content = re.sub(r"\s+", " ", " ".join(body)).strip()
        if content and (not cues or content != cues[-1]["text"]):
            cues.append({"start": start, "end": end, "text": content})
        i += 1
    return cues


def chunks(cues: list[dict], source: str, max_chars=700):
    out, buf, start, end = [], [], 0.0, 0.0
    for cue in cues:
        if not buf:
            start = cue["start"]
        buf.append(cue["text"])
        end = cue["end"]
        if sum(len(x) for x in buf) >= max_chars:
            out.append({"source": source, "loc": fmt(start), "heading": "Transcript",
                        "text": " ".join(buf), "start": start, "end": end})
            buf = []
    if buf:
        out.append({"source": source, "loc": fmt(start), "heading": "Transcript",
                    "text": " ".join(buf), "start": start, "end": end})
    return out


def index(work: Path, rows: list[dict]):
    """Add video chunks without replacing a PDF/text index in the same work dir."""
    db = work / "source_index.sqlite"
    con = sqlite3.connect(db)
    try:
        try:
            con.execute("CREATE VIRTUAL TABLE chunks USING fts5("
                        "id UNINDEXED, source, loc, heading, text)")
        except sqlite3.OperationalError:
            con.execute("CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, "
                        "source TEXT, loc TEXT, heading TEXT, text TEXT)")
        sources = sorted({str(r["source"]) for r in rows})
        for source in sources:
            con.execute("DELETE FROM chunks WHERE source=?", (source,))
        start = con.execute("SELECT COALESCE(MAX(id), 0) FROM chunks").fetchone()[0]
        con.executemany("INSERT INTO chunks VALUES (?,?,?,?,?)",
                        [(start + i + 1, r["source"], r["loc"], r["heading"], r["text"])
                         for i, r in enumerate(rows)])
        con.commit()
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", nargs="?", help="video or playlist URL")
    ap.add_argument("--work", required=True)
    ap.add_argument("--whole-playlist", action="store_true")
    ap.add_argument("--items", default="", help="1-3 or 2,4")
    ap.add_argument("--lang", default="en.*")
    ap.add_argument("--images", choices=("yes", "no"), default="no")
    ap.add_argument("--search", default=None, help="print candidate videos for a query")
    args = ap.parse_args()
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    if args.search:
        r = run(["yt-dlp", "-J", "--flat-playlist", "--skip-download",
                 f"ytsearch10:{args.search}"], timeout=60)
        if r.returncode != 0:
            print(f"extract_video.py: search failed: {r.stderr[-300:]}", file=sys.stderr)
            return 1
        meta = json.loads(r.stdout)
        for e in meta.get("entries") or []:
            print(json.dumps({k: e.get(k) for k in ("id", "title", "channel",
                                                    "duration", "webpage_url", "url")},
                             ensure_ascii=False))
        return 0
    if not args.source:
        print("extract_video.py: pass a URL or --search", file=sys.stderr)
        return 2
    try:
        is_watch = "watch?" in args.source
        whole = bool(args.whole_playlist or ("/playlist" in args.source) or
                     ("list=" in args.source and not is_watch))
        playlist = bool(whole or args.items)
        meta = metadata(args.source, playlist)
        picked = entries(meta, whole, args.items)
    except Exception as e:
        print(f"extract_video.py: {e}", file=sys.stderr)
        return 1
    all_rows, videos = [], []
    full_entries = meta.get("entries") or []
    playlist_title = str(meta.get("title") or "") if meta.get("_type") == "playlist" and (whole or args.items) else ""
    playlist_id = str(meta.get("id") or "") if meta.get("_type") == "playlist" and (whole or args.items) else ""
    for e in picked:
        vid = str(e.get("id") or "")
        if not vid:
            continue
        title = str(e.get("title") or vid)
        channel = str(e.get("channel") or e.get("uploader") or meta.get("channel") or
                      meta.get("uploader") or "Unknown")
        try:
            index = next(i + 1 for i, x in enumerate(full_entries) if x.get("id") == vid)
        except StopIteration:
            index = 0
        url = e.get("webpage_url") or e.get("url") or f"https://www.youtube.com/watch?v={vid}"
        label = source_label(channel, title, playlist_title, index)
        base_url = video_url(vid, 0, playlist_id)
        vtt = get_vtt(e, work, args.lang)
        if vtt is None:
            continue
        cues = parse_vtt(vtt)
        if not cues:
            continue
        rows = chunks([c for c in cues], label)
        for r in rows:
            r["source"] = label
        all_rows.extend(rows)
        videos.append({"id": vid, "title": title, "url": url,
                       "channel": channel, "duration": e.get("duration"),
                       "playlist_title": playlist_title, "playlist_index": index,
                       "source_label": label, "source_url": base_url,
                       "cues": len(cues), "caption_file": str(vtt)})
        (work / "transcripts" / f"{vid}.jsonl").write_text(
            "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cues))
        if args.images == "yes":
            r = run([sys.executable, str(Path(__file__).with_name("frames.py")),
                     "--work", str(work), "--video-id", vid, "--url", url,
                     "--title", title, "--source-label", label,
                     "--source-url", base_url, "--transcript",
                     str(work / "transcripts" / f"{vid}.jsonl"), "--auto"], timeout=900)
            if r.returncode != 0:
                print(f"extract_video.py: frames for {vid} failed: {r.stderr[-300:]}",
                      file=sys.stderr)
    if not all_rows:
        print("extract_video.py: no usable transcripts", file=sys.stderr)
        return 1
    index(work, all_rows)
    (work / "videos.jsonl").write_text(
        "".join(json.dumps(v, ensure_ascii=False) + "\n" for v in videos))
    toc = ["# Video source map", ""]
    for v in videos:
        toc.append(f"## {v['title']}")
        toc.append(f"- id: {v['id']}")
        toc.append(f"- {v['source_label']} @ 00:00")
        toc.append(f"- {v['source_url']}")
        toc.append(f"- cues: {v['cues']}")
        toc.append("")
    (work / "video_toc.md").write_text("\n".join(toc))
    (work / "video_meta.json").write_text(json.dumps(
        {"videos": videos, "chunks": len(all_rows)}, indent=2) + "\n")
    print(json.dumps({"videos": len(videos), "chunks": len(all_rows),
                      "frames": (work / "frames.jsonl").is_file()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
