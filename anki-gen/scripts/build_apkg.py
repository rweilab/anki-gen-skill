#!/usr/bin/env python3
"""Build .apkg from cards.json, with optional merge into an existing deck.

Text handling is delegated to render.py, which converts markdown to HTML and
rewrites LaTeX to the delimiters Anki's bundled MathJax actually understands.
There is no SVG step and no LaTeX rendering dependency -- see render.py for why.

The deck is written through Anki's own library (build_native.py): it creates the
notetypes and the cards itself, so the collection it exports always has a schema
Anki accepts. An earlier version also carried a second, genanki-based writer as a
fallback; it was removed in full rather than kept for reference, because it could
not produce a cloze deck that Anki 26 opens (see rule 15) and it made `genanki` a
hard import for every caller of this module, including `build_native`.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Identity lives in cardid.py, so the builder, the review server and triage.py all
# agree on what a card *is* by construction rather than by convention. Re-exported
# here because build_native.py calls build_apkg.card_hash.
from cardid import card_hash, load_cards   # noqa: E402,F401

# L3 and Procedure share the last rank: neither is reliably "easier", so keep
# them in the order the author wrote them.
LAYER_ORDER = {"L1": 0, "L2": 1}


def foundation_order(cards: list[dict]) -> list[dict]:
    """Stable soft order: source topic, then tier-zero, then L1/L2/advanced.

    Topic order is first appearance in cards.jsonl, which is the order the
    material was authored in. Ties keep their source order. Anki assigns new-card
    positions in add order, so this becomes the deck's default study order until
    the user changes the deck's New Card Sort Order.
    """
    topic_order: dict[str, int] = {}
    for c in cards:
        topic = str(c.get("topic", ""))
        topic_order.setdefault(topic, len(topic_order))

    return sorted(
        cards,
        key=lambda c: (
            topic_order[str(c.get("topic", ""))],
            0 if c.get("tier_zero") else 1,
            LAYER_ORDER.get(str(c.get("layer", "")), 2),
        ),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cards_json")
    ap.add_argument("output_apkg")
    ap.add_argument("--merge-existing")
    # Required, not defaulted. A silent "Default" put a real, valid deck somewhere nobody
    # would ever look for it again -- and the user is the one who knows where it belongs.
    ap.add_argument("--deck-name", required=True,
                    help="the deck name; ::-separated segments make a nested tree "
                         "(e.g. SCHOOL::CIRCUITS::OPAMPS)")
    ap.add_argument("--strict", action="store_true",
                    help="refuse to build when validate_cards.py reports an error")
    ap.add_argument("--media", action="store_true",
                    help="bundle card media (opt-in; off by default)")
    ap.add_argument("--media-root", default=None,
                    help="root the card media paths are relative to "
                         "(default: the directory holding cards.json)")
    args = ap.parse_args()

    cards = load_cards(args.cards_json)

    # --strict is the gate, not a formality: the deck below is written through a
    # path that cannot see a bad front or a leaked delimiter, so anything the
    # static checks catch has to stop the build here or it ships.
    if args.strict:
        from validate_cards import check_cards
        errs, _, _ = check_cards(cards)
        if errs:
            print(f"aborting (--strict): {len(errs)} validation error(s)",
                  file=sys.stderr)
            for e in errs[:10]:
                print("  -", e, file=sys.stderr)
            if len(errs) > 10:
                print(f"  ... and {len(errs) - 10} more", file=sys.stderr)
            return 1

    # WHERE THE DECK GOES is part of the build, not a trailing fact in a document. The one
    # observed failure of this pipeline was a complete, valid deck written into the hidden
    # scratch directory next to the extraction -- and every gate passed, because every gate
    # checks the deck and the deck was fine. So the destination is checked here, and printed
    # in full afterwards: a bare filename cannot tell the reader whether it is about to be lost.
    # Judge only the part of the path the CALLER named. A path can legitimately sit under a
    # dot-directory it did not choose -- ~/.claude/jobs/..., ~/.local/share/decks/... -- and
    # refusing that would be a false alarm. (It also would have refused this very test run,
    # which is how the first version of this check was caught.)
    out_path = Path(args.output_apkg)
    resolved = out_path.resolve()
    cwd = Path.cwd().resolve()
    try:
        rel = resolved.relative_to(cwd).parts
    except ValueError:                      # outside cwd: judge what was named, not the tree
        rel = resolved.parts[-2:] or resolved.parts
    if set(rel) & {".anki-gen-temp", ".work"}:
        print(f"  ! refusing to write the deck inside the work directory:\n"
              f"      {resolved}\n"
              f"    The .apkg is the deliverable and belongs where the user can find it.\n"
              f"    Pass a path in their cwd (e.g. --out ./Deck.apkg). The work directory\n"
              f"    holds regenerable scratch that is expected to be thrown away.",
              file=sys.stderr)
        return 2
    if any(q.startswith(".") for q in rel[:-1]):
        print(f"  ! note: {resolved}\n"
              f"    is inside a hidden directory beneath the cwd. SKILL.md expects the deck\n"
              f"    in the user's cwd; pass an explicit path if that is really what you want.",
              file=sys.stderr)

    if args.media:
        try:
            import PIL  # noqa: F401
        except ImportError:
            print("  ! images need Pillow: pip install pillow", file=sys.stderr)
            return 2
    from build_native import build_with_anki
    media_root = args.media_root or str(Path(args.cards_json).resolve().parent)
    try:
        info = build_with_anki(cards, str(out_path), args.deck_name,
                               args.merge_existing, media_root, args.media)
    except (ValueError, FileNotFoundError) as e:
        print(f"  ! {e}", file=sys.stderr)
        return 2
    print(f"Built {info['added']} notes, {info['cards']} cards "
          f"incl. {info['cloze_notes']} cloze note(s), "
          f"{out_path.stat().st_size/1024:.1f} KB")
    print(f"  deck: {out_path.resolve()}")
    if info.get("already_present"):
        # Says out loud what "idempotent" means in this run: these cards were
        # already in the merged deck and were left alone, review history intact.
        print(f"  {info['already_present']} card(s) already in "
              f"{args.merge_existing} — skipped, not duplicated")
    if info.get("media_cards"):
        print(f"  {info['media_cards']} card(s) include bundled media")
    if info.get("media_ignored"):
        print(f"  {info['media_ignored']} card(s) name media but were built without "
              f"--media; no images were bundled")
    if info["skipped"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
