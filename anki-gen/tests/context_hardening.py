#!/usr/bin/env python3
"""Deck dossier checks: pack, schema, previews, validation, export/import."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import deck_context as dc  # noqa: E402
from cardid import card_hash  # noqa: E402

try:
    from PIL import Image, ImageDraw
    HAVE_PIL = True
except ImportError:                       # pragma: no cover - image-less machines
    HAVE_PIL = False


def make_image(path: Path, size=(1200, 800), color=(255, 255, 255)):
    path.parent.mkdir(parents=True, exist_ok=True)
    if HAVE_PIL:
        im = Image.new("RGB", size, color)
        draw = ImageDraw.Draw(im)
        for i in range(6):
            draw.rectangle((40 + i * 30, 40 + i * 20, 300 + i * 30, 260 + i * 20),
                           outline=(20, 20, 20))
        im.save(path)
    else:
        path.write_bytes(b"\x89PNG\r\n\x1a\n")


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        os.environ["ANKI_GEN_DATA_HOME"] = str(td / "data")
        work = td / "work"
        work.mkdir()
        (work / "intake.md").write_text("# Intake\n\nLearner: second year.\n")
        (work / "scope_gate.md").write_text("# Scope\n\nFormula sheet given.\n")
        (work / "authoring_ledger.md").write_text(
            "# Ledger\n\n1. heap_4 vs heap_2 — why — Lec 4 p.2\n")
        cards = [
            {"front": "Why does heap_4 bound fragmentation?",
             "back": "It keeps one free list per size class. **Why:** allocation is constant time.",
             "layer": "L2", "topic": "Memory", "objects": ["rtos"],
             "deck": "RTOS", "source": "Lec 4 p.2", "tier_zero": True,
             "media": [{"file": "media/used.png", "side": "back", "caption": "used"}]},
            {"front": "What does heap_2 trade away?",
             "back": "Exact-fit reuse. **Why:** fixed classes waste a little space.",
             "layer": "L1", "topic": "Memory", "objects": [], "deck": "RTOS",
             "source": "Lec 4 p.3"},
            {"front": "Which scheduler state is runnable?",
             "back": "Ready. **Why:** it can run but is not executing.",
             "layer": "L1", "topic": "Scheduling", "objects": [], "deck": "RTOS",
             "source": "Lec 5 p.1"},
        ]
        (work / "cards.jsonl").write_text(
            "".join(json.dumps(c) + "\n" for c in cards))
        make_image(work / "media" / "used.png")
        make_image(work / "media" / "fig_labels.png")
        make_image(work / "media" / "fig_plain.png", color=(230, 240, 250))
        make_image(work / "media" / "frame.png", color=(10, 40, 80))
        make_image(work / "media" / "tiny.png", size=(160, 120))
        figures = [
            {"file": "media/fig_labels.png", "page": 7, "kind": "diagram",
             "quality": "high", "sha256": "a" * 64, "caption": "heap map",
             "source": "Lec 4", "labels": []},
            {"file": "media/fig_plain.png", "page": 8, "kind": "diagram",
             "quality": "medium", "sha256": "b" * 64, "caption": "scheduler",
             "source": "Lec 5", "labels": []},
            {"file": "media/used.png", "page": 2, "kind": "figure",
             "quality": "high", "sha256": "c" * 64, "caption": "used",
             "source": "Lec 4"},
            {"file": "media/tiny.png", "page": 9, "kind": "diagram",
             "quality": "high", "sha256": "d" * 64, "caption": "tiny",
             "source": "Lec 5"},
            {"file": "media/fig_plain.png", "page": 10, "kind": "photo",
             "quality": "low", "sha256": "e" * 64, "caption": "low"},
        ]
        (work / "figures.json").write_text(json.dumps(figures))
        (work / "frames.jsonl").write_text(json.dumps({
            "file": "media/frame.png", "best": True, "attach": "direct",
            "quality": "high", "timecode": "00:12", "caption": "state machine",
            "source": "RTOS 04 @ 00:12", "source_url": "https://example/04?t=12",
            "reason": "strong visual"}) + "\n")
        (work / "vision.jsonl").write_text(json.dumps({
            "file": "media/fig_labels.png",
            "result": {"kind": "diagram", "shows": "heap layout",
                       "labels": [f"L{i}" for i in range(9)]}}) + "\n")
        (work / "videos.jsonl").write_text(json.dumps({
            "id": "v1", "title": "RTOS 04", "source_type": "youtube",
            "source_url": "https://example/04", "source_label": "RTOS 04",
            "transcript_source": "captions"}) + "\n")
        (work / "manifest.json").write_text(json.dumps({
            "generated_at": "2026-10-22T00:00:00", "sources": [
                {"tag": "lec4", "source_type": "pdf", "source_path": "Lec 4.pdf",
                 "md": "lec4/lec4.md"}]}))
        (work / "transcripts.md").write_text("FULL TRANSCRIPT SHOULD NOT SHIP\n")
        (work / "review_feedback.jsonl").write_text(
            json.dumps({"hash": card_hash(cards[0]), "score": 5}) + "\n"
            + json.dumps({"hash": card_hash(cards[0]), "score": 1}) + "\n")

        curated = {
            "topics": {"Memory": {"takeaways": ["Classes bound fragmentation."],
                                  "gaps": ["heap_1..5 comparison"]}},
            "style": "# Style\n\n- course says heap_4, not heap4\n",
            "learner": "# Learner\n\n- prefers diagrams on the back\n",
            "preferences": {"images": "yes"},
            "notation": {"heap": "heap_N"},
            "decisions": "# Decisions\n\n- keep heap_4 as canonical\n",
            "future_work": "# Future work\n\n- revisit heap_2\n",
        }
        (work / "curated.json").write_text(json.dumps(curated))

        result = dc.pack(work, {"deck_name": "SCHOOL::RTOS", "profile": "User 1"})
        dossier = Path(result["path"])
        key = result["key"]
        for name in ("manifest.json", "deck_context.md", "topics.jsonl",
                     "style.md", "notation.json", "learner.md",
                     "preferences.json", "decisions.md", "future_work.md",
                     "cards.jsonl", "authoring_ledger.md", "scope_gate.md",
                     "intake.md", "sources.jsonl", "source_excerpts.jsonl",
                     "media_candidates.jsonl", "thumbnails"):
            assert (dossier / name).exists(), name
        print("ok    dossier layout")

        rows = [json.loads(x) for x in (dossier / "cards.jsonl").read_text().splitlines()]
        assert len(rows) == 3, rows
        assert len({r["rev_id"] for r in rows}) == 3
        assert all(r["guid"] == card_hash({"front": r["front"], "back": r["back"]})
                   for r in rows)
        assert rows[0]["why"] and rows[0]["source"]
        assert rows[0]["anki_note_id"] is None
        assert rows[0]["review_score"] == 1, rows[0]
        assert "FULL TRANSCRIPT" not in (dossier / "cards.jsonl").read_text()
        assert not (dossier / "transcripts.md").exists()
        assert not (dossier / "media").exists()
        assert not any(p.suffix.lower() in (".mp4", ".pdf") for p in dossier.rglob("*"))
        print("ok    compact card rows and no full media/source")

        topics = [json.loads(x) for x in (dossier / "topics.jsonl").read_text().splitlines()]
        memory = next(t for t in topics if t["topic"] == "Memory")
        assert memory["actual_cards"] == 2 and memory["takeaways"] == [
            "Classes bound fragmentation."], memory
        assert memory["gaps"] == ["heap_1..5 comparison"], memory
        assert any("heap_4" in a for a in memory["anchors"]), memory
        assert "Classes bound fragmentation." in (dossier / "deck_context.md").read_text()
        assert "course says heap_4" in (dossier / "style.md").read_text()
        print("ok    curated topic/style/preferences preserved")

        sources = [json.loads(x) for x in (dossier / "sources.jsonl").read_text().splitlines()]
        assert any("RTOS 04" in (s.get("title") or "") for s in sources), sources
        assert any(s.get("type") == "pdf" for s in sources), sources
        print("ok    source anchors derived from artifacts")

        media = [json.loads(x) for x in
                 (dossier / "media_candidates.jsonl").read_text().splitlines()]
        assert len(media) == 5, media   # high/medium only; low quality dropped
        used = next(m for m in media if m["file"].endswith("used.png"))
        assert used["used"] is True and not used["preview"], used
        unused = [m for m in media if not m["used"]]
        assert len(unused) == 4, media
        assert all(m["preview"] for m in unused), unused
        assert all((dossier / m["preview"]).is_file() for m in unused)
        label_prev = next(m for m in media if m["file"].endswith("fig_labels.png"))
        assert label_prev["preview_meta"]["target"] == 1024, label_prev
        tiny_prev = next(m for m in media if m["file"].endswith("tiny.png"))
        assert tiny_prev["preview_meta"]["low_res"] is True, tiny_prev
        print("ok    adaptive previews for unused high/medium media")

        assert dc.preview_long_edge("diagram", contact_sheet=True) == 320
        assert dc.preview_long_edge("diagram", ["a", "b", "c"]) == 768
        assert dc.preview_long_edge("photo") == 640
        print("ok    preview size policy")

        check = dc.validate(deck_key_or_selector=key)
        assert not check["errors"], check
        print("ok    dossier validates")

        first_ids = {r["content_hash"]: r["rev_id"] for r in rows}
        result2 = dc.pack(work, {"deck_name": "SCHOOL::RTOS", "profile": "User 1"})
        assert result2["key"] == key
        rows2 = [json.loads(x) for x in (dossier / "cards.jsonl").read_text().splitlines()]
        for row in rows2:
            assert first_ids[row["content_hash"]] == row["rev_id"]
        (dossier / "style.md").write_text("# Style\n\n- manually curated later\n")
        dc.pack(work, {"deck_name": "SCHOOL::RTOS", "profile": "User 1"})
        assert "manually curated later" in (dossier / "style.md").read_text()
        print("ok    repack keeps rev_id and curated edits")

        archive = td / "deck.zip"
        dc.export(key, archive)
        with zipfile.ZipFile(archive) as z:
            assert "_export.json" in z.namelist()
            meta = json.loads(z.read("_export.json"))
            assert meta["deck_key"] == key and meta["checksum"]
        shutil.rmtree(dossier)
        imported = dc.import_archive(archive, attach=False)
        assert imported["key"] == key, imported
        rows3 = [json.loads(x) for x in (Path(imported["path"]) / "cards.jsonl").read_text().splitlines()]
        assert len(rows3) == 3 and rows3[0]["rev_id"] == rows[0]["rev_id"]
        print("ok    export/import roundtrip")

        bad = dict(rows[0], source="")
        check = dc.validate({"manifest": {"schema": 1}, "cards": [bad], "topics": [],
                             "media_candidates": [], "learner": "x"})
        assert any("missing source" in e for e in check["errors"]), check
        assert any("why" in w for w in check["warnings"]), check
        print("ok    validation catches lost source and context gaps")

        # No hard cap: every indexed high/medium candidate survives packing.
        many = td / "many"
        many.mkdir()
        (many / "cards.jsonl").write_text((work / "cards.jsonl").read_text())
        for name in ("intake.md", "scope_gate.md", "authoring_ledger.md"):
            (many / name).write_text((work / name).read_text())
        figs = []
        for i in range(12):
            make_image(many / "media" / f"m{i}.png", size=(700, 500))
            figs.append({"file": f"media/m{i}.png", "page": i + 1,
                         "kind": "diagram", "quality": "medium",
                         "sha256": f"{i:064d}", "caption": f"diagram {i}",
                         "source": "Lec 6"})
        (many / "figures.json").write_text(json.dumps(figs))
        res = dc.pack(many, {"deck_name": "NO::CAP", "profile": "User 1"})
        media_many = [json.loads(x) for x in
                      (Path(res["path"]) / "media_candidates.jsonl").read_text().splitlines()]
        assert len(media_many) == 12, len(media_many)
        if HAVE_PIL:
            assert all(m["preview"] for m in media_many), media_many
        print("ok    no hard cap on high/medium media candidates")

    print("\nPASS  context hardening")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
