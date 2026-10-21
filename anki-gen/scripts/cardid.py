#!/usr/bin/env python3
"""One definition of a card's identity.

WHY THIS IS ITS OWN MODULE
--------------------------
A card's identity is used in three places that must agree exactly:

  * build_native.py   sets the note GUID from it
  * review_server.py  records it with every review score
  * triage.py         writes it into the review plan

When two of those derive the hash independently they agree by luck, not by
construction. Keeping the definition here means the heavier build-time imports
stay out of the way of callers that only need to agree on what a card *is*.

There is deliberately no tombstone filter here. A review score of 5 means the
card should not exist, and the way to make that true is to remove it from the
source of truth -- a hash list cannot do it, because the hash changes the moment
the card's text is edited, which is exactly what a re-scope does.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def load_cards(path) -> list[dict]:
    """Read a deck in either form: one JSON array, or one card per line (JSONL).

    Both are supported because they answer different needs. JSONL is the better
    authoring form -- the review step edits cards one at a time, and in an array
    every edit is a read-modify-write of the whole file (expensive, and silent
    corruption on a near-miss), while one line per card makes a fix one line.
    The array is supported because it is what every deck written before JSONL
    uses, and what the schema documents.

    One loader, here, so the builder, the validator, triage and the review server
    cannot disagree about what a deck file is.
    """
    text = Path(path).read_text()
    if Path(path).suffix == ".jsonl":
        return [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    return json.loads(text)


def card_hash(c: dict) -> str:
    """A card's stable identity.

    Prefers an explicit `hash` field, which is what the writer emits, and falls
    back to md5 of `front|back` -- matching `--merge-existing`'s content key, so
    the two notions of "this card already exists" cannot drift apart.
    """
    return c.get("hash") or hashlib.md5(
        f"{c.get('front', '')}|{c.get('back', '')}".encode()).hexdigest()


def last_row_per_card(rows: list[dict]) -> dict[str, dict]:
    """Reduce an append-only feedback log to one row per card: the LAST one.

    The log is append-per-event and last-write-wins (see review_server.Store), so
    reading it raw is a trap -- a card clicked 5 while cycling and then left on 3
    still has that 5 sitting in the file. Any decision about a card (cut it, keep
    it, rewrite it) has to be made from its final row or it is made from a score
    the reviewer has since changed.

    Keyed by hash (the card's identity), falling back to the card number for rows
    written before the hash was carried.
    """
    out: dict[str, dict] = {}
    for r in rows:
        key = str(r.get("hash") or r.get("n") or r.get("i"))
        out[key] = r
    return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print(json.dumps({"error": "Usage: cardid.py <feedback.jsonl>"}))
        raise SystemExit(1)
    rows = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()
            if line.strip()]
    print(json.dumps(last_row_per_card(rows), indent=2))