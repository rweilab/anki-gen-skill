#!/usr/bin/env python3
"""Offline video tests: VTT parsing, playlist entries, frame extraction/picker."""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
import zipfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from extract_video import (chunks, entries, get_vtt, index, parse_items, parse_vtt,
                           source_label, video_url)  # noqa: E402
from frames import late_best  # noqa: E402

VTT = """WEBVTT

00:00:01.000 --> 00:00:03.000
This diagram shows a state machine.

00:00:03.000 --> 00:00:03.500
This diagram shows a state machine.

00:00:04.000 --> 00:00:06.000
The timing diagram has two clocks.
"""


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        vtt = td / "sample.vtt"
        vtt.write_text(VTT)
        cues = parse_vtt(vtt)
        assert len(cues) == 2, cues
        assert cues[0]["start"] == 1.0 and "state machine" in cues[0]["text"], cues
        rows = chunks(cues, "YouTube test")
        assert rows and rows[0]["loc"] == "00:01", rows
        print("ok    VTT parse and dedupe")

        meta = {"_type": "playlist", "entries": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}
        assert [e["id"] for e in entries(meta, True, "")] == ["a", "b", "c"]
        assert [e["id"] for e in entries(meta, False, "2-3")] == ["b", "c"]
        assert [e["id"] for e in entries(meta, False, "")] == ["a"]
        assert parse_items("2,4", 4) == [1, 3]
        print("ok    playlist/range selection")

        single = source_label("Digi-Key", "STM32 GPIO Overview: Alternate Functions and Timing")
        series = source_label("Digi-Key", "RTOS Part 1: Tasks, Scheduling, and Context Switching",
                              "RTOS Basics", 1)
        assert single == "Digi-Key - STM32 GPIO Overview: Alternate Functions and Timing", single
        assert series == ("Digi-Key - RTOS Basics 01 - RTOS Part 1: Tasks, Scheduling, "
                          "and Context Switching"), series
        cleaned = source_label("DigiKey", "Introduction to RTOS Part 3 - Task Scheduling | "
                              "Digi-Key Electronics", "Introduction to RTOS", 3)
        assert cleaned == ("DigiKey - Introduction to RTOS 03 - Introduction to RTOS "
                           "Part 3 - Task Scheduling"), cleaned
        assert video_url("ID", 754) == "https://www.youtube.com/watch?v=ID&t=754"
        assert video_url("ID", 754, "LIST") == "https://www.youtube.com/watch?v=ID&list=LIST&t=754"
        print("ok    full-title source labels and timestamp URLs")

        cache = td / "cache" / "transcripts"
        cache.mkdir(parents=True)
        cached = cache / "cached.en.vtt"
        cached.write_text("WEBVTT\n")
        assert get_vtt({"id": "cached"}, td / "cache", "en.*") == cached
        print("ok    cached captions are reused")

        db = td / "mixed-index.sqlite"
        con = sqlite3.connect(db)
        con.execute("CREATE VIRTUAL TABLE chunks USING fts5(id UNINDEXED, source, loc, heading, text)")
        con.execute("INSERT INTO chunks VALUES (1,'PDF p.1','p.1','Source','pdf text')")
        con.commit(); con.close()
        work_idx = td / "mixed-work"
        work_idx.mkdir()
        (work_idx / "source_index.sqlite").write_bytes(db.read_bytes())
        index(work_idx, [{"source": "Digi-Key - Video @ 00:01", "loc": "00:01",
                          "heading": "Transcript", "text": "video text"}])
        con = sqlite3.connect(work_idx / "source_index.sqlite")
        try:
            sources = {r[0] for r in con.execute("select source from chunks")}
        finally:
            con.close()
        assert sources == {"PDF p.1", "Digi-Key - Video @ 00:01"}, sources
        print("ok    video index preserves existing PDF chunks")

        if not all(shutil.which(x) for x in ("ffmpeg", "tesseract")):
            print("skip  ffmpeg/tesseract missing; frame test skipped")
            return 0
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            print("skip  Pillow missing; frame test skipped")
            return 0

        img = td / "slide.png"
        im = Image.new("RGB", (1280, 720), "white")
        d = ImageDraw.Draw(im)
        d.rectangle((80, 80, 1200, 640), outline="black", width=5)
        d.text((140, 160), "STATE MACHINE", fill="black")
        d.text((140, 220), "IDLE -> RUN -> DONE", fill="black")
        d.rectangle((180, 340, 480, 500), outline="black", width=4)
        d.text((210, 400), "IDLE", fill="black")
        im.save(img)
        video = td / "slide.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-loop", "1", "-i", str(img), "-t", "6", "-r", "2",
                        "-vf", "scale=1280:720", "-pix_fmt", "yuv420p", str(video)],
                       check=True)
        transcript = td / "transcript.jsonl"
        transcript.write_text(json.dumps({"start": 1, "end": 2,
                                          "text": "This diagram shows a state machine."}) + "\n")
        work = td / "work"
        r = subprocess.run([sys.executable, str(SCRIPTS / "frames.py"),
                            "--work", str(work), "--video-id", "test",
                            "--url", "https://www.youtube.com/watch?v=test",
                            "--source-label", "Digi-Key - RTOS Basics 01 - State Machine Details",
                            "--source-url", "https://www.youtube.com/watch?v=test&list=LIST&t=0",
                            "--video-file", str(video), "--title", "Test",
                            "--transcript", str(transcript), "--auto"],
                           capture_output=True, text=True)
        assert r.returncode == 0, (r.stdout, r.stderr)
        frames = [json.loads(x) for x in (work / "frames.jsonl").read_text().splitlines()]
        assert frames, "no frames"
        assert all(Path(work / f["file"]).is_file() for f in frames)
        assert all(f["source"].startswith("Digi-Key - RTOS Basics 01 - State Machine Details @") for f in frames)
        assert all("list=LIST&t=" in f["source_url"] for f in frames)
        assert any(f.get("best") for f in frames), frames
        assert "needs_vision" in frames[0], frames[0]
        assert "image-vision" in (work / "frames.md").read_text()
        print(f"ok    frame extraction/picker ({len(frames)} candidate(s))")

        # An image-only diagram must not be filtered out for having no OCR words.
        diagram = td / "diagram.png"
        dim = Image.new("RGB", (1280, 720), "white")
        dd = ImageDraw.Draw(dim)
        dd.ellipse((280, 120, 1000, 600), outline="black", width=10)
        dd.line((640, 40, 640, 680), fill="black", width=8)
        dd.line((100, 360, 1180, 360), fill="black", width=8)
        dd.rectangle((500, 250, 780, 470), outline="black", width=7)
        dim.save(diagram)
        dvid = td / "diagram.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-loop", "1", "-i", str(diagram), "-t", "5", "-r", "2",
                        "-vf", "scale=1280:720", "-pix_fmt", "yuv420p", str(dvid)],
                       check=True)
        dtrans = td / "diagram.jsonl"
        dtrans.write_text(json.dumps({"start": 1, "end": 2,
                                      "text": "This diagram shows the atomic structure."}) + "\n")
        r = subprocess.run([sys.executable, str(SCRIPTS / "frames.py"),
                            "--work", str(work), "--video-id", "diagram",
                            "--url", "https://www.youtube.com/watch?v=diagram",
                            "--source-label", "Test - Atomic Structure",
                            "--source-url", "https://www.youtube.com/watch?v=diagram&t=0",
                            "--video-file", str(dvid), "--title", "Diagram",
                            "--transcript", str(dtrans), "--auto"],
                           capture_output=True, text=True)
        assert r.returncode == 0, (r.stdout, r.stderr)
        all_frames = [json.loads(x) for x in (work / "frames.jsonl").read_text().splitlines()]
        darts = [f for f in all_frames if f["video_id"] == "diagram"]
        assert darts and any(f.get("attach") in ("direct", "confirm") for f in darts), darts
        md = (work / "frames.md").read_text()
        assert "test " in md and "diagram " in md, md
        print("ok    image-only diagram and merged frames.md")

        # Same-shot frames: the latest high frame wins; a lower-quality cut
        # after it must not steal the pick.
        shot = [
            {"time": 1, "quality": "high", "attach": "direct", "dhash": 0,
             "edge": 0.03, "focus": 2.5, "color": 0.0},
            {"time": 3, "quality": "high", "attach": "direct", "dhash": 1,
             "edge": 0.04, "focus": 2.6, "color": 0.0},
            {"time": 5, "quality": "high", "attach": "direct", "dhash": 2,
             "edge": 0.05, "focus": 2.7, "color": 0.0},
            {"time": 9, "quality": "high", "attach": "direct", "dhash": 0xFFFFFFFFFFFFFFFF,
             "edge": 0.01, "focus": 2.0, "color": 0.0},
        ]
        assert late_best(shot)["time"] == 5, late_best(shot)
        print("ok    late-frame shot selection")

        # No transcript cues: the visual-only fallback must still find the diagram.
        empty = td / "empty.jsonl"
        empty.write_text("")
        r = subprocess.run([sys.executable, str(SCRIPTS / "frames.py"),
                            "--work", str(work), "--video-id", "scan",
                            "--url", "https://www.youtube.com/watch?v=scan",
                            "--source-label", "Test - Visual Scan",
                            "--source-url", "https://www.youtube.com/watch?v=scan&t=0",
                            "--video-file", str(dvid), "--title", "Scan",
                            "--transcript", str(empty), "--auto"],
                           capture_output=True, text=True)
        assert r.returncode == 0, (r.stdout, r.stderr)
        all_frames = [json.loads(x) for x in (work / "frames.jsonl").read_text().splitlines()]
        scanned = [f for f in all_frames if f["video_id"] == "scan"]
        assert scanned, "fallback scan produced no candidates"
        assert any(f.get("caption") == "visual scan" and
                   f.get("attach") in ("direct", "confirm") for f in scanned), scanned
        assert "visual scan" in (work / "frames.md").read_text()
        print("ok    visual fallback scan")

        card = {"front": "Which state machine state is idle?",
                "back": "The left box is IDLE.\n\n**Why:** the diagram labels it.",
                "layer": "L2", "topic": "Video", "objects": ["state_machine"],
                "deck": "VIDEO::TEST",
                "source": "Digi-Key - RTOS Basics 01 - State Machine Details @ 00:01",
                "source_url": "https://www.youtube.com/watch?v=test&list=LIST&t=1",
                "media": [{"file": frames[0]["file"], "side": "back",
                           "caption": "state machine", "source": "YouTube test @ 00:01",
                           "source_url": frames[0]["source_url"]}]}
        cards = td / "cards.jsonl"
        cards.write_text(json.dumps(card) + "\n")
        apkg = td / "video.apkg"
        r = subprocess.run([sys.executable, str(SCRIPTS / "build_apkg.py"), str(cards),
                            str(apkg), "--deck-name", "VIDEO::TEST", "--media",
                            "--media-root", str(work), "--strict"],
                           capture_output=True, text=True)
        assert r.returncode == 0, (r.stdout, r.stderr)
        r = subprocess.run([sys.executable, str(SCRIPTS / "validate_apkg.py"), str(apkg)],
                           capture_output=True, text=True)
        assert r.returncode == 0, (r.stdout, r.stderr)
        with tempfile.TemporaryDirectory() as extract:
            with zipfile.ZipFile(apkg) as z:
                z.extract("collection.anki2", extract)
            con = sqlite3.connect(Path(extract) / "collection.anki2")
            try:
                flds = "\n".join(row[0] for row in con.execute("select flds from notes"))
            finally:
                con.close()
        assert "list=LIST&amp;t=" in flds or "list=LIST&t=" in flds, flds
        assert "Image:" not in flds, flds
        assert "<a href" not in flds, flds
        print("ok    video frame attaches with plain source URL")

    print("\nPASS  video hardening")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
