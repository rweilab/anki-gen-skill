#!/usr/bin/env python3
"""Local video/audio helpers: metadata, sidecars, and local speech-to-text.

No cloud calls. Captions beside the media win; otherwise faster-whisper runs
locally when available, with whisper.cpp as the Python-version-independent
fallback. The default model choice benchmarks actual speech once per machine.
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
import urllib.request
from pathlib import Path

from platform_paths import ensure_tool_paths

ensure_tool_paths()

VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".webm", ".m4v", ".avi"}
AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".flac"}
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS
STAMP = re.compile(
    r"(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})\s*-->\s*"
    r"(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})")
CACHE = Path(os.environ.get("ANKI_GEN_CACHE_DIR",
                            Path.home() / ".cache" / "anki-gen"))
BENCHMARK = CACHE / "transcription-benchmark.json"
WHISPER_CPP_HOME = Path(os.environ.get(
    "ANKI_GEN_WHISPER_CPP_DIR", Path.home() / ".local" / "share" / "anki-gen" / "whisper.cpp"))
WHISPER_CPP_MODEL = CACHE / "whisper.cpp" / "ggml-base.bin"
WHISPER_CPP_URL = ("https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
                   "ggml-base.bin")
WHISPER_CPP_SHA256 = "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe"


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
        print("media_transcribe.py: warn: ffprobe missing; metadata limited",
              file=sys.stderr)
        return {"duration": 0.0, "title": ""}
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


def dedupe_cues(cues: list[dict]) -> list[dict]:
    """Collapse rolling/cumulative captions without losing new words.

    YouTube auto-captions repeat a sliding prefix of the previous cue. Exact
    dedupe leaves the repeated text; this removes the longest shared
    suffix/prefix (at least two words) and drops cues already fully contained.
    """
    out: list[dict] = []
    for cue in cues:
        text = re.sub(r"\s+", " ", str(cue.get("text", ""))).strip()
        if not text:
            continue
        if out:
            prev = out[-1]["text"]
            if text == prev:
                out[-1]["end"] = max(out[-1]["end"], cue.get("end", out[-1]["end"]))
                continue
            if prev in text:                 # sliding caption repeats a phrase
                text = text.split(prev, 1)[1].strip(" -–—:")
                if not text:
                    out[-1]["end"] = max(out[-1]["end"], cue.get("end", out[-1]["end"]))
                    continue
            pw, tw = prev.split(), text.split()
            overlap = 0
            for k in range(min(len(pw), len(tw), 12), 1, -1):
                if pw[-k:] == tw[:k]:
                    overlap = k
                    break
            if overlap:
                text = " ".join(tw[overlap:]).strip()
                if not text:
                    out[-1]["end"] = max(out[-1]["end"], cue.get("end", out[-1]["end"]))
                    continue
        out.append({**cue, "text": text})
    return out


def compact_cues(cues: list[dict], max_seconds: float = 25,
                 max_chars: int = 420) -> str:
    """Timestamped paragraphs for the model, not for the index."""
    lines, buf, start, last = [], [], None, None
    for cue in cues:
        t = float(cue.get("start", 0))
        if start is None:
            start = t
        buf.append(str(cue.get("text", "")))
        last = t
        if (last - start >= max_seconds
                or sum(len(x) for x in buf) >= max_chars):
            lines.append(f"[{int(start)//60:02d}:{int(start)%60:02d}] "
                         + " ".join(buf).strip())
            buf, start = [], None
    if buf:
        lines.append(f"[{int(start)//60:02d}:{int(start)%60:02d}] "
                     + " ".join(buf).strip())
    return "\n\n".join(lines)


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
    return dedupe_cues(cues)


def extract_audio(media: Path, work: Path, seconds_limit: float | None = None) -> Path:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found; local transcription needs ffmpeg")
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


def _model_cached(name: str) -> bool:
    root = CACHE / "models"
    for folder in root.glob(f"models--*--faster-whisper-{name}"):
        snapshots = folder / "snapshots"
        if snapshots.is_dir() and any(p.is_dir() for p in snapshots.iterdir()):
            return True
    return False


def _load_model(name: str, device: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper is unavailable; run setup.sh for whisper.cpp, "
            "or use a sidecar caption") from e
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = _model_cached(name)
    if not cached:
        print(f"media_transcribe.py: downloading Whisper model {name} once to "
              f"{CACHE / 'models'}; later runs stay local", file=sys.stderr)
    return WhisperModel(name, device=device, compute_type="int8",
                        download_root=str(CACHE / "models"),
                        local_files_only=cached)


def _audio_array(path: Path):
    """Decode our own 16 kHz mono WAV instead of letting faster-whisper use PyAV.

    PyAV removed the metadata_errors keyword faster-whisper passes to av.open,
    so feeding an ndarray keeps local transcription working across versions.
    """
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise RuntimeError("transcription audio must be mono 16-bit WAV")
        frames = wav.readframes(wav.getnframes())
    return np.frombuffer(frames, dtype="<i2").astype("float32") / 32768.0


def whisper_cli_path() -> Path | None:
    override = os.environ.get("ANKI_GEN_WHISPER_CLI")
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return path
    for name in ("whisper-cli", "whisper-cpp"):
        found = shutil.which(name)
        if found:
            return Path(found)
    for candidate in (WHISPER_CPP_HOME / "current" / "whisper-cli",
                      WHISPER_CPP_HOME / "current" / "bin" / "whisper-cli"):
        if candidate.is_file():
            return candidate
    return None


def whisper_cpp_model_cached() -> bool:
    return WHISPER_CPP_MODEL.is_file()


def _ensure_whisper_cpp_model() -> Path:
    if WHISPER_CPP_MODEL.is_file():
        return WHISPER_CPP_MODEL
    WHISPER_CPP_MODEL.parent.mkdir(parents=True, exist_ok=True)
    tmp = WHISPER_CPP_MODEL.with_name(WHISPER_CPP_MODEL.name + ".part")
    print("media_transcribe.py: downloading whisper.cpp model ggml-base.bin "
          "(~142 MB) once...", file=sys.stderr)
    try:
        with urllib.request.urlopen(WHISPER_CPP_URL, timeout=60) as response, \
                tmp.open("wb") as out:
            shutil.copyfileobj(response, out)
        digest = hashlib.sha256()
        with tmp.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != WHISPER_CPP_SHA256:
            raise RuntimeError("checksum mismatch")
        tmp.replace(WHISPER_CPP_MODEL)
        print("media_transcribe.py: whisper.cpp model ready", file=sys.stderr)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"local transcription model download failed: {e}") from e
    return WHISPER_CPP_MODEL


def _faster_whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def _whisper_cpp_env(cli: Path) -> dict:
    env = os.environ.copy()
    try:
        root = (WHISPER_CPP_HOME / "current").resolve()
        if root in Path(cli).resolve().parents:
            old = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = str(Path(cli).parent) + (
                os.pathsep + old if old else "")
    except OSError:
        pass
    return env


def _whisper_cpp_command(cli: Path, model: Path, audio: Path, base: Path,
                         language: str | None, prompt: str | None) -> list[str]:
    lang = str(language).strip() if language else "auto"
    if not lang or lang.lower() == "none":
        lang = "auto"
    if lang.lower() != "auto":
        lang = lang.split("-")[0].lower()
    cmd = [str(cli), "-m", str(model), "-f", str(audio), "-l", lang,
           "-osrt", "-of", str(base)]
    if prompt:
        cmd += ["--prompt", str(prompt)]
    return cmd


def _transcribe_whisper_cpp(audio: Path, work: Path, language: str | None,
                            initial_prompt: str | None) -> tuple[list[dict], str]:
    cli = whisper_cli_path()
    if not cli:
        raise RuntimeError("whisper.cpp not found; run setup.sh or install whisper-cli")
    model = _ensure_whisper_cpp_model()
    out_dir = work / "whisper-cpp"
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / audio.stem
    srt = Path(str(base) + ".srt")

    def run(prompt: str | None):
        if srt.exists():
            srt.unlink()
        cmd = _whisper_cpp_command(cli, model, audio, base, language, prompt)
        try:
            return subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=7200, env=_whisper_cpp_env(cli))
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("whisper.cpp timed out") from e

    result = run(initial_prompt)
    if (result.returncode != 0 or not srt.is_file()) and initial_prompt:
        print("media_transcribe.py: whisper.cpp rejected the initial prompt; "
              "retrying without it", file=sys.stderr)
        result = run(None)
    if result.returncode != 0 or not srt.is_file():
        detail = (result.stderr or result.stdout or "").strip()[-500:]
        raise RuntimeError(f"whisper.cpp failed: {detail}")
    model_name = model.stem.removeprefix("ggml-")
    return parse_captions(srt), f"whisper.cpp:{model_name}"


def _run(audio: Path, model_name: str, language: str | None,
         initial_prompt: str | None, device: str) -> float:
    model = _load_model(model_name, device)
    segments, _ = model.transcribe(
        _audio_array(audio), language=language, vad_filter=True,
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
    if _faster_whisper_available():
        try:
            chosen = choose_model(audio, language, model, device)
            loaded = _load_model(chosen, device)
            segments, _ = loaded.transcribe(
                _audio_array(audio), language=language, vad_filter=True,
                initial_prompt=initial_prompt)
            cues = []
            for seg in segments:
                text = re.sub(r"\s+", " ", str(seg.text or "")).strip()
                if text:
                    cues.append({"start": float(seg.start), "end": float(seg.end),
                                 "text": text})
            return cues, chosen
        except Exception as e:
            if not whisper_cli_path():
                raise
            print(f"media_transcribe.py: faster-whisper failed ({e}); "
                  "falling back to whisper.cpp", file=sys.stderr)
    if whisper_cli_path():
        return _transcribe_whisper_cpp(audio, work, language, initial_prompt)
    raise RuntimeError(
        "local transcription unavailable: install faster-whisper or whisper.cpp; "
        "sidecar captions and YouTube still work")
