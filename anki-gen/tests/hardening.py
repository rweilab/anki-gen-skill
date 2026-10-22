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

sys.path.insert(0, str(SCRIPTS))
from build_apkg import normalize_objects, study_order  # noqa: E402
from validate_cards import similar_answer_pairs  # noqa: E402
from new_cards import C, CardError  # noqa: E402

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

    skill = (ROOT / "SKILL.md").read_text()
    for phrase in ("Never use main-model vision",
                   "Never spawn a child `opencode` process",
                   "Do not probe for LibreOffice"):
        assert phrase in skill, f"guardrail missing from SKILL.md: {phrase!r}"
    maintainers = (ROOT / "MAINTAINERS.md").read_text()
    for phrase in ("## Quality contract", "**98%**", "4. speed"):
        assert phrase in maintainers, f"quality contract missing: {phrase!r}"
    assert (maintainers.index("1. correctness")
            < maintainers.index("3. token and API-call efficiency")
            < maintainers.index("4. speed")), "quality priority order changed"
    assert "quality contract in `MAINTAINERS.md`" in (ROOT / "AGENTS.md").read_text()
    print("ok    execution and quality guardrails present")

    # Soft order: source topic first, tier-zero, then L1/L2/advanced. Topic B is
    # first on purpose, so this also proves the order is not alphabetical.
    order_cards = [
        {"front": "B fact one?", "back": "**Why:** b1.", "layer": "L1",
         "topic": "Topic B", "deck": "ORDER::TEST", "source": "Lec 2 p.1"},
        {"front": "A understanding one?", "back": "**Why:** a2.", "layer": "L2",
         "topic": "Topic A", "deck": "ORDER::TEST", "source": "Lec 1 p.2"},
        {"front": "A fact one?", "back": "**Why:** a1.", "layer": "L1",
         "topic": "Topic A", "deck": "ORDER::TEST", "source": "Lec 1 p.1"},
        {"front": "A concept?", "back": "**Why:** a0.", "layer": "L2",
         "topic": "Topic A", "deck": "ORDER::TEST", "source": "Lec 1 p.0",
         "tier_zero": True},
        {"front": "B concept?", "back": "**Why:** b0.", "layer": "L2",
         "topic": "Topic B", "deck": "ORDER::TEST", "source": "Lec 2 p.0",
         "tier_zero": True},
        {"front": "B boundary?", "back": "**Why:** b3.", "layer": "L3",
         "topic": "Topic B", "deck": "ORDER::TEST", "source": "Lec 2 p.3"},
        {"front": "B procedure?", "back": "**Why:** bp.", "layer": "Procedure",
         "topic": "Topic B", "deck": "ORDER::TEST", "source": "Lec 2 p.4"},
    ]
    expected_order = [
        "B concept?", "B fact one?", "B boundary?", "B procedure?",
        "A concept?", "A fact one?", "A understanding one?",
    ]
    got_order = [c["front"] for c in study_order(order_cards)]
    assert got_order == expected_order, got_order
    print("ok    grouped order for a small deck")

    scatter_cards = []
    for topic in ("Alpha", "Beta", "Gamma"):
        for i in range(16):
            scatter_cards.append({
                "front": f"{topic} card {i}?",
                "back": "**Why:** test.",
                "layer": "L1" if i % 2 == 0 else "L2",
                "topic": topic,
                "deck": "SCATTER::TEST",
                "source": "Lec 1 p.1",
                "tier_zero": i == 0,
            })
    scattered = study_order(scatter_cards)
    assert len(scattered) == len(scatter_cards)
    assert scattered == study_order(list(scatter_cards))  # deterministic
    anchors = {c["topic"] for c in scatter_cards if c["tier_zero"]}
    seen_anchor = set()
    run_topic, run_len = None, 0
    for c in scattered:
        t = c["topic"]
        if c["tier_zero"]:
            seen_anchor.add(t)
        elif t in anchors:
            assert t in seen_anchor, f"{t} card before its tier-zero anchor"
        run_len = run_len + 1 if t == run_topic else 1
        run_topic = t
        assert run_len <= 4, f"topic run too long: {t} x{run_len}"
    assert {c["topic"] for c in scattered} == set(anchors)
    print("ok    scattered study order")

    tag_cards = [
        {"topic": "Memory Management", "objects": ["heap", "stack"]},
        {"topic": "Memory Management", "objects": ["heap"]},
        {"topic": "Queues", "objects": ["queue"]},
        {"topic": "Queues", "objects": ["queue"]},
        {"topic": "Deadlock & Starvation", "objects": ["deadlock"]},
        {"topic": "Deadlock & Starvation", "objects": ["critical_section", "rtos"]},
        {"topic": "Priority Inversion", "objects": ["critical_section", "rtos"]},
        {"topic": "Priority Inversion", "objects": ["rtos"]},
    ]
    normalized = normalize_objects(tag_cards)
    assert normalized[0]["objects"] == [], normalized[0]
    assert normalized[2]["objects"] == [], normalized[2]
    assert normalized[4]["objects"] == [], normalized[4]
    assert set(normalized[5]["objects"]) == {"critical_section", "rtos"}, normalized[5]
    span_cards = []
    for i in range(12):
        for topic in (f"T{i}", f"T{(i + 1) % 12}"):
            span_cards.append({"topic": topic, "objects": [f"narrow_{i}"]})
        for topic in (f"T{i}", f"T{(i + 3) % 12}", f"T{(i + 7) % 12}"):
            span_cards.append({"topic": topic, "objects": [f"broad_{i}"]})
    kept = {obj for c in normalize_objects(span_cards) for obj in c["objects"]}
    assert not any(o.startswith("narrow_") for o in kept), kept
    assert any(o.startswith("broad_") for o in kept), kept
    topic_words = normalize_objects([
        {"topic": "Interrupts & ISRs", "objects": ["interrupt"]},
        {"topic": "Scheduling", "objects": ["interrupt"]},
        {"topic": "Interrupts & ISRs", "objects": ["interrupt"]},
    ])
    assert all("interrupt" not in c["objects"] for c in topic_words), topic_words
    print("ok    broad tag normalization (topic span/name)")

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
    case("enzyme question missing enzyme", lambda: [dict(
        BASE, topic="Glycolysis", objects=[],
        front="Which enzyme splits fructose-1,6-bisphosphate into DHAP and G3P?",
        back="Fructose-1,6-bisphosphate → DHAP + G3P. **Why:** it splits the six-carbon sugar into two trioses.")],
        "error", "names no enzyme")
    enzyme_ok, _ = validate([dict(
        BASE, topic="Glycolysis", objects=[],
        front="Which enzyme splits fructose-1,6-bisphosphate into DHAP and G3P?",
        back="**Aldolase** cleaves it into DHAP and G3P. **Why:** the six-carbon sugar becomes two trioses.")])
    assert enzyme_ok["valid"] is True, enzyme_ok
    generic_enzyme, _ = validate([dict(
        BASE, topic="Glycolysis", objects=[],
        front="Which enzyme splits fructose-1,6-bisphosphate?",
        back="The enzyme splits it into DHAP and G3P.")])
    assert generic_enzyme["valid"] is False, generic_enzyme
    lysozyme, _ = validate([dict(
        BASE, topic="Immunology", objects=[],
        front="Which enzyme hydrolyses bacterial peptidoglycan?",
        back="**Lysozyme** cleaves the peptidoglycan backbone. **Why:** it breaks the sugar links.")])
    assert lysozyme["valid"] is True, lysozyme
    why_card, _ = validate([dict(
        BASE, topic="Glycolysis", objects=[],
        front="Why does the six-carbon sugar split into two trioses?",
        back="**Why:** the payoff phase needs two three-carbon substrates.")])
    assert why_card["valid"] is True, why_card

    tag_leak = [dict(BASE, topic="First-Order ODEs", objects=["bernoulli"],
                     front="Which substitution turns this into a linear ODE?",
                     back="Use the Bernoulli substitution; it turns the equation linear.")]
    data, _ = validate(tag_leak)
    assert any("appears only in the answer" in e for e in data["errors"]), data
    broad_tags = [
        dict(BASE, topic="Topic A", objects=["odes"], back="Use the ODE method."),
        dict(BASE, topic="Topic B", objects=["odes"], back="Use the ODE method."),
    ]
    data, _ = validate(broad_tags)
    assert not any("appears only in the answer" in w for w in data["errors"]
                   + data["warnings"]), data
    topic_leak = [dict(BASE, topic="Bernoulli", objects=[],
                       front="Which substitution turns this into a linear ODE?",
                       back="Use the Bernoulli substitution; it turns the equation linear.")]
    data, _ = validate(topic_leak)
    assert any("topics" not in w and "appears only in the answer" in w
               for w in data["warnings"]), data
    try:
        C(front="Which enzyme splits fructose-1,6-bisphosphate?",
          back="It splits into DHAP and G3P.", layer="L1", topic="Glycolysis",
          deck="ENZYME::TEST", source="Lec 1 p.1")
    except CardError as e:
        assert "enzyme" in str(e), e
    else:
        raise AssertionError("new_cards.C accepted a missing enzyme answer")
    print("ok    authoring helper rejects missing enzyme answer")

    print("ok    front-visible tag leak warning")

    same_answer = [
        dict(BASE, topic="Scheduling", front="How is the next task chosen?",
             back="The scheduler picks the highest priority ready task and runs it until it blocks."),
        dict(BASE, topic="Scheduling", front="Why is that task chosen?",
             back="The scheduler picks the highest priority ready task and runs it until it blocks."),
    ]
    pairs = similar_answer_pairs(same_answer)
    assert pairs and pairs[0][:2] == (1, 2), pairs
    contrast = [
        dict(BASE, topic="Inversion", front="What is bounded inversion?",
             back="A high-priority task waits for a low-priority lock holder."),
        dict(BASE, topic="Inversion", front="What is unbounded inversion?",
             back="A high-priority task waits for a low-priority lock holder."),
    ]
    assert not similar_answer_pairs(contrast), contrast
    print("ok    answer-aware overlap warning")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        mut = copy_scripts(td / "mut-tag")
        mutate(mut / "validate_cards.py", mut / "validate_cards.py",
               [("tag_findings = tag_leak_findings(cards)", "tag_findings = []")])
        data, _ = validate(tag_leak, mut)
        assert data["valid"] is True and not any(
            "appears only in the answer" in m for m in data["errors"]), data
        print("ok    sabotage detected: tag leak")

        mut = copy_scripts(td / "mut-overlap")
        mutate(mut / "validate_cards.py", mut / "validate_cards.py",
               [("for i, j, r in similar_answer_pairs(cards):",
                 "for i, j, r in []:")])
        data, _ = validate(same_answer, mut)
        assert not any("answers" in w for w in data["warnings"]), data
        print("ok    sabotage detected: answer overlap")

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

        # Integration: the built order actually scatters topics, and the built
        # tags are the broad buckets rather than the source subtopics.
        build_cards = []
        for topic, obj in (("Alpha", "heap"), ("Beta", "queue"), ("Gamma", "critical_section")):
            for i in range(16):
                build_cards.append({
                    "front": f"{topic} card {i}?",
                    "back": "**Why:** integration test.",
                    "layer": "L1" if i % 2 == 0 else "L2",
                    "topic": topic, "objects": [obj, "rtos", "critical_section"],
                    "deck": "SCATTER::TEST", "source": "Lec 1 p.1",
                    "tier_zero": i == 0,
                })
        build_path = td / "scatter.json"
        build_path.write_text(json.dumps(build_cards))
        scatter_apkg = td / "scatter.apkg"
        r = run([sys.executable, str(SCRIPTS / "build_apkg.py"), str(build_path),
                 str(scatter_apkg), "--deck-name", "SCATTER::TEST"])
        assert r.returncode == 0, r.stderr
        with zipfile.ZipFile(scatter_apkg) as z:
            z.extract("collection.anki2", td / "scatter-extract")
        con = sqlite3.connect(td / "scatter-extract" / "collection.anki2")
        try:
            rows = list(con.execute(
                "select n.sfld, n.tags from cards c join notes n on n.id=c.nid "
                "order by c.due"))
        finally:
            con.close()
        fronts = [row[0] for row in rows]
        tags_text = " ".join(row[1] for row in rows)
        assert "rtos" in tags_text and "critical_section" in tags_text, tags_text
        assert "heap" not in tags_text and "queue" not in tags_text, tags_text
        seen = {t: False for t in ("Alpha", "Beta", "Gamma")}
        last, run_len = None, 0
        for front in fronts:
            topic = front.split()[0]
            if front.endswith("card 0?"):
                seen[topic] = True
            else:
                assert seen[topic], f"{topic} card before its tier-zero anchor"
            run_len = run_len + 1 if topic == last else 1
            last = topic
            assert run_len <= 4, f"topic run too long: {topic} x{run_len}"
        print("ok    built deck scatter/tags")

        # The order above must survive Anki's note insertion and become the deck's
        # new-card order, not just a sorted Python list.
        order_path = td / "order.json"
        order_path.write_text(json.dumps(order_cards))
        order_apkg = td / "order.apkg"
        r = run([sys.executable, str(SCRIPTS / "build_apkg.py"), str(order_path),
                 str(order_apkg), "--deck-name", "ORDER::TEST"])
        assert r.returncode == 0, r.stderr
        extract = td / "order-extract"
        with zipfile.ZipFile(order_apkg) as z:
            z.extract("collection.anki2", extract)
        con = sqlite3.connect(extract / "collection.anki2")
        try:
            due_order = [row[0] for row in con.execute(
                "select n.sfld from cards c join notes n on n.id=c.nid "
                "order by c.due")]
        finally:
            con.close()
        assert due_order == expected_order, due_order
        print("ok    built deck follows foundation-first order")

        # One canonical diagram can be attached to several cards; the package must
        # bundle the file once and both notes must reference it.
        from PIL import Image
        shared = td / "media" / "shared.png"
        shared.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (320, 200), "white").save(shared)
        reuse_cards = [
            dict(BASE, front="What does the shared state diagram show?",
                 back="**Why:** the four task states.", topic="Scheduling",
                 media=[{"file": "media/shared.png", "side": "back",
                         "caption": "state machine"}]),
            dict(BASE, front="Which state is missing from an early diagram?",
                 back="**Why:** the full state machine has all four states.",
                 topic="Scheduling",
                 media=[{"file": "media/shared.png", "side": "back",
                         "caption": "state machine"}]),
        ]
        reuse_path = td / "reuse.json"
        reuse_path.write_text(json.dumps(reuse_cards))
        reuse_apkg = td / "reuse.apkg"
        r = run([sys.executable, str(SCRIPTS / "build_apkg.py"), str(reuse_path),
                 str(reuse_apkg), "--deck-name", "REUSE::TEST", "--media",
                 "--media-root", str(td)])
        assert r.returncode == 0, r.stderr
        extract = td / "reuse-extract"
        with zipfile.ZipFile(reuse_apkg) as z:
            z.extract("collection.anki2", extract)
            media_entries = [n for n in z.namelist() if n.isdigit()]
        con = sqlite3.connect(extract / "collection.anki2")
        try:
            fields = [row[0] for row in con.execute("select flds from notes")]
        finally:
            con.close()
        assert len(media_entries) == 1, media_entries
        assert sum("<img" in f for f in fields) == 2, fields
        print("ok    shared media reused across cards")

        # The tag leak must stop a strict build, not merely print a warning.
        leak_path = td / "leak.json"
        leak_path.write_text(json.dumps(tag_leak))
        leaked_apkg = td / "leaked.apkg"
        r = run([sys.executable, str(SCRIPTS / "build_apkg.py"), str(leak_path),
                 str(leaked_apkg), "--deck-name", "LEAK::TEST", "--strict"])
        assert r.returncode == 1 and not leaked_apkg.exists(), (r.returncode, r.stderr)
        print("ok    strict build rejects answer-bearing tags")

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
        data, _ = validate([dict(BASE, front="Calculate the runtime of nested loops.",
                                 objects=[])], mut)
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
