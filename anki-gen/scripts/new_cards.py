#!/usr/bin/env python3
"""Author cards so the cheap mistakes fail on the line that made them.

WHY THIS EXISTS (and why it is not another validator)
-----------------------------------------------------
`validate_cards.py` already catches a dropped `**`, an unbalanced `$...$`, a
control character from a non-raw string. The problem is *when*: it catches them
after the deck has been written, in one batch, at a distance from the line that
caused them. On a real run the same class of defect — a `**` that never closed —
had to be found and fixed twice, both times by re-reading a validator report and
hunting for the card.

So this is not a second opinion. `C()` builds each card and runs the SAME checks
during construction, by importing `findings()` from `validate_cards` — one
definition of what a bad card is, so the two can never disagree about it. What
changes is the latency: the error arrives at the line that wrote the card, with
the card's own text in hand.

USAGE — in the script that emits your cards.json:

    from new_cards import C, dump

    cards = [
        C(front=r"**Vacancies.** Why does a crystal contain them at all?",
          back=r"Because forming one costs energy $Q_v$ ...",
          layer="L2", topic="Vacancies", objects=["vacancy_concentration", "cu"],
          deck="ME 2813", source="Lec 04 p.12"),
        C(front=..., back=..., ..., tier_zero=True),
    ]
    dump(cards, "cards.json")

`C()` raises `CardError` on an *error*-severity problem (a dropped `**`, a
computation-demand front, a missing source) and records *warnings* — a source
with no page number, a Procedure front with no question — in `WARNINGS`, which
`dump()` prints as a short list. Errors stop the line you are writing; warnings
wait until the end, because most of them are judgement calls rather than
mistakes.

    python3 new_cards.py --template        # print a starter block to paste

This is a convenience, not a gate. `validate_cards.py` on the written cards.json
is still the mandatory check, and it re-runs every deck-wide check (near-duplicate
fronts, tier-zero coverage) that a per-card constructor cannot see.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_cards import findings     # noqa: E402
from cardid import load_cards as load   # noqa: E402,F401

REQUIRED = ("front", "back", "layer", "topic", "deck", "source")
LAYERS = {"L1", "L2", "L3", "Procedure"}

# Every warning any card raised, in the order it was raised. Printed by dump().
WARNINGS: list = []


class CardError(ValueError):
    """A card that must not be written as it stands."""


def C(front: str, back: str, *, layer: str, topic: str, deck: str, source: str,
      cloze: bool = False, tier_zero: bool = False, media: list | None = None,
      objects: list | None = None, hash: str = "", strict: bool = True,
      **extra) -> dict:
    """Build one card, checking it as it is built.

    The keyword-only signature is deliberate: `layer`, `topic`, `deck` and
    `source` are required by the validator, so a card that omits one cannot be
    constructed at all, rather than being written and rejected later. `**extra`
    exists for the schema's own pass-through fields (`source_ref`).

    `objects` are 0-2 names of the specific things this card is ABOUT (see
    SKILL.md "The topic is a chapter name, and object tags are a sniper"). They
    become the deck's search tags; `topic` is the chapter name and the only other
    tag.

    `strict=False` returns the card even when it has errors, for the case where
    you want to see the whole deck's problems in one pass. It is not the default
    because the point of this module is to fail early.
    """
    card = {"front": front, "back": back, "layer": layer, "topic": topic,
            "deck": deck, "source": source, "cloze": bool(cloze),
            "tier_zero": bool(tier_zero), "media": list(media or []),
            "objects": list(objects or []), "hash": hash}
    card.update(extra)

    for key in REQUIRED:
        if not str(card.get(key, "")).strip():
            raise CardError(f"empty {key!r} for {str(front)[:50]!r}")
    if card["layer"] not in LAYERS:
        raise CardError(f"bad layer {card['layer']!r} (expected one of "
                        f"{sorted(LAYERS)})")

    # The same checks the validator runs, on this one card. The message keeps the
    # validator's `card 1: 'front...' -- ` prefix stripped: there is no card 1 at
    # the moment of construction, and the front is already in hand.
    problems = validate_card(card)
    errors = [m for sev, m in problems if sev == "err"]
    if errors and strict:
        raise CardError(f"{str(front)[:60]!r}\n  " + "\n  ".join(errors))
    WARNINGS.extend((card, m) for sev, m in problems if sev == "warn")
    return card


def validate_card(card: dict) -> list[tuple[str, str]]:
    """One card's validator findings as (severity, message), deck-level lines dropped.

    Public because authoring and checking both need it: `C()` for the line being
    written, `author.py check` for the lines already on disk. One implementation, so
    the two cannot disagree about what is wrong with a card.
    """
    out = []
    for i, sev, msg in findings([card]):
        if i == 0:
            continue                      # a deck-level line has no card to attach to
        out.append((sev, msg.split(" -- ", 1)[-1]))
    return out


def dump(cards: list, path: str, *, indent: int = 1) -> Path:
    """Write cards.json, then report the warnings collected while building.

    Warnings are printed rather than raised because they are the judgement calls
    (a locator-less citation, a comparison front with no data) that a human should
    see together and decide on -- and because raising on the first one would stop
    the authoring run for something that may be intentional.

    A `.jsonl` path writes one card per line instead. That form exists because the
    review step edits cards one at a time: in an array, every edit is a
    read-modify-write of the whole file, which is both expensive and a silent
    corruption risk on a near-miss. One line per card makes a fix a one-line edit.
    `load()` reads either form, so the two are interchangeable downstream.
    """
    out = Path(path)
    if out.suffix == ".jsonl":
        out.write_text("".join(json.dumps(c) + "\n" for c in cards))
    else:
        out.write_text(json.dumps(cards, indent=indent))
    print(f"{len(cards)} card(s) -> {out}", file=sys.stderr)
    if WARNINGS:
        print(f"{len(WARNINGS)} warning(s) to look at:", file=sys.stderr)
        for card, msg in WARNINGS:
            print(f"  {str(card.get('front', ''))[:44]!r}  {msg.split(' -- ', 1)[-1]}",
                  file=sys.stderr)
    return out


TEMPLATE = '''\
"""Cards for <course>. Write them here, then:  python3 make_cards.py"""

from new_cards import C, dump

DECK = "<deck name>"          # the caller's name; see rule 23
CARDS = [
    C(front=r"<a question answerable from memory>",
      back=r"""<the answer>

**Why:** <the mechanism, 1-3 sentences>""",
      layer="L2", topic="<Topic>", deck=DECK, source="<Lec 07 p.14>"),

    # A tier_zero concept card belongs before each topic's formula cards.
    C(front=r"<the question a student has before meeting any notation>",
      back=r"<plain language first, then the equation>",
      layer="L2", topic="<Topic>", deck=DECK, source="<Lec 07 p.9>",
      tier_zero=True),
]

if __name__ == "__main__":
    dump(CARDS, "cards.json")
    # Then, always:
    #   python3 ~/.claude/skills/anki-gen/scripts/validate_cards.py cards.json
'''


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Authoring helpers for the Python script that emits cards.json.")
    ap.add_argument("--template", action="store_true",
                    help="print a starter script to paste into make_cards.py")
    args = ap.parse_args()
    if args.template:
        print(TEMPLATE)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
