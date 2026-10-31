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
from cardid import card_hash  # noqa: E402
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
        assert (doc_work / "sources.ready").is_file(), r.stdout
        print("ok    pipeline writes one combined sources.md atomically")
        course = td / "course"
        course.mkdir()
        (course / "visible.txt").write_text("The visible source sentence.\n")
        (course / "work").mkdir()
        (course / "work" / "hidden.txt").write_text("The work-dir sentence.\n")
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--sources", str(course), "--out", str(course / "work")], td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        combined = (course / "work" / "sources.md").read_text()
        assert "visible source sentence" in combined, combined
        assert "work-dir sentence" not in combined, combined
        print("ok    directory extraction excludes the work dir")

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
                 "--out-apkg", str(apkg)], td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert apkg.is_file() and "validate   1 note" in r.stdout, (r.stdout, r.stderr)
        assert "context    " not in r.stdout, r.stdout
        assert not list((td / "xdg" / "decks").glob("*/cards.jsonl")), r.stdout
        assert "quality    static 0 error(s)" in r.stdout and "READY" in r.stdout, r.stdout
        assert "status     DONE" in r.stdout, r.stdout
        assert "provenance 1/1 (0 derived)" in r.stdout, r.stdout
        context_apkg = td / "local-context.apkg"
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(cards), "--out", str(gates),
                 "--gates-only", "--build", "--context", "--deck-name", "LOCAL::TEST",
                 "--out-apkg", str(context_apkg)], td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert "context    " in r.stdout and "card(s)" in r.stdout, (r.stdout, r.stderr)
        assert list((td / "xdg" / "decks").glob("*/cards.jsonl")), r.stdout
        print("ok    pipeline build+validate+opt-in context and quality status")
        bad = td / "bad.jsonl"
        bad.write_text(json.dumps({
            "front": "Why does a missing source fail?",
            "back": "The gate cannot trace the claim. **Why:** provenance is required.",
            "layer": "L2", "topic": "Provenance", "deck": "LOCAL::TEST",
        }) + "\n")
        bad_work = td / "bad-work"
        bad_work.mkdir()
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(bad), "--out", str(bad_work), "--gates-only"], td)
        assert r.returncode != 0, (r.stdout, r.stderr)
        assert "error      card 1" in r.stdout and "fix:" in r.stdout, r.stdout
        gates_json = json.loads((bad_work / "gates.json").read_text())
        assert gates_json["errors"], gates_json
        print("ok    gates print exact errors, fixes, and gates.json")

        lock_work = td / "lock-work"
        lock_work.mkdir()
        (lock_work / "pipeline_state.json").write_text(json.dumps({
            "stage": "extract", "status": "running", "pid": os.getpid()}) + "\n")
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--sources", str(notes), "--out", str(lock_work)], td)
        assert r.returncode != 0 and "another extraction" in r.stderr, (r.stdout, r.stderr)
        print("ok    live extraction lock refuses a second extractor")

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

        review_work = td / "review-work"
        review_work.mkdir()
        review_cards = td / "review-cards.jsonl"
        review_rows = [
            {"front": "Which method applies to this steady-flow device?",
             "back": "Use the steady-flow energy equation. **Why:** mass and energy balances.",
             "layer": "Procedure", "topic": "Turbines", "objects": ["procedural"],
             "deck": "LOCAL::TEST", "source": "Lec 1 p.1", "kc": "thermo.steady_flow",
             "stratum": "procedure"},
            {"front": "Why does the entropy of a closed system increase?",
             "back": "Because accessible microstates increase. **Why:** the second law.",
             "layer": "L2", "topic": "Entropy", "deck": "LOCAL::TEST",
             "source": "Lec 1 p.2", "kc": "thermo.entropy", "stratum": "mechanism"},
        ]
        review_cards.write_text("".join(json.dumps(x) + "\n" for x in review_rows))
        for name in ("intake.md", "scope_gate.md", "authoring_ledger.md"):
            (review_work / name).write_text("evidence\n")
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(review_cards), "--out", str(review_work),
                 "--gates-only"], td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        feedback = [
            {"n": 1, "hash": card_hash(review_rows[0]), "score": 1,
             "comment": "Too easy; ask which condition selects it."},
            {"n": 2, "hash": card_hash(review_rows[1]), "score": 5,
             "comment": "Reject; duplicate of another card."},
        ]
        (review_work / "review_feedback.jsonl").write_text(
            "".join(json.dumps(x) + "\n" for x in feedback))
        (review_work / "review_done").write_text(json.dumps(
            {"deck_note": "Use the course's method names."}))
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(review_cards), "--out", str(review_work),
                 "--gates-only", "--build", "--deck-name", "LOCAL::TEST",
                 "--out-apkg", str(td / "review.apkg")], td)
        assert r.returncode != 0 and "review_actions.json is open" in r.stderr, (
            r.stdout, r.stderr)
        actions = json.loads((review_work / "review_actions.json").read_text())
        assert actions["status"] == "open", actions
        assert actions["score1"] and actions["score1"][0]["action"] == "", actions
        assert actions["score5"] and actions["score5"][0]["hash"], actions
        assert actions["deck_note"] == "Use the course's method names.", actions
        # The rejected card is removed from the source of truth before the actions
        # are resolved; the score-5 hash is then absent from the current deck.
        review_cards.write_text(json.dumps(review_rows[0]) + "\n")
        actions["status"] = "resolved"
        actions["score1"][0]["action"] = "keep anchor"
        actions["score1"][0]["target"] = "n/a"
        (review_work / "review_actions.json").write_text(
            json.dumps(actions, indent=2) + "\n")
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(review_cards), "--out", str(review_work),
                 "--gates-only", "--build", "--deck-name", "LOCAL::TEST",
                 "--out-apkg", str(td / "review.apkg")], td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert "review     resolved" in r.stdout, r.stdout
        assert "packet     " in r.stdout, r.stdout
        assert "shape      " in r.stdout and "strata     " in r.stdout, r.stdout
        assert (review_work / "review_packet.md").is_file(), r.stdout
        # New feedback after the actions were resolved regenerates an open skeleton.
        with (review_work / "review_feedback.jsonl").open("a") as fh:
            fh.write(json.dumps({"n": 1, "hash": card_hash(review_rows[0]),
                                 "score": 3}) + "\n")
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(review_cards), "--out", str(review_work),
                 "--gates-only", "--build", "--deck-name", "LOCAL::TEST",
                 "--out-apkg", str(td / "review-stale.apkg")], td)
        assert r.returncode != 0 and "review_actions.json is open" in r.stderr, (
            r.stdout, r.stderr)
        legacy_work = td / "legacy-review-work"
        legacy_work.mkdir()
        legacy_cards = legacy_work / "cards.jsonl"
        legacy_cards.write_text(json.dumps(review_rows[0]) + "\n")
        for name in ("intake.md", "scope_gate.md", "authoring_ledger.md"):
            (legacy_work / name).write_text("evidence\n")
        (legacy_work / "review_feedback.jsonl").write_text(json.dumps(
            {"n": 1, "hash": card_hash(review_rows[0]), "score": 1,
             "comment": "Known material."}) + "\n")
        (legacy_work / "review_actions.md").write_text(
            "# Review actions\nstatus: resolved\n\n"
            "## Score 1 — rescope, do not auto-cut\n\n"
            "- [ ] Point Defects / concept / thermo.steady_flow — cards 1\n"
            "  action: keep anchor\n  target: n/a\n")
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(legacy_cards), "--out", str(legacy_work),
                 "--gates-only", "--build", "--deck-name", "LEGACY::TEST",
                 "--out-apkg", str(td / "legacy-review.apkg")], td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert "review     resolved" in r.stdout, r.stdout
        print("ok    legacy review_actions.md still builds")
        packet_dir = td / "packet-test"
        packet_dir.mkdir()
        packet = pipeline.write_review_packet(
            packet_dir, review_rows, {"entries": [{"i": 1, "reasons": ["test"]}]}, None)
        packet_text = packet.read_text()
        assert review_rows[0]["front"] in packet_text, packet_text
        assert review_rows[1]["front"] not in packet_text, packet_text
        assert "sources.md" not in packet_text, packet_text
        print("ok    review feedback creates actions, packet, and shape line")

        mixed = td / "mixed"
        mixed.mkdir()
        (mixed / "notes.txt").write_text("A mixed directory keeps its document.\n")
        (mixed / "clip.mp4").write_bytes(b"not a real video")
        media_sources, doc_sources = pipeline._split_sources([str(mixed)])
        assert any(p.endswith("clip.mp4") for p in media_sources), media_sources
        assert any(p.endswith("notes.txt") for p in doc_sources), doc_sources
        print("ok    mixed directory splits media and documents")

        kc_work = td / "kc-work"
        kc_work.mkdir()
        kc_cards = td / "kc-cards.jsonl"
        kc_rows = [
            {"front": "What is a control volume?",
             "back": "A fixed region. **Why:** mass flows through it.",
             "layer": "L2", "topic": "Control Volumes", "deck": "LOCAL::TEST",
             "source": "Lec 1 p.1", "kc": "thermo.control_volume",
             "stratum": "concept"},
            {"front": "Which equation applies to a steady-flow device?",
             "back": "The steady-flow energy equation. **Why:** energy balances.",
             "layer": "Procedure", "topic": "Turbines", "deck": "LOCAL::TEST",
             "source": "Lec 1 p.2", "kc": "thermo.steady_flow",
             "stratum": "procedure"},
            {"front": "Why does steady flow need a control volume?",
             "back": "It balances mass and energy across a fixed region. **Why:** the boundary is the bookkeeping device.",
             "layer": "L2", "topic": "Turbines", "deck": "LOCAL::TEST",
             "source": "Lec 1 p.2", "kc": "thermo.steady_flow",
             "stratum": "mechanism"},
        ]
        kc_cards.write_text("".join(json.dumps(x) + "\n" for x in kc_rows))
        (kc_work / "kcs.md").write_text("""# KCs — Test

| kc | type | claim | why | requires | evidence_quote | source |
|---|---|---|---|---|---|---|
| thermo.control_volume | concept | A control volume is fixed. | Reused by every balance | — | A control volume is fixed. | Lec 1 p.1 |
| thermo.steady_flow | procedure | Apply the steady-flow equation. | One-card method choice | thermo.control_volume | Apply the steady-flow equation. | Lec 1 p.2 |
""")
        (kc_work / "sources.md").write_text(
            "A control volume is fixed. Apply the steady-flow equation.\n")
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(kc_cards), "--out", str(kc_work),
                 "--gates-only"], td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert "kc         3/3 card(s) linked to 2 KC(s)" in r.stdout, r.stdout
        assert (kc_work / "review_packet.md").is_file(), r.stdout
        print("ok    pipeline gates link cards to the KC map and source quotes")
        ceiling_work = td / "ceiling-work"
        ceiling_work.mkdir()
        (ceiling_work / "scope_gate.md").write_text("Ceiling: 2\n")
        (ceiling_work / "kcs.md").write_text((kc_work / "kcs.md").read_text())
        (ceiling_work / "sources.md").write_text((kc_work / "sources.md").read_text())
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(kc_cards), "--out", str(ceiling_work),
                 "--gates-only"], td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert "above its own Ceiling 2" in r.stdout, r.stdout
        assert any("Ceiling 2" in w for w in json.loads(
            (ceiling_work / "gates.json").read_text())["warnings"]), r.stdout
        print("ok    scope-gate ceiling warns without auto-cutting")
        intake_scope_work = td / "intake-scope-work"
        intake_scope_work.mkdir()
        (intake_scope_work / "intake.md").write_text(
            "# Intake\n\n## Scope\n\n- Ceiling: 2\n")
        (intake_scope_work / "kcs.md").write_text((kc_work / "kcs.md").read_text())
        (intake_scope_work / "sources.md").write_text(
            (kc_work / "sources.md").read_text())
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(kc_cards), "--out", str(intake_scope_work),
                 "--gates-only"], td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert "above its own Ceiling 2" in r.stdout, r.stdout
        assert (intake_scope_work / "review_packet.md").is_file(), r.stdout
        print("ok    intake scope section replaces scope_gate.md")

        image_work = td / "image-work"
        image_work.mkdir()
        (image_work / "intake.md").write_text(
            "# Intake\n\n- images: no\n\n## Scope\n\nCeiling: 3\n")
        (image_work / "kcs.md").write_text((kc_work / "kcs.md").read_text())
        (image_work / "sources.md").write_text((kc_work / "sources.md").read_text())
        (image_work / "figures").mkdir()
        (image_work / "figures" / "figures.json").write_text(json.dumps(
            [{"file": "media/a.png"}, {"file": "media/b.png"}]) + "\n")
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(kc_cards), "--out", str(image_work),
                 "--gates-only"], td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert "2 figure(s) extracted but intake says images: no" in r.stdout, r.stdout
        assert any("2 figure(s) extracted" in w for w in json.loads(
            (image_work / "gates.json").read_text())["warnings"]), r.stdout
        print("ok    images: no with extracted figures warns without blocking")

        bad_kc_work = td / "bad-kc-work"
        bad_kc_work.mkdir()
        (bad_kc_work / "kcs.md").write_text("# KCs\n\nNo table here.\n")
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(kc_cards), "--out", str(bad_kc_work),
                 "--gates-only"], td)
        assert r.returncode != 0 and "no parsable KC table" in r.stdout, (
            r.stdout, r.stderr)
        print("ok    unparsable kcs.md blocks the gates")
        no_why_work = td / "no-why-work"
        no_why_work.mkdir()
        (no_why_work / "kcs.md").write_text("""# KCs — Test

| kc | claim | evidence_quote | source |
|---|---|---|---|
| thermo.control_volume | A control volume is fixed. | A control volume is fixed. | Lec 1 p.1 |
""")
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(kc_cards), "--out", str(no_why_work),
                 "--gates-only"], td)
        assert r.returncode != 0 and "missing the `why` column" in r.stdout, (
            r.stdout, r.stderr)
        print("ok    kcs.md without a why column blocks the gates")

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
            "front": "Calculate the current when V = 12 V and R = 3 ohm.",
            "back": "4 A.", "layer": "L1",
            "topic": "Ohm's Law", "objects": [], "deck": "LOCAL::TEST",
            "source": "local recording @ 00:00",
        }) + "\n")
        r = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                 "--cards", str(bad), "--out", str(work / "bad"),
                 "--gates-only", "--build", "--deck-name", "LOCAL::TEST",
                 "--out-apkg", str(td / "bad.apkg")], td)
        assert r.returncode != 0 and not (td / "bad.apkg").exists(), (r.stdout, r.stderr)
        print("ok    pipeline refuses build on alignment error")

        fig_state = td / "fig-state"
        fig_state.mkdir()
        (fig_state / "pipeline_state.json").write_text(json.dumps({"figures": 3}))
        assert pipeline._extracted_figures(fig_state) == 3, "figure state key drifted"
        print("ok    figure count reads the state key the extractor writes")

        base = [{"front": "a", "back": "b", "topic": "T"}]
        base_sig = pipeline._cards_signature(base)
        one_change = pipeline._cards_signature([{"front": "a", "back": "c", "topic": "T"}])
        two_changes = pipeline._cards_signature([
            {"front": "a", "back": "c", "topic": "T"},
            {"front": "d", "back": "e", "topic": "T"}])
        media_change = pipeline._cards_signature([
            {"front": "a", "back": "b", "topic": "T",
             "media": [{"file": "media/x.png"}]}])
        assert base_sig != media_change, "media-only edit did not change signature"
        assert pipeline._loop_state(None, base_sig, 0, True) == (1, "")
        assert pipeline._loop_state(base_sig, base_sig, 1, True)[0] == 2
        assert "no card changed" in pipeline._loop_state(base_sig, base_sig, 1, True)[1]
        assert "only 1 card changed" in pipeline._loop_state(base_sig, one_change, 1, True)[1]
        assert pipeline._loop_state(base_sig, two_changes, 1, True) == (0, "")
        assert pipeline._loop_state(base_sig, base_sig, 1, False) == (0, "")
        print("ok    loop guard detects small-change repeats and resets")

        loop_work = td / "loop-work"
        loop_work.mkdir()
        loop_bad = td / "loop-bad.jsonl"
        loop_bad.write_text(json.dumps({
            "front": "Calculate the current when V = 12 V and R = 3 ohm.",
            "back": "4 A.", "layer": "L1", "topic": "Ohm's Law",
            "source": "notes p.1"}) + "\n")
        first = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                     "--cards", str(loop_bad), "--out", str(loop_work),
                     "--gates-only"], td)
        second = run([sys.executable, str(SCRIPTS / "pipeline.py"),
                      "--cards", str(loop_bad), "--out", str(loop_work),
                      "--gates-only"], td)
        assert "loop       " not in first.stdout, first.stdout
        assert "loop       no card changed" in second.stdout, second.stdout
        print("ok    pipeline prints the loop warning on an unchanged repeat")

        target = td / "atomic.apkg"
        def fake_run(cmd, *args, **kwargs):
            if any(str(x).endswith("build_apkg.py") for x in cmd):
                Path(cmd[3]).write_bytes(b"not a package")
                return subprocess.CompletedProcess(cmd, 0, "Built 1 note", "")
            return subprocess.CompletedProcess(cmd, 1, "", "validation failed")
        with mock.patch("pipeline.subprocess.run", side_effect=fake_run):
            result = pipeline.stage_build(
                Path("cards.jsonl"), td, "DECK", target, False, None)
        assert result["ok"] is False, result
        assert not target.exists(), "failed validation published an .apkg"
        assert not list(td.glob(".atomic.apkg.tmp-*")), "temp build left behind"
        print("ok    failed validation leaves no .apkg or temp file")

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
