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
import frames  # noqa: E402
import media_transcribe as mt  # noqa: E402
import ytdlp  # noqa: E402


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

        # whisper.cpp fallback: no faster-whisper, fake CLI emits a real SRT.
        fake = td / "fake-whisper-cli"
        fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "from pathlib import Path\n"
            "args = sys.argv\n"
            "base = Path(args[args.index('-of') + 1])\n"
            "Path(args[args.index('--record') + 1]).write_text(json.dumps(args))\n"
            "Path(str(base) + '.srt').write_text("
            "'1\\n00:00:00,000 --> 00:00:02,000\\nFake whisper.cpp transcript.\\n')\n"
        )
        fake.chmod(0o755)
        model = td / "ggml-base.bin"
        model.write_bytes(b"not a real model")
        recorded = td / "args.json"
        with mock.patch.object(mt, "_faster_whisper_available", return_value=False), \
             mock.patch.object(mt, "WHISPER_CPP_MODEL", model):
            # --record is test-only; the wrapper appends it so the production
            # argument builder stays clean.
            wrapper = td / "whisper-cli"
            wrapper.write_text(
                f"#!/usr/bin/env bash\nexec {fake} \"$@\" --record {recorded}\n")
            wrapper.chmod(0o755)
            with mock.patch.object(mt, "whisper_cli_path", return_value=wrapper):
                cues, source = mt.transcribe(media, work, model="auto",
                                             language="en", force=True)
        assert source == "whisper.cpp:base" and cues, (source, cues)
        assert cues[0]["text"] == "Fake whisper.cpp transcript.", cues
        argv = json.loads(recorded.read_text())
        assert "-m" in argv and argv[argv.index("-m") + 1] == str(model), argv
        assert "-f" in argv and argv[argv.index("-f") + 1].endswith(".wav"), argv
        assert argv[argv.index("-l") + 1] == "en", argv
        assert "-osrt" in argv and "-of" in argv, argv
        assert "-np" not in argv and "-t" not in argv, argv
        assert "--prompt" not in argv, argv
        with mock.patch.object(mt, "_faster_whisper_available", return_value=False), \
             mock.patch.object(mt, "WHISPER_CPP_MODEL", model), \
             mock.patch.object(mt, "whisper_cli_path", return_value=wrapper):
            mt.transcribe(media, work, model="auto", language=None,
                          initial_prompt="course terms", force=True)
        argv = json.loads(recorded.read_text())
        assert argv[argv.index("-l") + 1] == "auto", argv
        assert argv[argv.index("--prompt") + 1] == "course terms", argv
        print("ok    whisper.cpp backend args and SRT fallback")

        # Missing ffprobe degrades metadata, not the transcription path.
        with mock.patch.object(mt.shutil, "which", return_value=None):
            assert mt.probe(media) == {"duration": 0.0, "title": ""}
        print("ok    missing ffprobe degrades gracefully")

        # Missing ffmpeg is a clear failure, not a traceback.
        with mock.patch.object(mt.shutil, "which", return_value=None):
            try:
                mt.extract_audio(media, work)
            except RuntimeError as e:
                assert "ffmpeg" in str(e), e
            else:
                raise AssertionError("missing ffmpeg did not raise")
        print("ok    missing ffmpeg fails clearly")

        # No backend produces a clear error, not a traceback.
        with mock.patch.object(mt, "_faster_whisper_available", return_value=False), \
             mock.patch.object(mt, "whisper_cli_path", return_value=None):
            try:
                mt.transcribe(media, work, force=True)
            except RuntimeError as e:
                assert "unavailable" in str(e), e
            else:
                raise AssertionError("missing backend did not raise")
        print("ok    missing local backend fails clearly")

        # Optional video tooling fails with a feature message, not a traceback.
        with mock.patch.object(ytdlp, "available", return_value=False):
            try:
                ytdlp.run(("--version",))
            except RuntimeError as e:
                assert "yt-dlp is not installed" in str(e), e
            else:
                raise AssertionError("missing yt-dlp did not raise")
        with mock.patch.object(frames.subprocess, "run",
                               side_effect=FileNotFoundError("ffmpeg")):
            result = frames.run(["ffmpeg", "-version"])
        assert result.returncode == 127 and "not found" in result.stderr, result
        print("ok    missing optional video tooling fails clearly")

        # Doctor has one local-audio verdict and no stale faster-whisper warning.
        doctor = subprocess.run(
            [sys.executable, str(SCRIPTS / "doctor.py")],
            capture_output=True, text=True)
        assert doctor.returncode == 0, doctor.stderr
        assert doctor.stdout.count("Local transcription:") == 1, doctor.stdout
        assert "warn  faster-whisper" not in doctor.stdout, doctor.stdout
        print("ok    doctor has one local-audio verdict")

        # Model auto benchmark caches the choice and does not re-run.
        sample = td / "bench.wav"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                        "-ar", "16000", "-ac", "1", str(sample)], check=True)
        arr = mt._audio_array(sample)
        assert arr.dtype.name == "float32" and len(arr) > 0, arr
        assert float(abs(arr).max()) <= 1.0, arr

        model_cache = td / "models" / "models--Systran--faster-whisper-base.en" / "snapshots" / "x"
        model_cache.mkdir(parents=True)
        with mock.patch.object(mt, "CACHE", td):
            assert mt._model_cached("base.en") is True
            assert mt._model_cached("small.en") is False
        print("ok    local WAV decode and model cache detection")

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
