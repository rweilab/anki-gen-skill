#!/usr/bin/env python3
"""Precision fixtures: legitimate near-misses must not become default warnings."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from validate_cards import check_cards  # noqa: E402
from roi_report import report as roi_report_text  # noqa: E402
from triage import select  # noqa: E402
from build_apkg import study_order  # noqa: E402

BASE = {"layer": "L2", "topic": "Data Structures", "objects": [],
        "deck": "QUALITY::TEST", "source": "Lec 4 p.2"}


def card(front, back, **extra):
    return {**BASE, "front": front, "back": back, **extra}


def main() -> int:
    cards = [
        card("What does a stack do with the most recently pushed item?",
             "It returns it first (LIFO). **Why:** the top is the only accessible end.", tier_zero=True),
        card("What does a queue do with the most recently added item?",
             "It returns it last (FIFO). **Why:** items leave from the front.", tier_zero=True),
        card("What is the difference between a stack and a queue?",
             "A stack is LIFO; a queue is FIFO. **Why:** the accessible end differs."),
        card("How do you convert a 3-index to a 4-index?",
             "Add 1 to each position. **Why:** the reciprocal pair is the confusion being tested."),
        card("How do you convert a 4-index to a 3-index?",
             "Subtract 1 from each position. **Why:** the reciprocal pair is the confusion being tested."),
        card("What is a graph?",
             "A set of vertices and edges. **Glossary:** $V$ = vertices; $E$ = edges. "
             "**Why:** relations are the object of study."),
        card("What is a tree?",
             "A connected acyclic graph. **Glossary:** $V$ = vertices; $E$ = edges. "
             "**Why:** removing cycles makes paths unique."),
        card("When does a greedy algorithm fail?",
             "When a local choice blocks a better global choice. **Why:** the exchange "
             "argument no longer holds; a counterexample is the classic trap.", layer="L3"),
        card("Which structure has the lowest worst-case search for 1,000 sorted items: "
             "array, linked list, or balanced tree?",
             "A balanced tree. **Glossary:** $O(\\cdot)$ = asymptotic upper bound. "
             "**Why:** $O(\\log n)$ beats $O(n)$."),
        card("The three primary colors are {{c1::red}}, {{c2::green}}, and {{c3::blue}}.",
             "Additive mixing uses red, green, and blue. **Why:** the eye has three cone types.",
             layer="L1", cloze=True, source="derived"),
    ]
    errors, warnings, info = check_cards(cards)
    assert not errors, errors
    assert not warnings, warnings
    # Soft duplicates are candidates in the ROI report, not validator warnings;
    # deliberate contrasts may appear there and the debloat pass decides.
    print("ok    legitimate contrast/reciprocal/glossary cards stay clean by default")

    perf = [
        card(f"Perf card {i}?", f"The answer is stable. **Why:** reason number {i} is distinct.",
             topic="Perf", source="derived")
        for i in range(300)
    ]
    started = time.perf_counter()
    check_cards(perf)
    roi_report_text(perf)
    select(perf, 1, 12)
    study_order(perf)
    elapsed = time.perf_counter() - started
    assert elapsed < 5, f"core path took {elapsed:.2f}s on 300 cards"
    print(f"ok    core path stays fast on 300 cards ({elapsed:.2f}s)")

    # A true duplicate is still an exact, deterministic error.
    dup = [cards[0], dict(cards[0])]
    errors, _, _ = check_cards(dup)
    assert any("exact duplicate" in e for e in errors), errors
    pair = [
        card("How is the next task chosen by the scheduler?",
             "The scheduler picks the highest-priority ready task and runs it until it blocks."),
        card("Which task does the scheduler run next when several are ready?",
             "The scheduler picks the highest-priority ready task and runs it until it blocks."),
    ]
    assert "duplicate" in roi_report_text(pair)
    print("ok    exact duplicates remain errors; soft duplicates are ROI candidates")
    print("\nPASS  quality precision")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
