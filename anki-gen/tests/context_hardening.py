#!/usr/bin/env python3
"""Deck dossier checks: pack, schema, previews, validation, export/import."""
from __future__ import annotations

import contextlib
import io
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
import revision  # noqa: E402
from cardid import card_hash  # noqa: E402
from dossier.errors import ArchiveError, SchemaTooNew  # noqa: E402

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
                     "cards.jsonl", "anki_state.jsonl", "sources.jsonl",
                     "source_excerpts.jsonl", "media_candidates.jsonl",
                     "thumbnails", "evidence/intake.md",
                     "evidence/scope_gate.md", "evidence/authoring_ledger.md"):
            assert (dossier / name).exists(), name
        manifest = json.loads((dossier / "manifest.json").read_text())
        assert manifest["format"] == "anki-gen.deck-dossier"
        assert manifest["schema"] == 1 and manifest["deck"]["uuid"] == key
        assert "cards.jsonl" in manifest["files"]
        assert manifest["files"]["cards.jsonl"]["role"] == "cards"
        print("ok    dossier layout")

        rows = [json.loads(x) for x in (dossier / "cards.jsonl").read_text().splitlines()]
        states = [json.loads(x) for x in (dossier / "anki_state.jsonl").read_text().splitlines()]
        assert len(rows) == 3 and len(states) == 3, rows
        assert len({r["rev_id"] for r in rows}) == 3
        assert all(r["guid"] == card_hash({"front": r["front"], "back": r["back"]})
                   for r in rows)
        assert rows[0]["why"] and rows[0]["source"]
        assert rows[0]["review_score"] == 1, rows[0]
        assert states[0]["anki_note_id"] is None and states[0]["state"] == "live"
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
            assert meta["deck_uuid"] == key and meta["files"]
            assert all(e.get("sha256") for e in meta["files"])
        shutil.rmtree(dossier)
        imported = dc.import_archive(archive)
        assert imported["key"] == key, imported
        rows3 = [json.loads(x) for x in (Path(imported["path"]) / "cards.jsonl").read_text().splitlines()]
        assert len(rows3) == 3 and rows3[0]["rev_id"] == rows[0]["rev_id"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert revision.main(["context", "import", str(archive), "--dry-run"]) == 0
        assert "dry run" in buf.getvalue(), buf.getvalue()
        print("ok    export/import roundtrip and dry-run CLI")

        bad = dict(rows[0], source="", why="", retrieval_target="")
        check = dc.validate({"manifest": {"schema": 1}, "cards": [bad], "topics": [],
                             "state": [], "media_candidates": [], "learner": "x",
                             "path": str(dossier), "sources": []})
        assert any("missing source" in e["message"] for e in check["errors"]), check
        assert any("why" in w["message"] for w in check["warnings"]), check
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

        # Unknown fields survive a repack; the schema is additive.
        states = [json.loads(x) for x in
                  (dossier / "anki_state.jsonl").read_text().splitlines()]
        cards_now = [json.loads(x) for x in
                     (dossier / "cards.jsonl").read_text().splitlines()]
        cards_now[0].setdefault("extra", {})["x_future"] = {"keep": True}
        dc.update_cards(key, cards_now, states)
        dc.pack(work, {"deck_name": "SCHOOL::RTOS", "profile": "User 1"})
        rows4 = [json.loads(x) for x in (dossier / "cards.jsonl").read_text().splitlines()]
        assert rows4[0]["extra"]["x_future"] == {"keep": True}, rows4[0]
        print("ok    unknown fields preserved")

        # The index is a cache and rebuilds from manifests.
        index = Path(dc.data_root()) / "decks" / "index.json"
        index.unlink()
        assert dc.resolve(key) == key
        assert index.is_file()
        print("ok    index rebuilds from manifests")

        # Checksum verification is explicit and catches tamper.
        cards_file = dossier / "cards.jsonl"
        original_cards = cards_file.read_text()
        cards_file.write_text(original_cards + json.dumps({"rev_id": "tamper"}) + "\n")
        assert dc.file_problems(key), "tampered file was not reported"
        cards_file.write_text(original_cards)
        print("ok    file checksum verification detects tamper")

        # Newer schemas are refused instead of rewritten.
        manifest_file = dossier / "manifest.json"
        original_manifest = manifest_file.read_text()
        future = json.loads(original_manifest)
        future["schema"] = 99
        manifest_file.write_text(json.dumps(future))
        try:
            dc.load(key)
        except SchemaTooNew:
            pass
        else:
            raise AssertionError("future schema was accepted")
        manifest_file.write_text(original_manifest)
        print("ok    newer schema is read-only/refused")

        # Unsafe archives and checksum tampering are rejected.
        bad = td / "bad.zip"
        with zipfile.ZipFile(archive) as src, zipfile.ZipFile(bad, "w") as dst:
            for name in src.namelist():
                data = src.read(name)
                if name == "cards.jsonl":
                    data += b" "
                dst.writestr(name, data)
        try:
            dc.import_archive(bad)
        except ArchiveError:
            pass
        else:
            raise AssertionError("tampered archive was accepted")
        with zipfile.ZipFile(archive) as src:
            meta = json.loads(src.read("_export.json"))
        evil = td / "evil.zip"
        with zipfile.ZipFile(evil, "w") as z:
            z.writestr("_export.json", json.dumps(meta))
            z.writestr("../escape.txt", "nope")
        try:
            dc.import_archive(evil)
        except ArchiveError:
            pass
        else:
            raise AssertionError("unsafe archive path was accepted")
        print("ok    archive path/checksum hardening")

        # Generic resources: any file type, open kind/role, future metadata.
        blob = td / "future-resource.bin"
        blob.write_bytes(b"\x00\x01future-resource\xff")
        row = dc.add_resource(key, blob, kind="dataset", role="reference",
                              name="future-resource.bin",
                              metadata={"unknown_future_field": {"x": 1}})
        assert row["path"].startswith("resources/")
        assert (dossier / row["path"]).read_bytes() == blob.read_bytes()
        loaded = dc.load(key)
        assert any(r["resource_id"] == row["resource_id"] for r in loaded["resources"])
        assert loaded["manifest"]["counts"]["resources"] == 1
        assert not dc.validate(deck_key_or_selector=key)["errors"]
        archive2 = td / "with-resource.zip"
        dc.export(key, archive2)
        with zipfile.ZipFile(archive2) as z:
            assert row["path"] in z.namelist()
        (dossier / row["path"]).write_bytes(b"tampered")
        assert any("checksum mismatch" in e["message"]
                   for e in dc.validate(deck_key_or_selector=key)["errors"])
        print("ok    generic resources are extensible and validated")

        # Future manifest metadata is preserved in extensions.
        manifest = json.loads((dossier / "manifest.json").read_text())
        manifest.setdefault("extensions", {})["x-future"] = {"ok": True}
        (dossier / "manifest.json").write_text(json.dumps(manifest))
        dc.pack(work, {"deck_name": "SCHOOL::RTOS", "profile": "User 1"})
        assert json.loads((dossier / "manifest.json").read_text()
                          )["extensions"]["x-future"] == {"ok": True}
        print("ok    manifest extensions are preserved")

    print("\nPASS  context hardening")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
