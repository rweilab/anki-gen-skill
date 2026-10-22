#!/usr/bin/env python3
"""Pipeline local-media and build/validate checks, offline."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from preflight import check  # noqa: E402


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        media = td / "local recording.mp4"
        r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i", "color=c=black:s=160x120:d=1",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                 "-shortest", "-c:v", "libx264", "-c:a", "aac", str(media)], td)
        assert r.returncode == 0, r.stderr
        media.with_suffix(".vtt").write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nLocal pipeline sentence.\n")

        work = td / "work"
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--sources", str(media), "--out", str(work), "--images", "no"], td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert "media      1 source" in r.stdout, r.stdout
        assert (work / "videos.jsonl").is_file(), r.stdout
        print("ok    pipeline local media branch")

        second = td / "second.mp4"
        r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "lavfi", "-i", "color=c=blue:s=160x120:d=1",
                 "-f", "lavfi", "-i", "sine=frequency=660:duration=1",
                 "-shortest", "-c:v", "libx264", "-c:a", "aac", str(second)], td)
        assert r.returncode == 0, r.stderr
        second.with_suffix(".srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nSecond local sentence.\n")
        batch_work = td / "batch-work"
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--sources", str(media), str(second), "--out", str(batch_work),
                 "--images", "no"], td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        vids = [json.loads(x) for x in (batch_work / "videos.jsonl").read_text().splitlines()]
        assert len(vids) == 2, (r.stdout, vids)
        assert {v["source_type"] for v in vids} == {"local"}
        print("ok    pipeline multi-file local batch")

        cards = td / "cards.jsonl"
        cards.write_text(json.dumps({
            "front": "Why does a local recording need a citation?",
            "back": "**Why:** the learner must reopen the exact timestamp.",
            "layer": "L2", "topic": "Local Media", "objects": [],
            "deck": "LOCAL::TEST", "source": "local recording @ 00:00",
        }) + "\n")
        apkg = td / "local.apkg"
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(cards), "--out", str(work / "gates"),
                 "--gates-only", "--build", "--deck-name", "LOCAL::TEST",
                 "--out-apkg", str(apkg), "--strict"], td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert apkg.is_file() and "validate   1 note" in r.stdout, (r.stdout, r.stderr)
        print("ok    pipeline build+validate")

        bad = td / "bad.jsonl"
        bad.write_text(json.dumps({
            "front": "Which enzyme splits fructose-1,6-bisphosphate?",
            "back": "It splits into DHAP and G3P.", "layer": "L1",
            "topic": "Glycolysis", "objects": [], "deck": "LOCAL::TEST",
            "source": "local recording @ 00:00",
        }) + "\n")
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(bad), "--out", str(work / "bad"),
                 "--gates-only", "--build", "--deck-name", "LOCAL::TEST",
                 "--out-apkg", str(td / "bad.apkg"), "--strict"], td)
        assert r.returncode != 0 and not (td / "bad.apkg").exists(), (r.stdout, r.stderr)
        print("ok    pipeline refuses build on alignment error")

        fake_home = td / "home"
        (fake_home / ".claude" / "skills" / ".backups" / "old").mkdir(parents=True)
        (fake_home / ".claude" / "skills" / ".backups" / "old" / "SKILL.md").write_text("old")
        errors, _ = check(fake_home)
        assert errors and "backup" in errors[0], errors
        print("ok    preflight rejects stale backup SKILL.md")

    print("\nPASS  pipeline hardening")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
