#!/usr/bin/env python3
"""Pipeline local-media and build/validate checks, offline."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from preflight import check  # noqa: E402
import pipeline  # noqa: E402
from unittest import mock  # noqa: E402


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        os.environ["ANKI_GEN_DATA_HOME"] = str(td / "xdg")
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
        assert "media      1 video(s)" in r.stdout, r.stdout
        assert "[video 1/1]" in r.stdout, r.stdout
        assert "read transcripts.md once" in r.stdout, r.stdout
        assert (work / "videos.jsonl").is_file(), r.stdout
        assert pipeline._media_images([str(media)], "auto") == "yes"
        assert pipeline._media_images([str(media)], "no") == "no"
        audio = td / "audio.m4a"
        r = run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                 "-i", str(media), "-vn", str(audio)], td)
        assert r.returncode == 0, r.stderr
        assert pipeline._media_images([str(audio)], "auto") == "no"
        state = json.loads(run([sys.executable, str(SCRIPTS / "pipeline.py"),
                                "--out", str(work), "--status"], td).stdout)
        assert any(v.get("status") == "done" for v in state.get("media", {}).values()), state
        resumed = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                       "--sources", str(media), "--out", str(work),
                       "--images", "no", "--resume"], td)
        assert resumed.returncode == 0, (resumed.stdout, resumed.stderr)
        assert "resume skip" in resumed.stdout, resumed.stdout
        print("ok    pipeline local media branch, state, and resume")

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

        notes = td / "notes.txt"
        notes.write_text("A voltage source maintains a fixed potential difference.\n")
        doc_work = td / "doc-work"
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--sources", str(notes), "--out", str(doc_work)], td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        combined = (doc_work / "sources.md").read_text()
        assert "## notes" in combined, combined
        assert "fixed potential difference" in combined, combined
        assert "read sources.md once" in r.stdout, r.stdout
        assert "transcripts.md" not in r.stdout, r.stdout
        print("ok    pipeline writes one combined sources.md")

        # Two URL sources must merge their metadata, not leave only the last.
        merged = td / "url-merge"
        merged.mkdir()
        def fake_run(cmd, log):
            src = cmd[2]
            vid = src.rsplit("/", 1)[-1]
            (merged / "videos.jsonl").write_text(json.dumps(
                {"id": vid, "title": vid, "source_label": f"ch - {vid}",
                 "source_url": src, "cues": 1}) + "\n")
            (merged / "video_meta.json").write_text(json.dumps(
                {"videos": [{"id": vid, "cues": 1}], "chunks": 1,
                 "failures": []}))
            log.write_text("fake media log\n")
            return 0
        with mock.patch.object(pipeline, "_run_media", side_effect=fake_run):
            info = pipeline.stage_media(
                ["https://youtu.be/a", "https://youtu.be/b"], merged, "no",
                "auto", "en", False)
        assert info["videos"] == 2, info
        assert len((merged / "videos.jsonl").read_text().splitlines()) == 2
        toc = (merged / "video_toc.md").read_text()
        assert "youtu.be/a" in toc and "youtu.be/b" in toc, toc
        print("ok    pipeline merges multiple video sources")

        # A previous run cannot still be running. Mark it interrupted, then
        # record this run's failure honestly.
        state_work = td / "state"
        state_work.mkdir()
        pipeline._write_state(state_work, {
            "media": {"old-source": {"status": "running"}}})
        def fail_run(cmd, log):
            log.write_text("boom\n")
            return 1
        import contextlib
        import io
        buf = io.StringIO()
        with mock.patch.object(pipeline, "_run_media", side_effect=fail_run), \
                contextlib.redirect_stdout(buf):
            pipeline.stage_media(["https://youtu.be/fail"], state_work, "no",
                                 "auto", "en", False)
        state = json.loads((state_work / "pipeline_state.json").read_text())
        assert state["media"]["old-source"]["status"] == "interrupted", state
        assert state["media"]["https://youtu.be/fail"]["status"] == "failed", state
        assert state["status"] == "failed" and state["media_failed"] == 1, state
        assert "[media 1/1] start" in buf.getvalue(), buf.getvalue()
        (state_work / "video_meta.json").write_text(json.dumps({
            "videos": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "failures": [{"id": "c"}],
        }))
        state = pipeline._load_state(state_work)
        state["source"] = "s"
        state["media"] = {"s": {"status": "running"}}
        pipeline._write_state(state_work, state)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert pipeline.main(["--out", str(state_work), "--status"]) == 0
        status = json.loads(buf.getvalue())
        assert status["media"]["s"]["videos_done"] == 2, status
        assert status["media"]["s"]["videos_total"] == 3, status
        print("ok    media state marks interrupted and failed")

        cards = td / "cards.jsonl"
        cards.write_text(json.dumps({
            "front": "Why does a local recording need a citation?",
            "back": "**Why:** the learner must reopen the exact timestamp.",
            "layer": "L2", "topic": "Local Media", "objects": [],
            "deck": "LOCAL::TEST", "source": "local recording @ 00:00",
        }) + "\n")
        apkg = td / "local.apkg"
        gates = work / "gates"
        gates.mkdir(parents=True)
        for name in ("intake.md", "scope_gate.md", "authoring_ledger.md"):
            (gates / name).write_text("evidence\n")
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(cards), "--out", str(gates),
                 "--gates-only", "--build", "--deck-name", "LOCAL::TEST",
                 "--out-apkg", str(apkg), "--strict"], td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert apkg.is_file() and "validate   1 note" in r.stdout, (r.stdout, r.stderr)
        assert "context    " in r.stdout and "card(s)" in r.stdout, r.stdout
        assert list((td / "xdg" / "decks").glob("*/cards.jsonl")), r.stdout
        assert "quality    static 0 error(s)" in r.stdout and "NOT CERTIFIED" in r.stdout, r.stdout
        assert "provenance 1/1 (0 derived)" in r.stdout, r.stdout
        print("ok    pipeline build+validate+context and quality status")

        risk_cards = td / "risk.jsonl"
        risk_cards.write_text(json.dumps({
            "front": "What does the title frame show?",
            "back": "A title slide.", "layer": "L2", "topic": "Risk",
            "deck": "RISK::TEST", "source": "Lec 1 p.1",
            "media": [{"file": "media/title.png", "side": "back"}],
        }) + "\n")
        risk = td / "risk"
        risk.mkdir()
        for name in ("intake.md", "scope_gate.md", "authoring_ledger.md"):
            (risk / name).write_text("evidence\n")
        (risk / "frames.jsonl").write_text(json.dumps({
            "file": "media/title.png", "best": True, "attach": "direct",
            "title_like": True, "quality": "high", "caption": "Lecture: title",
            "source": "Lec 1"}) + "\n")
        blocked = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                       "--cards", str(risk_cards), "--out", str(risk),
                       "--gates-only", "--build", "--deck-name", "RISK::TEST",
                       "--out-apkg", str(td / "risk.apkg")], td)
        assert blocked.returncode == 1 and "media risks remain" in blocked.stderr, (
            blocked.stdout, blocked.stderr)
        print("ok    pipeline blocks objective media risks")

        merged_apkg = td / "merged.apkg"
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(cards), "--out", str(gates),
                 "--gates-only", "--build", "--deck-name", "LOCAL::TEST",
                 "--out-apkg", str(merged_apkg), "--merge-existing", str(apkg)], td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert "already in" in r.stdout, r.stdout
        print("ok    pipeline passes --merge-existing through")

        no_gate = work / "no-gate"
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(cards), "--out", str(no_gate),
                 "--gates-only", "--build", "--deck-name", "LOCAL::TEST",
                 "--out-apkg", str(td / "no-gate.apkg")], td)
        assert r.returncode != 0 and "missing required evidence" in r.stderr, (
            r.stdout, r.stderr)
        print("ok    pipeline refuses build without evidence artifacts")

        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(cards), "--out", str(td / "oops.apkg"),
                 "--gates-only"], td)
        assert r.returncode == 2 and "not the .apkg" in r.stderr, (r.stdout, r.stderr)
        print("ok    pipeline rejects an .apkg work directory")

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
