#!/usr/bin/env python3
"""Offline tests for local media ingestion and model selection."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import extract_video  # noqa: E402
import media_transcribe as mt  # noqa: E402


def make_media(path: Path, seconds: int = 1) -> None:
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"color=c=black:s=160x120:d={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-shortest", "-c:v", "libx264", "-c:a", "aac", str(path)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def args(**kw):
    base = dict(title="", model="base.en", language="en", device="cpu",
                force_transcribe=False, initial_prompt=None, images="no")
    base.update(kw)
    return SimpleNamespace(**base)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        media = td / "recording with space.mp4"
        make_media(media)
        assert mt.media_id(media).startswith("local-")
        assert mt.media_files(str(td)) == [media]

        vtt = td / "recording with space.vtt"
        vtt.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nA local lecture sentence.\n")
        cues = mt.parse_captions(vtt)
        assert cues == [{"start": 0.0, "end": 1.5, "text": "A local lecture sentence."}], cues

        srt = td / "captions.srt"
        srt.write_text("1\n00:00:01,000 --> 00:00:02,500\nSecond local sentence.\n")
        assert mt.parse_captions(srt)[0]["text"] == "Second local sentence."

        work = td / "work"
        rc = extract_video.local_source(str(media), work, args())
        assert rc == 0
        videos = [json.loads(x) for x in (work / "videos.jsonl").read_text().splitlines()]
        assert len(videos) == 1 and videos[0]["source_type"] == "local"
        assert videos[0]["source_label"].startswith("Local recording -")
        assert videos[0]["transcript_source"] == "sidecar:vtt"
        assert Path(videos[0]["compact_file"]).is_file(), videos[0]
        assert videos[0]["compact_tokens"] > 0, videos[0]
        assert (work / "transcripts.md").is_file(), "combined transcript missing"
        assert "Local recording - recording with space" in (work / "video_toc.md").read_text()
        assert not (work / "frames.jsonl").exists()
        print("ok    local sidecar ingestion and labels")

        audio = td / "audio.m4a"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(media), "-vn", str(audio)], check=True)
        audio.with_suffix(".srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nAudio-only transcript.\n")
        audio_work = td / "audio-work"
        rc = extract_video.local_source(str(audio), audio_work, args(images="yes"))
        assert rc == 0 and not (audio_work / "frames.jsonl").exists()
        print("ok    audio-only skips frames")

        # Sidecar wins over the model; no faster-whisper import is needed.
        with mock.patch.object(mt, "_load_model", side_effect=AssertionError("model called")):
            cues, source = mt.transcribe(media, work, model="base.en")
        assert source == "sidecar:vtt" and cues, (source, cues)
        print("ok    sidecar bypasses faster-whisper")

        # Model auto benchmark caches the choice and does not re-run.
        sample = td / "bench.wav"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                        "-ar", "16000", "-ac", "1", str(sample)], check=True)
        cache = td / "bench.json"
        calls = []
        def fake_run(audio, model_name, language, prompt, device):
            calls.append(model_name)
            return 1.0 if model_name == "base.en" else 4.0
        with mock.patch.object(mt, "BENCHMARK", cache), \
             mock.patch.object(mt, "_run", side_effect=fake_run):
            chosen = mt.choose_model(sample, "en", "auto", "cpu")
            again = mt.choose_model(sample, "en", "auto", "cpu")
        assert chosen == "small.en" and again == chosen and calls == ["base.en", "small.en"], calls
        assert json.loads(cache.read_text())["chosen"] == "small.en"
        print("ok    auto model benchmark/cache")

        # An explicit model never benchmarks.
        calls.clear()
        with mock.patch.object(mt, "_run", side_effect=fake_run):
            assert mt.choose_model(sample, "en", "tiny.en", "cpu") == "tiny.en"
        assert calls == [], calls
        assert mt.choose_model(sample, "auto", "auto", "cpu") == "small"
        assert mt.choose_model(sample, "es", "auto", "cpu") == "small"
        print("ok    explicit model bypasses benchmark; non-English uses multilingual")

    print("\nPASS  local media hardening")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
