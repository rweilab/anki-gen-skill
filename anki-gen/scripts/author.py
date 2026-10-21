#!/usr/bin/env python3
"""Put the deck's shape on disk before the cards are written.

The authoring step is the expensive one, and most of it is duplicated: the deck gets
composed in reasoning, then composed again in the file. The cause is uncertainty -- how
many cards, which fields, what is still missing -- and it can only be resolved by reading
a file that already exists. So write the shape first:

    scaffold concepts.jsonl  -> cards.jsonl   (one stub per concept, front/back blank)
    <fill each line>
    check cards.jsonl        -> one line: written vs stub
    finalize cards.jsonl ... -> cards.json    (hashes filled, gates ready)

`check` matters: the alternative is reading the deck back to see progress, which costs
~13k tokens for a 61-card deck the model already wrote.

It will not invent a card, pick a layer, or fill a blank. Those are judgements (SKILL.md
stages 5 and 7) and stay with the model.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cardid import card_hash, load_cards            # noqa: E402
from new_cards import validate_card                 # noqa: E402

LAYERS = {"L1", "L2", "L3", "Procedure"}
REQUIRED = ("layer", "topic", "source")
OPTIONAL = ("objects", "stratum", "tier_zero", "cloze", "media")


def is_stub(c: dict) -> bool:
    return not str(c.get("front", "")).strip() or not str(c.get("back", "")).strip()


def write_rows(path: str, rows: list[dict]) -> None:
    Path(path).write_text(json.dumps(rows, indent=1) + "\n" if Path(path).suffix == ".json"
                          else "".join(json.dumps(r) + "\n" for r in rows))


def read_rows(path: str) -> list[dict]:
    text = Path(path).read_text()
    return json.loads(text) if Path(path).suffix == ".json" else [
        json.loads(ln) for ln in text.splitlines() if ln.strip()]


def scaffold(args) -> int:
    rows, bad = [], []
    for i, c in enumerate(read_rows(args.concepts), 1):
        missing = [k for k in REQUIRED if not str(c.get(k, "")).strip()]
        if missing:
            bad.append(f"concept {i}: missing {', '.join(missing)}")
        elif c["layer"] not in LAYERS:
            bad.append(f"concept {i}: bad layer {c['layer']!r}")
        else:
            # Every field the builder reads is present, so filling a line needs only the
            # two strings -- no schema decision, no field-name recall.
            rows.append({"layer": c["layer"], "topic": c["topic"], "source": c["source"],
                         "deck": args.deck, "front": "", "back": "",
                         **{k: c[k] for k in OPTIONAL if k in c}})
    if bad:
        print(f"{len(bad)} unusable concept(s):", file=sys.stderr)
        for b in bad:
            print("  " + b, file=sys.stderr)
    write_rows(args.out, rows)
    topics: dict[str, int] = {}
    for r in rows:
        topics[r["topic"]] = topics.get(r["topic"], 0) + 1
    top = sorted(topics.items(), key=lambda x: -x[1])
    print(f"scaffold   {len(rows)} stub(s) -> {args.out}, {len(topics)} topic(s)")
    print("           " + ", ".join(f"{t}×{n}" for t, n in top[:8])
          + (f", +{len(top) - 8} more" if len(top) > 8 else ""))
    return 1 if bad else 0


def check(args) -> int:
    cards = load_cards(args.cards)
    stubs = [i for i, c in enumerate(cards, 1) if is_stub(c)]
    # Validate written lines only: a stub's empty front would fire every text check and
    # bury the real problems.
    broken = []
    for i, c in enumerate(cards, 1):
        if not is_stub(c):
            errs = [m for sev, m in validate_card(c) if sev == "err"]
            if errs:
                broken.append((i, errs[0]))
    line = f"check      {len(cards) - len(stubs)} of {len(cards)} written"
    if stubs:
        shown = ", ".join(map(str, stubs[:12]))
        line += f", {len(stubs)} stub(s) at {shown}"
        if len(stubs) > 12:
            line += f" (+{len(stubs) - 12})"
    print(line)
    for i, msg in broken[:8]:
        print(f"  card {i}: {msg}", file=sys.stderr)
    if len(broken) > 8:
        print(f"  ... and {len(broken) - 8} more", file=sys.stderr)
    untouched = [t for t, v in _by_topic(cards).items() if all(v)]
    if untouched:
        print(f"untouched  {len(untouched)} topic(s): " + ", ".join(sorted(untouched)[:10]))
    return 1 if (stubs or broken) else 0


def _by_topic(cards: list[dict]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for c in cards:
        out.setdefault(c.get("topic", "?"), []).append(1 if is_stub(c) else 0)
    return out


def finalize(args) -> int:
    cards = load_cards(args.cards)
    stubs = [i for i, c in enumerate(cards, 1) if is_stub(c)]
    if stubs:
        # An empty field is legal in Anki, so the builder cannot catch a hole. Refuse.
        print(f"refusing to finalize: {len(stubs)} stub(s) at "
              f"{', '.join(map(str, stubs[:12]))}", file=sys.stderr)
        return 2
    for c in cards:
        c["deck"] = c.get("deck") or args.deck
        c["hash"] = card_hash(c)
    write_rows(args.out, cards)
    print(f"finalize   {len(cards)} card(s) -> {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="author.py", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scaffold")
    s.add_argument("concepts", help="{layer,topic,source,...} per line")
    s.add_argument("-o", "--out", default="cards.jsonl")
    s.add_argument("--deck", required=True)
    s.set_defaults(func=scaffold)
    c = sub.add_parser("check")
    c.add_argument("cards")
    c.set_defaults(func=check)
    f = sub.add_parser("finalize")
    f.add_argument("cards")
    f.add_argument("out")
    f.add_argument("--deck", required=True)
    f.set_defaults(func=finalize)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
