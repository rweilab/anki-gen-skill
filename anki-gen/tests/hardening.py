#!/usr/bin/env python3
"""Hardening checks: negative fixtures, golden deck, and sabotage probes.

Run by scripts/smoke.sh. Everything is local and temporary; no model calls.
"""
from __future__ import annotations

import contextlib
import io
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
from cardid import card_hash  # noqa: E402
from validate_cards import similar_answer_pairs  # noqa: E402
import new_cards  # noqa: E402
from new_cards import C, CardError, dump  # noqa: E402
from parse_intent import parse_intent  # noqa: E402
from render import with_source  # noqa: E402

BASE = {
    "front": "Why does a vacancy increase a crystal's free energy?",
    "back": "**Why:** forming a vacancy costs energy $Q_v$, but configurational "
            "entropy lowers the free energy at finite temperature.",
    "layer": "L2", "topic": "Point Defects", "objects": ["vacancy"],
    "deck": "GOLDEN::TEST", "source": "Lec 04 p.12", "tier_zero": True,
}


def run(cmd, env=None):
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def validate(cards, scripts=SCRIPTS, deep=False):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "cards.json"
        p.write_text(json.dumps(cards))
        cmd = [sys.executable, str(scripts / "validate_cards.py"), str(p), "--json"]
        if deep:
            cmd.append("--deep")
        r = run(cmd)
        try:
            return json.loads(r.stdout), r
        except json.JSONDecodeError as e:
            raise AssertionError(f"validator did not emit JSON: {r.stdout}\n{r.stderr}") from e


def validate_with(cards, ledger=None, source=None):
    """Run the CLI with the optional KC map and source corpus."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        p = root / "cards.json"
        p.write_text(json.dumps(cards))
        cmd = [sys.executable, str(SCRIPTS / "validate_cards.py"), str(p), "--json"]
        if ledger is not None:
            lp = root / "authoring_ledger.md"
            lp.write_text(ledger)
            cmd += ["--ledger", str(lp)]
        if source is not None:
            sp = root / "sources.md"
            sp.write_text(source)
            cmd += ["--source", str(sp)]
        r = run(cmd)
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
    derived, _ = validate([dict(BASE, source="derived")])
    assert derived["valid"] is True, derived
    assert with_source("<p>x</p>", "derived") == "<p>x</p>"
    print("ok    positive control and derived-source policy")

    skill = (ROOT / "SKILL.md").read_text()
    for phrase in ("Main-model vision is a last-resort",
                   "Never spawn a child `opencode` process",
                   "Do not probe for LibreOffice",
                   "Never open, copy, query, or inspect the live collection DB"):
        assert phrase in skill, f"guardrail missing from SKILL.md: {phrase!r}"
    revision = (ROOT / "references" / "revision.md").read_text()
    assert "collection.anki2" in revision and "AnkiConnect" in revision
    maintainers = (ROOT / "MAINTAINERS.md").read_text()
    for phrase in ("## Quality contract", "**98%**", "4. speed"):
        assert phrase in maintainers, f"quality contract missing: {phrase!r}"
    assert (maintainers.index("1. correctness")
            < maintainers.index("3. token and API-call efficiency")
            < maintainers.index("4. speed")), "quality priority order changed"
    assert "quality contract in `MAINTAINERS.md`" in (ROOT / "AGENTS.md").read_text()
    print("ok    execution and quality guardrails present")

    # Identity follows content, never a stale explicit hash.
    stale = dict(BASE, hash="deadbeef")
    edited = dict(stale, front="Why did the answer change after the fix?")
    assert card_hash(stale) != "deadbeef", card_hash(stale)
    assert card_hash(edited) != card_hash(stale), (card_hash(stale), card_hash(edited))
    print("ok    stale explicit hash is ignored")

    intent = parse_intent('make 30 cards --deck-name "My Deck" from Lec/')
    assert intent["deck_name"] == "My Deck", intent
    assert "max_cards" not in intent and "sources" not in intent, intent
    assert "video_frames" not in intent, intent
    help_run = run([sys.executable, str(SCRIPTS / "parse_intent.py"), "--help"])
    assert help_run.returncode == 0 and "Usage:" in help_run.stdout, help_run
    print("ok    intent keeps quoted deck names and --help")

    # Rule 26 and markdown images are structural defects, not style choices.
    pointer = dict(BASE, back="See the magnitude card for the numbers. **Why:** it catches units.")
    data, _ = validate([pointer])
    assert any("points at another card" in e for e in data["errors"]), data
    code_pointer = dict(BASE, back="Use `see the card` as a literal example. **Why:** it is quoted.")
    data, _ = validate([code_pointer])
    assert not any("points at another card" in e for e in data["errors"]), data
    md_image = dict(BASE, back="![cell](media/x.png) **Why:** a figure.")
    data, _ = validate([md_image])
    assert any("literal markdown image" in e for e in data["errors"]), data
    code_image = dict(BASE, back="Use `![alt](x)` as a literal example. **Why:** quoted.")
    data, _ = validate([code_image])
    assert not any("literal markdown image" in e for e in data["errors"]), data

    # Cloze must close; the build path has a second guard for the same shape.
    unterminated = dict(BASE, front="The cell has {{c1::2 atoms and a long enough sentence.",
                        cloze=True)
    data, _ = validate([unterminated])
    assert any("never closes" in e for e in data["errors"]), data
    print("ok    pointer/markdown-image/unterminated-cloze guards")

    # Glossary is info, not a warning that forces boilerplate.
    sym = dict(BASE, front="How do $N_v$, $N_s$, and $Q_v$ relate at equilibrium?",
               back="The ratio is a function of $Q_v$.", layer="L2")
    data, _ = validate([sym])
    assert not any("symbol-heavy" in w for w in data["warnings"]), data
    assert any("symbol-heavy" in i for i in data["info"]), data

    # Tier-zero coverage is a narrow warning, and table recall is not a formula.
    formula_cards = [
        dict(BASE, topic="Formula Topic", objects=[], tier_zero=False, front=f"Formula card {i}: why does $x_{i}$ hold?")
        for i in range(3)
    ]
    data, _ = validate(formula_cards)
    assert any("no tier-zero" in w for w in data["warnings"]), data
    with_tz = formula_cards + [dict(BASE, topic="Formula Topic", objects=[],
                                    front="What is the idea before the formulas?",
                                    tier_zero=True)]
    data, _ = validate(with_tz)
    assert not any("no tier-zero" in w for w in data["warnings"]), data
    table_cards = [
        dict(BASE, topic="Table Topic", objects=[], tier_zero=False,
             back="Use the printed table; **Why:** the ranking is a lookup.",
             front=f"Which of the four structures ranks highest on property {i}?")
        for i in range(3)
    ]
    data, _ = validate(table_cards)
    assert not any("no tier-zero" in w for w in data["warnings"]), data
    print("ok    glossary info and narrow tier-zero warning")

    bloat = [dict(BASE, topic="Bloat", objects=[], tier_zero=False,
                  front=f"Which structure property number {i} does the table list?",
                  back=f"Use table row {i}; **Why:** it is a lookup.")
             for i in range(16)]
    data, _ = validate(bloat)
    assert any("has 16 cards" in w for w in data["warnings"]), data
    print("ok    topic bloat warning")

    ledger = """# Authoring ledger

## KCs
| kc_id | type | claim | source | evidence_quote | requires |
|---|---|---|---|---|---|
| thermo.control_volume | concept | A control volume is fixed. | Lec 04 p.3 | A control volume is fixed. | — |
| thermo.steady_flow | procedure | Apply the steady-flow equation. | Lec 04 p.12 | Apply the steady-flow equation. | thermo.control_volume |
"""
    kc_cards = [
        dict(BASE, front="What is a control volume?",
             back="A fixed region in space. **Why:** mass flows through it.",
             kc="thermo.control_volume", stratum="concept", source="Lec 04 p.3"),
        dict(BASE, front="Which equation applies to a steady-flow device?",
             back="The steady-flow energy equation. **Why:** mass and energy balance.",
             kc="thermo.steady_flow", stratum="procedure", source="Lec 04 p.12"),
        dict(BASE, front="Why does the steady-flow equation need a control volume?",
             back="It balances mass and energy across that fixed region. **Why:** the bookkeeping needs a boundary.",
             kc="thermo.steady_flow", stratum="mechanism", source="Lec 04 p.12"),
    ]
    data, _ = validate_with(kc_cards, ledger=ledger,
                             source="A control volume is fixed. Apply the steady-flow equation.")
    assert data["valid"] is True, data
    print("ok    KC map links cards and resolves prerequisites")

    data, _ = validate_with([dict(kc_cards[0], kc="")], ledger=ledger,
                             source="A control volume is fixed.")
    assert any("missing 'kc'" in e for e in data["errors"]), data
    data, _ = validate_with([dict(kc_cards[0], kc="thermo.unknown")], ledger=ledger,
                             source="A control volume is fixed.")
    assert any("not in the KC map" in e for e in data["errors"]), data
    bad_ledger = """# Authoring ledger

## KCs
| kc_id | type | claim | source | evidence_quote | requires |
|---|---|---|---|---|---|
| thermo.control_volume | concept | A control volume is fixed. | Lec 04 p.3 | A control volume is fixed. | — |
| thermo.steady_flow | procedure | Apply the steady-flow equation. | Lec 04 p.12 | Apply the steady-flow equation. | thermo.missing |
"""
    data, _ = validate_with([kc_cards[1], kc_cards[2]], ledger=bad_ledger,
                             source="Apply the steady-flow equation.")
    assert any("requires unknown KC" in e for e in data["errors"]), data
    data, _ = validate_with([kc_cards[0]], ledger=ledger,
                             source="A control volume is fixed.")
    assert any("has no cards" in w for w in data["warnings"]), data
    print("ok    KC coverage and dependency failures are caught")

    flat_ledger = """# Authoring ledger

## KCs
| kc_id | type | claim | source | evidence_quote | requires |
|---|---|---|---|---|---|
| thermo.control_volume | concept | A control volume is fixed. | Lec 04 p.3 | A control volume is fixed. | — |
| thermo.steady_flow | procedure | Apply the steady-flow equation. | Lec 04 p.12 | Apply the steady-flow equation. | — |
"""
    flat_cards = [kc_cards[0], kc_cards[1]]
    data, _ = validate_with(flat_cards, ledger=flat_ledger,
                             source="A control volume is fixed. Apply the steady-flow equation.")
    assert data["valid"] is True, data
    assert any("every KC has exactly one card" in w for w in data["warnings"]), data
    assert any("single-card concept" in w for w in data["warnings"]), data
    print("ok    flat KC map warns instead of forcing filler")

    why_ledger = """# KCs — Thermodynamics

| kc | type | claim | why | requires | evidence_quote | source |
|---|---|---|---|---|---|---|
| thermo.control_volume | concept | A control volume is fixed. | Reused by every balance | — | A control volume is fixed. | Lec 04 p.3 |
| thermo.steady_flow | procedure | Apply the steady-flow equation. | One-card method choice | thermo.control_volume | Apply the steady-flow equation. | Lec 04 p.12 |
"""
    data, _ = validate_with(kc_cards, ledger=why_ledger,
                             source="A control volume is fixed. Apply the steady-flow equation.")
    assert data["valid"] is True, data
    assert not any("missing 'why'" in e for e in data["errors"]), data
    print("ok    h1 KCs table with why parses and validates")
    both_heading = why_ledger.replace("# KCs — Thermodynamics",
                                      "# KCs — Thermodynamics\n\n## KCs")
    data, _ = validate_with(kc_cards, ledger=both_heading,
                             source="A control volume is fixed. Apply the steady-flow equation.")
    assert data["valid"] is True, data
    print("ok    h1 and h2 KCs headings both parse")

    data, _ = validate_with(kc_cards, ledger=why_ledger.replace("Reused by every balance", "—"),
                             source="A control volume is fixed. Apply the steady-flow equation.")
    assert any("missing 'why'" in e for e in data["errors"]), data
    print("ok    missing why is an error")

    dup = why_ledger.replace("Apply the steady-flow equation. | One-card method choice",
                             "A control volume is fixed. | One-card method choice")
    data, _ = validate_with(kc_cards, ledger=dup,
                             source="A control volume is fixed. Apply the steady-flow equation.")
    assert any("exact same claim" in e for e in data["errors"]), data
    print("ok    duplicate KC claims are rejected")

    boundary_card = dict(kc_cards[0], front="Why is a control volume useful?",
                         back="It gives the balance a fixed boundary. **Why:** the bookkeeping needs a region.",
                         kc="thermo.boundary", stratum="boundary")
    boundary_ledger = """# KCs — Boundary

| kc | type | claim | why | requires | evidence_quote | source |
|---|---|---|---|---|---|---|
| thermo.control_volume | concept | A control volume is fixed. | Reused by every balance | — | A control volume is fixed. | Lec 04 p.3 |
| thermo.boundary | boundary | A control volume gives a balance a fixed boundary. | Single high-value boundary case | thermo.control_volume | A control volume is fixed. | Lec 04 p.3 |
"""
    data, _ = validate_with([kc_cards[0], dict(kc_cards[0], front="Why does a control volume help a balance?",
                                               back="It fixes the region. **Why:** the boundary is the bookkeeping device.",
                                               kc="thermo.control_volume"), boundary_card],
                             ledger=boundary_ledger,
                             source="A control volume is fixed.")
    assert data["valid"] is True, data
    assert not any("single-card boundary" in w for w in data["warnings"]), data
    print("ok    single-card boundary KC is allowed")
    no_stratum = [dict(kc_cards[1], stratum=""), dict(kc_cards[2], stratum="")]
    data, _ = validate_with(no_stratum, ledger=ledger,
                             source="A control volume is fixed. Apply the steady-flow equation.")
    assert data["valid"] is True, data
    print("ok    stratum is optional when the KC type carries the family")

    bad_quote_ledger = ledger.replace("A control volume is fixed. | —",
                                      "Entropy always decreases. | —")
    data, _ = validate_with(kc_cards, ledger=bad_quote_ledger,
                             source="A control volume is fixed. Apply the steady-flow equation.")
    assert any("not in the extracted source" in e for e in data["errors"]), data
    missing_quote_ledger = ledger.replace("A control volume is fixed. | —", "— | —")
    data, _ = validate_with(kc_cards, ledger=missing_quote_ledger,
                             source="A control volume is fixed. Apply the steady-flow equation.")
    assert any("need an evidence_quote" in e for e in data["errors"]), data
    derived_ledger = ledger.replace("Lec 04 p.3 | A control volume is fixed.",
                                    "derived | —")
    data, _ = validate_with(kc_cards, ledger=derived_ledger,
                             source="A control volume is fixed. Apply the steady-flow equation.")
    assert data["valid"] is True, data
    legacy_ledger = """# Authoring ledger

## KCs
| kc_id | type | claim | source | requires |
|---|---|---|---|---|
| thermo.control_volume | concept | A control volume is fixed. | Lec 04 p.3 | — |
| thermo.steady_flow | procedure | Apply the steady-flow equation. | Lec 04 p.12 | thermo.control_volume |
"""
    data, _ = validate_with(kc_cards, ledger=legacy_ledger,
                             source="A control volume is fixed. Apply the steady-flow equation.")
    assert data["valid"] is True and not any("evidence_quote" in w for w in data["warnings"]), data
    print("ok    KC evidence is grounded; derived and legacy maps are handled")
    quoted_ledger = ledger.replace(
        "| Lec 04 p.3 | A control volume is fixed. | — |",
        "| Lec 04 p.3 | \"A control volume is fixed.\" | — |")
    data, _ = validate_with(kc_cards, ledger=quoted_ledger,
                             source="A control volume is fixed. Apply the steady-flow equation.")
    assert data["valid"] is True, data
    print("ok    quoted evidence cells are accepted")

    procedure = dict(BASE, layer="Procedure",
                     front="A block on a rough incline. Determine the acceleration. Which method applies?",
                     back="Use Newton's second law with a friction component. **Why:** the net force sets the acceleration.",
                     source="Lec 04 p.12")
    data, _ = validate([procedure])
    assert not any("computation prompt" in e for e in data["errors"]), data
    print("ok    Procedure Shape A decision fronts are exempt from the computation gate")

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
    case("duplicate object case", lambda: [dict(BASE, objects=["RtOs", "rtos"])],
         "warning", "duplicate object")
    case("front refers to unseen image",
         lambda: [dict(BASE, objects=[], front="For the circuit shown, what is the current?")],
         "warning", "front refers")
    case("multi-blank cloze without labels",
         lambda: [dict(BASE, objects=[], front="{{c1::5}} and {{c2::7}}", cloze=True)],
         "warning", "multi-blank")
    front_media, _ = validate([dict(
        BASE, front="For the circuit shown, what is the current?",
        media=[{"file": "figure.png", "side": "front"}])])
    assert not any("front refers" in w for w in front_media["warnings"]), front_media
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
    case("exact duplicate cards", lambda: [BASE, BASE],
         "error", "exact duplicates")
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
    C(front=BASE["front"], back=BASE["back"], layer=BASE["layer"],
      topic=BASE["topic"], deck="UNIQUE::TEST", source=BASE["source"])
    try:
        C(front=BASE["front"], back=BASE["back"], layer=BASE["layer"],
          topic=BASE["topic"], deck="UNIQUE::TEST", source=BASE["source"])
    except CardError as e:
        assert "exact duplicate" in str(e), e
    else:
        raise AssertionError("new_cards.C accepted an exact duplicate")
    print("ok    authoring helper rejects exact duplicates")

    new_cards.ERRORS.clear()
    new_cards.WARNINGS.clear()
    new_cards._SEEN.clear()
    bad1 = C(front="33 g Cu and 47 g Zn. What are the atom percents?",
             back="Work it out.", layer="L1", topic="Alloys",
             deck="BATCH::TEST", source="Lec 1 p.1", strict=False)
    bad2 = C(front="Calculate the density from 10 g and 2 cm3.",
             back="Work it out.", layer="L1", topic="Density",
             deck="BATCH::TEST", source="Lec 1 p.2", strict=False)
    assert len(new_cards.ERRORS) >= 2, new_cards.ERRORS
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "cards.jsonl"
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                dump([bad1, bad2], target)
        except CardError as e:
            assert "refusing to write" in str(e), e
        else:
            raise AssertionError("new_cards.dump wrote cards with errors")
        assert not target.exists(), target
    new_cards.ERRORS.clear()
    new_cards.WARNINGS.clear()
    new_cards._SEEN.clear()
    print("ok    authoring helper reports all batch errors and refuses to write")

    print("ok    front-visible tag leak warning")
    data, _ = validate([dict(BASE, front="What does P_0 mean at the surface?",
                             back="Use $P_0$ and `x_1` in prose.")])
    assert any("bare symbol 'P_0'" in w for w in data["warnings"]), data
    data, _ = validate([dict(BASE, front="What does $P_0$ mean at the surface?",
                             back="Use `x_1` in code.")])
    assert not any("bare symbol" in w for w in data["warnings"]), data
    data, _ = validate([dict(BASE, front="Line one<br>Line two",
                             back="A normal answer.")])
    assert any("literal <br>" in w for w in data["warnings"]), data
    print("ok    MathJax symbols and literal <br> are warned")


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
        data, _ = validate(same_answer, mut, deep=True)
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

    r = run([sys.executable, str(SCRIPTS / "roi_report.py"), str(GOLDEN),
             "--list"])
    assert r.returncode == 0, r.stderr
    assert len(r.stdout.splitlines()) == 5, r.stdout
    assert "**Why:**" not in r.stdout and "Glossary" not in r.stdout, r.stdout
    print("ok    roi_report --list prints fronts without backs")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        concepts = td / "concepts.jsonl"
        concepts.write_text(json.dumps({
            "layer": "L2", "topic": "Authoring",
            "source": "Lec 1 p.1", "objects": ["authoring"],
        }) + "\n")
        stubs = td / "stubs.jsonl"
        r = run([sys.executable, str(SCRIPTS / "author.py"), "scaffold",
                 str(concepts), "-o", str(stubs), "--deck", "AUTHOR::TEST"])
        assert r.returncode == 0, (r.stdout, r.stderr)
        rows = [json.loads(x) for x in stubs.read_text().splitlines()]
        assert len(rows) == 1 and rows[0]["front"] == rows[0]["back"] == "", rows
        filled = td / "filled.jsonl"
        rows[0]["front"] = "What does the authoring scaffold do?"
        rows[0]["back"] = "It writes stubs. **Why:** it keeps the deck shape on disk."
        filled.write_text("".join(json.dumps(x) + "\n" for x in rows))
        r = run([sys.executable, str(SCRIPTS / "author.py"), "check", str(stubs)])
        assert r.returncode == 1, (r.stdout, r.stderr)
        r = run([sys.executable, str(SCRIPTS / "author.py"), "check", str(filled)])
        assert r.returncode == 0, (r.stdout, r.stderr)
        final = td / "final.json"
        r = run([sys.executable, str(SCRIPTS / "author.py"), "finalize",
                 str(stubs), str(final), "--deck", "AUTHOR::TEST"])
        assert r.returncode == 2, (r.stdout, r.stderr)
        r = run([sys.executable, str(SCRIPTS / "author.py"), "finalize",
                 str(filled), str(final), "--deck", "AUTHOR::TEST"])
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert "hash" not in json.loads(final.read_text())[0]
        print("ok    author.py scaffold/check/finalize")

        good_apkg = td / "golden.apkg"
        r = run([sys.executable, str(SCRIPTS / "build_apkg.py"), str(GOLDEN),
                 str(good_apkg), "--deck-name", "GOLDEN::TEST"])
        assert r.returncode == 0, r.stderr
        r = run([sys.executable, str(SCRIPTS / "validate_apkg.py"), str(good_apkg)])
        assert r.returncode == 0, r.stderr
        assert "5 notes" in r.stdout, r.stdout
        no_anki = run([sys.executable, "-S", str(SCRIPTS / "validate_apkg.py"),
                       str(good_apkg)])
        assert no_anki.returncode == 3, (no_anki.stdout, no_anki.stderr)
        assert "STRUCTURAL ONLY — NOT IMPORT-VALIDATED" in (no_anki.stdout + no_anki.stderr), no_anki
        print("ok    golden build/import and missing-anki honesty")

        # A corrected card must not keep an old explicit hash and be skipped by
        # merge. If this fails, the fix silently never reaches Anki.
        stale_cards = [dict(BASE, hash="deadbeef", objects=[])]
        stale_path = td / "stale.json"
        stale_path.write_text(json.dumps(stale_cards))
        first_apkg = td / "stale-first.apkg"
        r = run([sys.executable, str(SCRIPTS / "build_apkg.py"), str(stale_path),
                 str(first_apkg), "--deck-name", "STALE::TEST"])
        assert r.returncode == 0, r.stderr
        stale_cards[0]["front"] = "Why did the corrected card change the deck?"
        stale_path.write_text(json.dumps(stale_cards))
        merged_apkg = td / "stale-merged.apkg"
        r = run([sys.executable, str(SCRIPTS / "build_apkg.py"), str(stale_path),
                 str(merged_apkg), "--deck-name", "STALE::TEST",
                 "--merge-existing", str(first_apkg)])
        assert r.returncode == 0, r.stderr
        with tempfile.TemporaryDirectory() as ex:
            with zipfile.ZipFile(merged_apkg) as z:
                z.extract("collection.anki2", ex)
            con = sqlite3.connect(Path(ex) / "collection.anki2")
            try:
                count = con.execute("select count(*) from notes").fetchone()[0]
            finally:
                con.close()
        assert count == 2, count
        print("ok    edited card gets a new content identity")

        invalid = [dict(BASE, objects=[], front="Calculate the runtime of nested loops.")]
        invalid_path = td / "invalid.json"
        invalid_path.write_text(json.dumps(invalid))
        r = run([sys.executable, str(SCRIPTS / "build_apkg.py"), str(invalid_path),
                 str(td / "invalid.apkg"), "--deck-name", "INVALID::TEST"])
        assert r.returncode != 0 and not (td / "invalid.apkg").exists(), r.stderr
        r = run([sys.executable, str(SCRIPTS / "build_apkg.py"), str(invalid_path),
                 str(td / "invalid.apkg"), "--deck-name", "INVALID::TEST",
                 "--allow-invalid"])
        assert r.returncode == 0, r.stderr
        print("ok    build validation is default with diagnosis escape")

        # Cloze: one deletion is one card; two distinct deletions are two cards.
        # The old check was inert, and its count comparison would have failed the
        # valid one-deletion note.
        cloze_cards = [
            {"front": "A body-centred cell has {{c1::2}} atoms per unit cell.",
             "back": "Eight corners at 1/8 plus one interior atom, in a long enough back.",
             "layer": "L1", "topic": "Cloze", "cloze": True, "deck": "CLOZE::TEST",
             "source": "Lec 1 p.1"},
            {"front": "SC has {{c1::4}} atoms and BCC has {{c2::2}} atoms per cell.",
             "back": "Count the corners, faces, and interior atoms in a long enough back.",
             "layer": "L1", "topic": "Cloze", "cloze": True, "deck": "CLOZE::TEST",
             "source": "Lec 1 p.2"},
        ]
        cloze_path = td / "cloze.json"
        cloze_path.write_text(json.dumps(cloze_cards))
        cloze_apkg = td / "cloze.apkg"
        r = run([sys.executable, str(SCRIPTS / "build_apkg.py"), str(cloze_path),
                 str(cloze_apkg), "--deck-name", "CLOZE::TEST"])
        assert r.returncode == 0, r.stderr
        r = run([sys.executable, str(SCRIPTS / "validate_apkg.py"), str(cloze_apkg)])
        assert r.returncode == 0, r.stdout + r.stderr
        assert "2 notes" in r.stdout, r.stdout

        broken = td / "cloze-broken.apkg"
        with zipfile.ZipFile(cloze_apkg) as z:
            files = {n: z.read(n) for n in z.namelist()}
        with tempfile.TemporaryDirectory() as ex:
            (Path(ex) / "collection.anki2").write_bytes(files["collection.anki2"])
            con = sqlite3.connect(Path(ex) / "collection.anki2")
            try:
                nid = con.execute(
                    "select id from notes where flds like '%c2::%'").fetchone()[0]
                con.execute("delete from cards where nid=?", (nid,))
                con.commit()
            finally:
                con.close()
            files["collection.anki2"] = (Path(ex) / "collection.anki2").read_bytes()
        with zipfile.ZipFile(broken, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in files.items():
                z.writestr(name, data)
        r = run([sys.executable, str(SCRIPTS / "validate_apkg.py"), str(broken)])
        assert r.returncode != 0 and "cloze deletion" in (r.stdout + r.stderr), r.stdout
        print("ok    cloze integrity (valid and sabotaged)")

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
                 str(scatter_apkg), "--deck-name", "SCATTER::TEST", "--allow-invalid"])
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
        assert tags_text == tags_text.lower(), tags_text
        assert "alpha" in tags_text and "Alpha" not in tags_text, tags_text
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
                 str(order_apkg), "--deck-name", "ORDER::TEST", "--allow-invalid"])
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
                 "--media-root", str(td), "--allow-invalid"])
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

        missing_cards = [
            dict(BASE, objects=[], media=[{"file": "media/missing-a.png"}]),
            dict(BASE, objects=[], front="Which missing figure is listed second?",
                 media=[{"file": "media/missing-b.png"}]),
        ]
        missing_path = td / "missing.json"
        missing_path.write_text(json.dumps(missing_cards))
        r = run([sys.executable, str(SCRIPTS / "build_apkg.py"), str(missing_path),
                 str(td / "missing.apkg"), "--deck-name", "MISS::TEST", "--media",
                 "--media-root", str(td)])
        assert r.returncode != 0, (r.stdout, r.stderr)
        assert "missing-a.png" in r.stderr and "missing-b.png" in r.stderr, r.stderr
        print("ok    missing media is reported together")

        # The tag leak must stop a build, not merely print a warning.
        leak_path = td / "leak.json"
        leak_path.write_text(json.dumps(tag_leak))
        leaked_apkg = td / "leaked.apkg"
        r = run([sys.executable, str(SCRIPTS / "build_apkg.py"), str(leak_path),
                 str(leaked_apkg), "--deck-name", "LEAK::TEST"])
        assert r.returncode == 1 and not leaked_apkg.exists(), (r.returncode, r.stderr)
        print("ok    build validation rejects answer-bearing tags")

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

        # A missing core library gives a clean feature error, not a traceback.
        no_anki = td / "no-anki.apkg"
        r = run([sys.executable, "-S", str(SCRIPTS / "build_apkg.py"),
                 str(GOLDEN), str(no_anki), "--deck-name", "NO::ANKI"])
        assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
        assert "anki library is required" in r.stderr, r.stderr
        print("ok    missing anki library fails cleanly")

        # Sabotage 4: drop source footers in the native builder.
        mut = copy_scripts(td / "mut-build")
        mutate(mut / "build_native.py", mut / "build_native.py",
               [('src = str(c.get("source") or c.get("source_ref") or "")', 'src = ""')])
        bad_apkg = td / "bad.apkg"
        r = run([sys.executable, str(mut / "build_apkg.py"), str(GOLDEN),
                 str(bad_apkg), "--deck-name", "GOLDEN::TEST"])
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
