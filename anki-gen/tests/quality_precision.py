#!/usr/bin/env python3
"""Precision fixtures: legitimate near-misses must not become default warnings."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from validate_cards import check_cards  # noqa: E402

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
             "A stack is LIFO; a queue is FIFO. **Why:** the accessible end differs.", stratum="contrast"),
        card("How do you convert a 3-index to a 4-index?",
             "Add 1 to each position. **Why:** the reciprocal pair is the confusion being tested."),
        card("How do you convert a 4-index to a 3-index?",
             "Subtract 1 from each position. **Why:** the reciprocal pair is the confusion being tested."),
        card("What is a graph?",
             "A set of vertices and edges. **Glossary:** $V$ = vertices; $E$ = edges. "
             "**Why:** relations are the object of study.", stratum="definition"),
        card("What is a tree?",
             "A connected acyclic graph. **Glossary:** $V$ = vertices; $E$ = edges. "
             "**Why:** removing cycles makes paths unique.", stratum="definition"),
        card("When does a greedy algorithm fail?",
             "When a local choice blocks a better global choice. **Why:** the exchange "
             "argument no longer holds; a counterexample is the classic trap.", layer="L3"),
        card("Which structure has the lowest worst-case search for 1,000 sorted items: "
             "array, linked list, or balanced tree?",
             "A balanced tree. **Why:** $O(\\log n)$ beats $O(n)$.", stratum="comparison"),
    ]
    errors, warnings, info = check_cards(cards, deep=False)
    assert not errors, errors
    assert not [w for w in warnings if "similar" in w or "overlapping" in w
                or "duplicate" in w], warnings
    # Deep similarity remains available but opt-in; the test only requires that
    # it does not turn legitimate cards into default build failures.
    deep_errors, deep_warnings, _ = check_cards(cards, deep=True)
    assert not deep_errors, deep_errors
    print("ok    legitimate contrast/reciprocal/glossary cards stay clean by default")

    # A true duplicate is still an exact, deterministic error.
    dup = [cards[0], dict(cards[0])]
    errors, _, _ = check_cards(dup, deep=False)
    assert any("exact duplicate" in e for e in errors), errors
    print("ok    exact duplicates remain errors")
    print("\nPASS  quality precision")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
