#!/usr/bin/env python3
"""Ingest YouTube and local media transcripts into the skill's source index.

YouTube uses manual captions first, then auto captions. Local media uses sidecar
captions, then faster-whisper or whisper.cpp. Optional 720p frames are extracted
by frames.py through the normal media path.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_paths import ensure_tool_paths  # noqa: E402
ensure_tool_paths()
import ytdlp  # noqa: E402
import media_transcribe as mt  # noqa: E402

# yt-dlp's own polite pause before each subtitle request.
SUBTITLE_PACING = "2"


def run(cmd, timeout=300):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def video_url(vid: str, seconds: float = 0, playlist_id: str = "") -> str:
    base = f"https://www.youtube.com/watch?v={vid}"
    if playlist_id:
        base += f"&list={playlist_id}"
    return f"{base}&t={max(0, int(seconds))}"


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _clean_title(title: str, channel: str) -> str:
    """Drop a trailing channel marker; the channel is displayed separately."""
    for sep in (" | ", " - ", " · "):
        if sep in title:
            head, tail = title.rsplit(sep, 1)
            a, b = _norm(tail), _norm(channel)
            if b and (a.startswith(b) or b.startswith(a)):
                return head.strip()
    return title.strip()


def _short_playlist(playlist: str) -> str:
    return re.sub(r"^(?:the\s+)?introduction\s+to\s+", "", playlist,
                  flags=re.I).strip() or playlist


def source_label(channel: str, title: str, playlist: str = "", index: int = 0) -> str:
    """Canonical short citation: `DigiKey · RTOS 04 · Memory Management`.

    Playlist and episode titles repeat each other in the YouTube metadata; the
    full title stays in `title`/the URL, while the card footer stays readable.
    """
    title = _clean_title(title, channel)
    if playlist:
        title = re.sub(rf"^{re.escape(playlist)}\s*(?:Part\s*\d+)?\s*[-–—:]\s*",
                       "", title, flags=re.I).strip() or title
    if playlist and index:
        return f"{channel} · {_short_playlist(playlist)} {index:02d} · {title}"
    return f"{channel} · {title}"


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
    args = ["-J", "--skip-download", "--no-warnings"]
    args += ["--flat-playlist"] if playlist else ["--no-playlist"]
    args.append(url)
    r = ytdlp.run(args, timeout=180)
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


def get_vtt(entry: dict, work: Path, lang: str) -> tuple[Path | None, str]:
    vid = str(entry.get("id"))
    url = entry.get("webpage_url") or entry.get("url") or f"https://www.youtube.com/watch?v={vid}"
    outdir = work / "transcripts"
    outdir.mkdir(parents=True, exist_ok=True)
    existing = list(outdir.glob(f"{vid}*.vtt"))
    if existing:
        return prefer_vtt(existing, vid), "ok"
    pattern = outdir / f"{vid}.%(ext)s"
    try:
        r = ytdlp.run(("--skip-download", "--no-playlist", "--no-progress",
                       "--sleep-subtitles", SUBTITLE_PACING, "--write-subs",
                       "--write-auto-subs", "--sub-langs", lang, "--sub-format", "vtt",
                       "-o", str(pattern), url), timeout=180)
    except Exception as e:
        print(f"extract_video.py: caption request failed for {vid}: {e}",
              file=sys.stderr)
        return None, "rate_limited" if "timeout" in str(e).lower() else "error"
    files = list(outdir.glob(f"{vid}*.vtt"))
    path = prefer_vtt(files, vid)
    if path is None:
        status = "rate_limited" if ytdlp.is_transient(r.stderr) else "no_captions"
        print(f"extract_video.py: {status} for {vid} ({r.stderr[-200:]})",
              file=sys.stderr)
        return None, status
    return path, "ok"


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
    return mt.dedupe_cues(cues)


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


def write_transcript(work: Path, vid: str, cues: list[dict], label: str) -> dict:
    """Write JSONL for lookup and compact markdown for the model."""
    tdir = work / "transcripts"
    tdir.mkdir(parents=True, exist_ok=True)
    raw = tdir / f"{vid}.jsonl"
    raw.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cues))
    body = mt.compact_cues(cues)
    compact = tdir / f"{vid}.compact.md"
    compact.write_text(f"# {label}\n\n{body}\n" if body else f"# {label}\n\n")
    return {"caption_file": str(raw), "compact_file": str(compact),
            "compact_chars": len(body), "compact_tokens": max(1, len(body) // 4)}


def write_video_meta(work: Path, videos: list[dict], failures: list[dict],
                     chunks_count: int) -> None:
    """Write the resume index after every video, not only at the end."""
    path = work / "video_meta.json"
    tmp = path.with_name(".video_meta.json.tmp")
    tmp.write_text(json.dumps(
        {"videos": videos, "chunks": chunks_count, "failures": failures},
        indent=2) + "\n")
    tmp.replace(path)


def load_video_meta(work: Path) -> tuple[list[dict], list[dict]]:
    try:
        data = json.loads((work / "video_meta.json").read_text())
    except (OSError, json.JSONDecodeError):
        return [], []
    return list(data.get("videos") or []), list(data.get("failures") or [])


def rows_from_videos(work: Path, videos: list[dict]) -> list[dict]:
    rows = []
    for video in videos:
        raw = Path(str(video.get("caption_file") or ""))
        if not raw.is_file():
            continue
        try:
            cues = [json.loads(line) for line in raw.read_text().splitlines()
                    if line.strip()]
        except json.JSONDecodeError:
            continue
        rows.extend(chunks(cues, str(video.get("source_label") or "")))
    return rows


def write_combined_transcripts(work: Path, videos: list[dict]) -> None:
    blocks = ["# Transcripts", ""]
    for v in videos:
        blocks += [f"## {v['source_label']}", ""]
        path = v.get("compact_file")
        body = ""
        if path and Path(path).is_file():
            body = Path(path).read_text().strip()
            if body.startswith("# "):
                _, sep, rest = body.partition("\n")
                body = rest.strip() if sep else ""
        blocks += [body or f"_No transcript ({v.get('caption_error', 'missing')})._", ""]
    text = "\n".join(blocks)
    (work / "transcripts.md").write_text(text)


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


def _local_title(path: Path, info: dict, override: str) -> str:
    return override.strip() or info.get("title") or path.stem


def local_source(source: str, work: Path, args) -> int:
    if platform.system() == "Darwin" and platform.machine() != "arm64":
        print("extract_video.py: warn: Intel Mac local transcription is best-effort",
              file=sys.stderr)
    media_list = mt.media_files(source)
    if not media_list:
        print("extract_video.py: no supported media files found", file=sys.stderr)
        return 1
    all_rows, videos, failures = [], [], []
    for position, media in enumerate(media_list, 1):
        try:
            info = mt.probe(media)
        except Exception as e:
            failures.append({"id": media.name, "title": media.name, "reason": str(e)})
            continue
        title = _local_title(media, info,
                             args.title if len(media_list) == 1 else "")
        vid = mt.media_id(media)
        label = f"Local recording - {title}"
        try:
            cues, transcript_source = mt.transcribe(
                media, work, model=args.model,
                language=None if args.language in ("", "auto") else args.language,
                device=args.device,
                initial_prompt=args.initial_prompt,
                force=args.force_transcribe)
        except Exception as e:
            failures.append({"id": vid, "title": title, "reason": str(e)})
            continue
        if not cues:
            transcript_source = "no_speech"
        transcript_files = write_transcript(work, vid, cues, label)
        rows = chunks(cues, label)
        all_rows.extend(rows)
        videos.append({
            "id": vid, "title": title, "url": "", "channel": "Local recording",
            "duration": info.get("duration"), "playlist_title": "",
            "playlist_index": 0, "source_label": label, "source_url": "",
            "cues": len(cues), **transcript_files,
            "source_type": "local", "local_path": str(media.resolve()),
            "media_kind": mt.kind(media), "transcript_source": transcript_source,
            "model": "none" if transcript_source.startswith("sidecar") else transcript_source,
        })
        frames = "skipped"
        if args.images in ("yes", "auto") and mt.kind(media) == "video":
            r = run([sys.executable, str(Path(__file__).with_name("frames.py")),
                     "--work", str(work), "--video-id", vid, "--url", "",
                     "--video-file", str(media), "--title", title,
                     "--source-label", label, "--source-url", "",
                     "--transcript", transcript_files["caption_file"],
                     "--auto"], timeout=900)
            if r.returncode != 0:
                frames = "failed"
                failures.append({"id": vid, "title": title,
                                 "reason": "frame extraction failed"})
            else:
                frames = "ok"
        elif args.images in ("yes", "auto"):
            print(f"extract_video.py: audio-only {media.name}; frames skipped",
                  file=sys.stderr)
        print(f"[video {position}/{len(media_list)}] {title}: "
              f"transcript {transcript_source}, cues {len(cues)}, frames {frames}",
              flush=True)
        write_video_meta(work, videos, failures, len(all_rows))
    if not all_rows and not videos:
        for f in failures:
            print(f"extract_video.py: {f['id']} — {f['reason']}", file=sys.stderr)
        return 1
    write_combined_transcripts(work, videos)
    index(work, all_rows)
    (work / "videos.jsonl").write_text(
        "".join(json.dumps(v, ensure_ascii=False) + "\n" for v in videos))
    toc = ["# Video source map", ""]
    for v in videos:
        toc.extend([f"## {v['title']}", f"- id: {v['id']}",
                    f"- {v['source_label']} @ 00:00",
                    f"- local: {v['local_path']}",
                    f"- transcript: {v['transcript_source']}",
                    f"- cues: {v['cues']}",
                    f"- compact: {Path(v['compact_file']).name} "
                    f"(~{v.get('compact_tokens', 0)} tokens)", ""])
    if failures:
        toc.append("## Skipped")
        toc.extend(f"- {f['id']} — {f['reason']} — {f['title']}" for f in failures)
        toc.append("")
    (work / "video_toc.md").write_text("\n".join(toc))
    write_video_meta(work, videos, failures, len(all_rows))
    print(json.dumps({"videos": len(videos), "chunks": len(all_rows),
                      "frames": (work / "frames.jsonl").is_file(),
                      "failures": failures}, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", nargs="?", help="video or playlist URL")
    ap.add_argument("--work", required=True)
    ap.add_argument("--whole-playlist", action="store_true")
    ap.add_argument("--items", default="", help="1-3 or 2,4")
    ap.add_argument("--lang", default="en.*")
    ap.add_argument("--images", choices=("yes", "no", "auto"), default="auto")
    ap.add_argument("--search", default=None, help="print candidate videos for a query")
    ap.add_argument("--title", default="", help="local recording title")
    ap.add_argument("--model", default="auto", help="local Whisper model or auto")
    ap.add_argument("--language", default="en", help="local language, or auto")
    ap.add_argument("--device", default="cpu", help="local Whisper device")
    ap.add_argument("--force-transcribe", action="store_true",
                    help="ignore a sidecar VTT/SRT and transcribe anyway")
    ap.add_argument("--resume", action="store_true",
                    help="skip playlist videos already in video_meta.json")
    ap.add_argument("--initial-prompt", default=None,
                    help="optional course terms for local transcription")
    args = ap.parse_args()
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    if args.search:
        r = ytdlp.run(("-J", "--flat-playlist", "--skip-download",
                       f"ytsearch10:{args.search}"), timeout=60)
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
    local = args.source[7:] if args.source.startswith("file://") else args.source
    if Path(local).exists():
        return local_source(local, work, args)
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
    all_rows, videos, failures = [], [], []
    picked_ids = {str(e.get("id") or "") for e in picked}
    prior_videos, prior_failures = load_video_meta(work) if args.resume else ([], [])
    failed_ids = {str(f.get("id") or "") for f in prior_failures}
    # A rate-limited caption is incomplete; retry it on resume. A permanent
    # no-captions result stays complete so every resume does not re-request it.
    retry_ids = failed_ids | {str(v.get("id") or "") for v in prior_videos
                              if v.get("caption_error") == "rate_limited"}
    completed = [v for v in prior_videos
                 if str(v.get("id") or "") in picked_ids
                 and str(v.get("id") or "") not in retry_ids]
    videos.extend(completed)
    failures.extend([f for f in prior_failures
                     if str(f.get("id") or "") in picked_ids])
    all_rows.extend(rows_from_videos(work, completed))
    completed_ids = {str(v.get("id") or "") for v in completed}
    full_entries = meta.get("entries") or []
    playlist_title = str(meta.get("title") or "") if meta.get("_type") == "playlist" and (whole or args.items) else ""
    playlist_id = str(meta.get("id") or "") if meta.get("_type") == "playlist" and (whole or args.items) else ""
    for position, e in enumerate(picked, 1):
        vid = str(e.get("id") or "")
        if not vid:
            continue
        if vid in completed_ids:
            print(f"[video {position}/{len(picked)}] resume skip {e.get('title') or vid}",
                  flush=True)
            continue
        videos[:] = [v for v in videos if str(v.get("id") or "") != vid]
        failures[:] = [f for f in failures if str(f.get("id") or "") != vid]
        title = str(e.get("title") or vid)
        channel = str(e.get("channel") or e.get("uploader") or meta.get("channel") or
                      meta.get("uploader") or "Unknown")
        try:
            playlist_index = next(i + 1 for i, x in enumerate(full_entries) if x.get("id") == vid)
        except StopIteration:
            playlist_index = 0
        url = e.get("webpage_url") or e.get("url") or f"https://www.youtube.com/watch?v={vid}"
        label = source_label(channel, title, playlist_title, playlist_index)
        base_url = video_url(vid, 0, playlist_id)
        vtt, caption_status = get_vtt(e, work, args.lang)
        cues = parse_vtt(vtt) if vtt is not None else []
        if vtt is not None and not cues:
            caption_status = "empty_captions"
        files = write_transcript(work, vid, cues, label)
        if cues:
            rows = chunks(cues, label)
            for r in rows:
                r["source"] = label
            all_rows.extend(rows)
        video = {"id": vid, "title": title, "url": url,
                 "channel": channel, "duration": e.get("duration"),
                 "playlist_title": playlist_title, "playlist_index": playlist_index,
                 "source_label": label, "source_url": base_url,
                 "cues": len(cues), "transcript_source": caption_status,
                 **files}
        if caption_status != "ok":
            video["caption_error"] = caption_status
        videos.append(video)
        frames = "skipped"
        if args.images in ("yes", "auto"):
            r = run([sys.executable, str(Path(__file__).with_name("frames.py")),
                     "--work", str(work), "--video-id", vid, "--url", url,
                     "--title", title, "--source-label", label,
                     "--source-url", base_url, "--transcript",
                     files["caption_file"], "--auto"], timeout=900)
            if r.returncode != 0:
                frames = "failed"
                failures.append({"id": vid, "title": title,
                                 "reason": "frame extraction failed"})
                print(f"extract_video.py: frames for {vid} failed: {r.stderr[-300:]}",
                      file=sys.stderr)
            else:
                frames = "ok"
        print(f"[video {position}/{len(picked)}] {title}: "
              f"captions {caption_status}, cues {len(cues)}, frames {frames}",
              flush=True)
        write_video_meta(work, videos, failures, len(all_rows))
    if not all_rows and not videos:
        print("extract_video.py: no usable transcripts or frames", file=sys.stderr)
        return 1
    write_combined_transcripts(work, videos)
    index(work, all_rows)
    (work / "videos.jsonl").write_text(
        "".join(json.dumps(v, ensure_ascii=False) + "\n" for v in videos))
    toc = ["# Video source map", ""]
    for v in videos:
        toc.append(f"## {v.get('title', v.get('id', ''))}")
        toc.append(f"- id: {v.get('id', '')}")
        toc.append(f"- {v.get('source_label', '')} @ 00:00")
        if v.get("source_url"):
            toc.append(f"- {v['source_url']}")
        toc.append(f"- cues: {v.get('cues', 0)}")
        if v.get("transcript_source"):
            toc.append(f"- transcript: {v['transcript_source']}")
        if v.get("compact_file"):
            toc.append(f"- compact: {Path(v['compact_file']).name} "
                       f"(~{v.get('compact_tokens', 0)} tokens)")
        toc.append("")
    if failures:
        toc.append("## Skipped")
        for f in failures:
            toc.append(f"- {f['id']} — {f['reason']} — {f['title']}")
        toc.append("")
    (work / "video_toc.md").write_text("\n".join(toc))
    write_video_meta(work, videos, failures, len(all_rows))
    print(json.dumps({"videos": len(videos), "chunks": len(all_rows),
                      "frames": (work / "frames.jsonl").is_file(),
                      "failures": failures}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
