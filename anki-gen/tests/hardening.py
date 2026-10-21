#!/usr/bin/env python3
"""Hardening checks: negative fixtures, golden deck, and sabotage probes.

Run by scripts/smoke.sh. Everything is local and temporary; no model calls.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
GOLDEN = ROOT / "tests" / "golden_cards.jsonl"

BASE = {
    "front": "Why does a vacancy increase a crystal's free energy?",
    "back": "**Why:** forming a vacancy costs energy $Q_v$, but configurational "
            "entropy lowers the free energy at finite temperature.",
    "layer": "L2", "topic": "Point Defects", "objects": ["vacancy"],
    "deck": "GOLDEN::TEST", "source": "Lec 04 p.12", "tier_zero": True,
}


def run(cmd, env=None):
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def validate(cards, scripts=SCRIPTS):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "cards.json"
        p.write_text(json.dumps(cards))
        r = run([sys.executable, str(scripts / "validate_cards.py"), str(p), "--json"])
        try:
            return json.loads(r.stdout), r
        except json.JSONDecodeError as e:
            raise AssertionError(f"validator did not emit JSON: {r.stdout}\n{r.stderr}") from e


def case(name, factory, kind, needle):
    cards = factory()
    data, _ = validate(cards)
    text = "\n".join(data.get("errors", []) + data.get("warnings", []))
    if kind == "error":
        assert data["valid"] is False, f"{name}: expected invalid, got valid"
        assert needle.lower() in text.lower(), f"{name}: missing {needle!r} in {text}"
    else:
        assert data["valid"] is True, f"{name}: expected valid warnings, got errors: {data.get('errors')}"
        assert needle.lower() in text.lower(), f"{name}: missing {needle!r} in {text}"
    print(f"ok    negative: {name}")


def mutate(src: Path, dst: Path, replacements: list[tuple[str, str]]) -> Path:
    target = dst if dst.suffix else dst / src.name
    target.parent.mkdir(parents=True, exist_ok=True)
    text = src.read_text()
    for old, new in replacements:
        if old not in text:
            raise AssertionError(f"mutation target not found in {src.name}: {old[:80]!r}")
        text = text.replace(old, new, 1)
    target.write_text(text)
    return target


def copy_scripts(dst: Path) -> Path:
    shutil.copytree(SCRIPTS, dst, ignore=shutil.ignore_patterns("__pycache__"))
    return dst


def load_golden():
    return [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]


def main() -> int:
    # A known-good card must pass.
    good, _ = validate([BASE])
    assert good["valid"] is True, good
    print("ok    positive control")

    # Negative fixtures: one defect per high-value rule.
    case("missing source", lambda: [{k: v for k, v in BASE.items() if k != "source"}],
         "error", "no source")
    case("source without locator", lambda: [dict(BASE, source="Lecture")],
         "warning", "no locator")
    case("topic is layer code", lambda: [dict(BASE, topic="L2")],
         "error", "topic is the layer")
    case("objects string", lambda: [dict(BASE, objects="vacancy")],
         "error", "objects")
    case("too many objects", lambda: [dict(BASE, objects=["a", "b", "c"])],
         "warning", "object tags")
    case("bad layer", lambda: [dict(BASE, layer="L9")],
         "error", "bad layer")
    case("empty back", lambda: [dict(BASE, back="")],
         "error", "missing/empty 'back'")
    case("computed front", lambda: [dict(BASE, front="Calculate the runtime of nested loops.")],
         "error", "computation prompt")
    case("unmatched bold", lambda: [dict(BASE, front="**An unclosed bold concept with enough length")],
         "error", "unmatched **")
    case("unbalanced inline math", lambda: [dict(BASE, front="What is $x?")],
         "error", "stray $")
    case("control character", lambda: [dict(BASE, back="bad \x0cText")],
         "error", "control char")
    case("cloze syntax without flag", lambda: [dict(BASE, front="The cell has {{c1::2}} atoms.")],
         "error", "cloze")
    case("bad media side", lambda: [dict(BASE, media=[{"file": "media/x.png", "side": "left"}])],
         "error", "media side")
    case("media path escape", lambda: [dict(BASE, media=[{"file": "../x.png", "side": "back"}])],
         "error", "path escapes")
    case("bad source URL scheme", lambda: [dict(BASE, source_url="javascript:alert(1)")],
         "error", "source_url")
    case("YouTube URL without timestamp", lambda: [dict(BASE, source_url="https://youtu.be/x")],
         "warning", "no t=")
    case("artificial one-card topics", lambda: [
        dict(BASE, topic=f"Subtopic {i}", objects=[],
             front=f"Why is subtopic number {i} distinct enough for its own topic?")
        for i in range(1, 9)], "warning", "topics")
    case("near-duplicate fronts", lambda: [BASE, BASE],
         "warning", "similar")

    # Golden deck: quality counters must not silently drop.
    golden = load_golden()
    data, _ = validate(golden)
    assert data["valid"] is True, data
    why = sum(1 for c in golden if re.search(r"\*\*Why:\*\*", c["back"]))
    sources = sum(1 for c in golden if re.search(r"\d", c["source"]))
    tier = sum(1 for c in golden if c.get("tier_zero"))
    gloss = sum(1 for c in golden if re.search(r"\*\*Glossary", c["back"]))
    assert (why, sources, tier, gloss) == (5, 5, 1, 1), (why, sources, tier, gloss)
    print("ok    golden quality counters")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        good_apkg = td / "golden.apkg"
        r = run([sys.executable, str(SCRIPTS / "build_apkg.py"), str(GOLDEN),
                 str(good_apkg), "--deck-name", "GOLDEN::TEST", "--strict"])
        assert r.returncode == 0, r.stderr
        r = run([sys.executable, str(SCRIPTS / "validate_apkg.py"), str(good_apkg)])
        assert r.returncode == 0, r.stderr
        assert "5 notes" in r.stdout, r.stdout
        print("ok    golden build/import")

        # Sabotage 1: disable the source check; the missing-source fixture should now pass.
        mut = copy_scripts(td / "mut-source")
        mutate(mut / "validate_cards.py", mut / "validate_cards.py",
               [("if not src:", "if False:")])
        data, _ = validate([{k: v for k, v in BASE.items() if k != "source"}], mut)
        assert data["valid"] is True and not any("no source" in e for e in data["errors"]), data
        print("ok    sabotage detected: source check")

        # Sabotage 2: disable the computation check.
        mut = copy_scripts(td / "mut-compute")
        mutate(mut / "validate_cards.py", mut / "validate_cards.py",
               [("why = is_computation_prompt(front)", "why = None")])
        data, _ = validate([dict(BASE, front="Calculate the runtime of nested loops.")], mut)
        assert data["valid"] is True and not any("computation" in e for e in data["errors"]), data
        print("ok    sabotage detected: computation check")

        # Sabotage 3: break math rendering; a render expectation must notice.
        mut = copy_scripts(td / "mut-render")
        mutate(mut / "render.py", mut / "render.py",
               [("tmpl, found = _extract_math(text)", "tmpl, found = text, []")])
        r = run([sys.executable, "-c",
                 "import sys; sys.path.insert(0, sys.argv[1]); import render; "
                 "print(render.to_html('$x$'))", str(mut)])
        assert r.returncode == 0, r.stderr
        assert r"\(" not in r.stdout and "$x$" in r.stdout, r.stdout
        print("ok    sabotage detected: math renderer")

        # Sabotage 4: drop source footers in the native builder.
        mut = copy_scripts(td / "mut-build")
        mutate(mut / "build_native.py", mut / "build_native.py",
               [('src = str(c.get("source") or c.get("source_ref") or "")', 'src = ""')])
        bad_apkg = td / "bad.apkg"
        r = run([sys.executable, str(mut / "build_apkg.py"), str(GOLDEN),
                 str(bad_apkg), "--deck-name", "GOLDEN::TEST", "--strict"])
        assert r.returncode == 0, r.stderr
        with tempfile.TemporaryDirectory() as extract:
            with zipfile.ZipFile(bad_apkg) as z:
                z.extract("collection.anki2", extract)
            con = sqlite3.connect(Path(extract) / "collection.anki2")
            try:
                flds = [row[0] for row in con.execute("select flds from notes")]
            finally:
                con.close()
        assert not any("Lec 04 p.12" in f for f in flds), flds
        print("ok    sabotage detected: source footer")

    print("\nPASS  hardening checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
