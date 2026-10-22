#!/usr/bin/env python3
"""Local video/audio helpers: metadata, sidecars, and optional faster-whisper.

No cloud calls. Captions beside the media win; otherwise faster-whisper runs
locally. The default model choice benchmarks actual speech once per machine.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".m4v", ".avi"}
AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".flac"}
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS
STAMP = re.compile(
    r"(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})\s*-->\s*"
    r"(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})")
CACHE = Path(os.environ.get("ANKI_GEN_CACHE_DIR",
                            Path.home() / ".cache" / "anki-gen"))
BENCHMARK = CACHE / "transcription-benchmark.json"


def is_media(path) -> bool:
    return Path(path).suffix.lower() in MEDIA_EXTS


def kind(path) -> str:
    return "audio" if Path(path).suffix.lower() in AUDIO_EXTS else "video"


def media_files(source: str) -> list[Path]:
    path = Path(source)
    if path.is_file():
        if not is_media(path):
            raise ValueError(f"unsupported media type: {source}")
        return [path]
    if path.is_dir():
        return sorted(p for p in path.rglob("*") if p.is_file() and is_media(p))
    raise ValueError(f"local media not found: {source}")


def media_id(path: Path) -> str:
    st = path.stat()
    raw = f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()
    return "local-" + hashlib.sha256(raw).hexdigest()[:12]


def probe(path: Path) -> dict:
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe not found; install ffmpeg")
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:format_tags=title", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {r.stderr[-300:]}")
    data = json.loads(r.stdout or "{}")
    fmt = data.get("format") or {}
    try:
        duration = float(fmt.get("duration") or 0)
    except ValueError:
        duration = 0.0
    tags = {str(k).lower(): v for k, v in (fmt.get("tags") or {}).items()}
    return {"duration": duration, "title": str(tags.get("title") or "").strip()}


def sidecar(path: Path) -> Path | None:
    for ext in (".vtt", ".srt"):
        candidate = path.with_suffix(ext)
        if candidate.is_file():
            return candidate
    return None


def seconds(stamp: str) -> float:
    total = 0.0
    for part in stamp.replace(",", ".").split(":"):
        total = total * 60 + float(part)
    return total


def parse_captions(path: Path) -> list[dict]:
    text = path.read_text(errors="replace").replace("\r\n", "\n")
    lines = text.splitlines()
    cues, i = [], 0
    while i < len(lines):
        m = STAMP.search(lines[i])
        if not m:
            i += 1
            continue
        start, end = seconds(m.group(1)), seconds(m.group(2))
        i += 1
        body = []
        while i < len(lines) and lines[i].strip():
            line = lines[i].strip()
            if not line.isdigit() and line.upper() != "WEBVTT":
                body.append(re.sub(r"<[^>]+>", "", line))
            i += 1
        content = re.sub(r"\s+", " ", " ".join(body)).strip()
        if content and (not cues or content != cues[-1]["text"]):
            cues.append({"start": start, "end": end, "text": content})
        i += 1
    return cues


def extract_audio(media: Path, work: Path, seconds_limit: float | None = None) -> Path:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found; install ffmpeg")
    audio_dir = work / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"-{int(seconds_limit)}s" if seconds_limit else ""
    out = audio_dir / f"{media_id(media)}{suffix}.wav"
    if out.is_file() and out.stat().st_size > 0:
        return out
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(media),
           "-vn", "-ac", "1", "-ar", "16000"]
    if seconds_limit:
        cmd += ["-t", str(seconds_limit)]
    cmd.append(str(out))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0 or not out.is_file():
        raise RuntimeError(f"ffmpeg audio extraction failed: {r.stderr[-300:]}")
    return out


def _load_model(name: str, device: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "local transcription needs faster-whisper; run setup.sh or "
            "pip install --user faster-whisper") from e
    CACHE.mkdir(parents=True, exist_ok=True)
    return WhisperModel(name, device=device, compute_type="int8",
                        download_root=str(CACHE / "models"))


def _run(audio: Path, model_name: str, language: str | None,
         initial_prompt: str | None, device: str) -> float:
    model = _load_model(model_name, device)
    segments, _ = model.transcribe(
        str(audio), language=language, vad_filter=True,
        initial_prompt=initial_prompt)
    start = time.monotonic()
    for _ in segments:
        pass
    return time.monotonic() - start


def choose_model(audio: Path, language: str | None, requested: str,
                 device: str) -> str:
    if requested and requested != "auto":
        return requested
    if not language or str(language).lower() == "auto":
        return "small"
    if not str(language).lower().startswith("en"):
        return "small"
    cache = {}
    if BENCHMARK.is_file():
        try:
            cache = json.loads(BENCHMARK.read_text())
        except (OSError, json.JSONDecodeError):
            cache = {}
    key = f"{platform.machine()}-{os.cpu_count()}-{device}"
    if cache.get("key") == key and cache.get("chosen") in ("base.en", "small.en"):
        return cache["chosen"]
    sample = extract_audio(audio, audio.parent.parent, seconds_limit=25)
    try:
        base = _run(sample, "base.en", "en", None, device)
        small = _run(sample, "small.en", "en", None, device)
        chosen = "small.en" if small <= 18.0 else "base.en"
        CACHE.mkdir(parents=True, exist_ok=True)
        BENCHMARK.write_text(json.dumps({
            "key": key, "chosen": chosen, "base_seconds": round(base, 2),
            "small_seconds": round(small, 2),
            "sample_seconds": 25, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, indent=2) + "\n")
        return chosen
    except Exception as e:
        print(f"media_transcribe.py: model benchmark failed ({e}); using base.en",
              file=sys.stderr)
        return "base.en"


def transcribe(media: Path, work: Path, model: str = "auto",
               language: str | None = "en", device: str = "cpu",
               initial_prompt: str | None = None,
               force: bool = False) -> tuple[list[dict], str]:
    cue_path = None if force else sidecar(media)
    if cue_path:
        cues = parse_captions(cue_path)
        if cues:
            return cues, f"sidecar:{cue_path.suffix[1:]}"
        print(f"media_transcribe.py: empty sidecar {cue_path.name}; transcribing",
              file=sys.stderr)
    audio = extract_audio(media, work)
    chosen = choose_model(audio, language, model, device)
    loaded = _load_model(chosen, device)
    segments, _ = loaded.transcribe(
        str(audio), language=language, vad_filter=True,
        initial_prompt=initial_prompt)
    cues = []
    for seg in segments:
        text = re.sub(r"\s+", " ", str(seg.text or "")).strip()
        if text:
            cues.append({"start": float(seg.start), "end": float(seg.end),
                         "text": text})
    return cues, chosen
