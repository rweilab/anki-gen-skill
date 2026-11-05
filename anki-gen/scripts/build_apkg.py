#!/usr/bin/env python3
"""Build .apkg from cards.jsonl, with optional merge into an existing deck.

Text handling is delegated to render.py, which converts markdown to HTML and
rewrites LaTeX to the delimiters Anki's bundled MathJax actually understands.
There is no SVG step and no LaTeX rendering dependency -- see render.py for why.

The deck is written through Anki's own library (build_native.py): it creates the
notetypes and the cards itself, so the collection it exports always has a schema
Anki accepts. An earlier version also carried a second, genanki-based writer as a
fallback; it was removed in full rather than kept for reference, because it could
not produce a cloze deck that Anki 26 opens (see card-writing.md § cloze) and it made `genanki` a
hard import for every caller of this module, including `build_native`.
"""
import argparse
import hashlib
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Identity lives in cardid.py, so the builder, the review server and triage.py all
# agree on what a card *is* by construction rather than by convention. Re-exported
# here because build_native.py calls build_apkg.card_hash.
from cardid import card_hash, load_cards   # noqa: E402,F401
from schema_types import Card              # noqa: E402

# L3 and Procedure share the last rank: neither is reliably "easier", so keep
# them in the order the author wrote them.
LAYER_ORDER = {"L1": 0, "L2": 1}
SOURCE_BIAS = 2.0
ANCHOR_BOOST = 2.0
REPEAT_PENALTY = 0.35


def _tag_key(value) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")


def _same_stem(a: str, b: str) -> bool:
    if a == b or a.rstrip("s") == b.rstrip("s"):
        return True
    return len(a) >= 6 and len(b) >= 6 and a[:6] == b[:6]


def normalize_objects(cards: list[Card]) -> list[Card]:
    """Keep broad, cross-topic buckets; drop topic/subtopic and one-topic tags.

    The writer's object list is deliberately a suggestion. A topic already tags
    every card, so `heap` under Memory Management or `queue` under Queues adds
    nothing. A tag earns its place only if it recurs across topics.
    """
    spans: dict[str, set[str]] = {}
    counts: dict[str, int] = {}
    for c in cards:
        topic = _tag_key(c.get("topic", ""))
        raw = c.get("objects") or []
        if isinstance(raw, str):
            raw = [raw]
        for obj in raw:
            key = _tag_key(obj)
            if key:
                spans.setdefault(key, set()).add(topic)
                counts[key] = counts.get(key, 0) + 1

    # A tag must span a meaningful share of the deck's topics, not just two
    # cards in neighbouring chapters. The share scales with topic count.
    topic_keys = {_tag_key(c.get("topic", "")) for c in cards}
    topic_words = {word for key in topic_keys for word in key.split("_")}
    topic_count = len(topic_keys)
    min_topics = max(2, (topic_count + 3) // 4)
    ranked = sorted(spans, key=lambda k: (len(spans[k]), counts[k]),
                    reverse=True)
    allowed = {k for k in ranked if len(spans[k]) >= min_topics}
    allowed = set(sorted(allowed, key=lambda k: (len(spans[k]), counts[k]),
                         reverse=True)[:max(3, topic_count // 2)])
    out = []
    for c in cards:
        topic = _tag_key(c.get("topic", ""))
        raw = c.get("objects") or []
        if isinstance(raw, str):
            raw = [raw]
        keep = []
        for obj in raw:
            key = _tag_key(obj)
            if not key or key in keep:
                continue
            if (key == topic or key in topic.split("_")
                    or any(_same_stem(key, word) for word in topic_words)):
                continue
            if (key not in allowed or len(spans.get(key, ())) < 2
                    or counts.get(key, 0) < 2):
                continue
            keep.append(key)
        keep.sort(key=lambda k: (len(spans[k]), counts[k]), reverse=True)
        out.append({**c, "objects": keep[:2]})
    return out


def study_order(cards: list[Card], depths: dict[str, int] | None = None) -> list[Card]:
    """Order cards by topic, prerequisite depth, tier-zero, then layer.

    Small decks stay grouped. Larger decks interleave topics: each topic's queue
    is already dependency-ordered, and the seeded RNG makes a rebuild reproducible.
    Ordering is within a topic; a cross-topic prerequisite is recorded but not
    enforced by the interleaver.
    """
    topics: dict[str, list[dict]] = {}
    for c in cards:
        topics.setdefault(str(c.get("topic", "")), []).append(c)
    depths = depths or {}
    topic_order = {name: i for i, name in enumerate(topics)}

    def order_key(c: dict) -> tuple:
        kc = str(c.get("kc") or "")
        return (topic_order[str(c.get("topic", ""))],
                int(depths.get(kc, 0)),
                0 if c.get("tier_zero") else 1,
                LAYER_ORDER.get(str(c.get("layer", "")), 2))

    if len(topics) < 3 or len(cards) / len(topics) < 6:
        return sorted(cards, key=order_key)
    names = list(topics)
    queues = {name: sorted(group, key=order_key) for name, group in topics.items()}

    seed = hashlib.sha256(
        "|".join(card_hash(c) for c in cards).encode()).digest()
    rng = random.Random(seed)
    max_run = max(2, min(4, len(names) // 3))
    out, last, run = [], None, 0
    while len(out) < len(cards):
        choices = [n for n in names if queues[n] and
                   not (n == last and run >= max_run)]
        if not choices:
            choices = [n for n in names if queues[n]]
        weights = []
        for i, name in enumerate(names):
            if name not in choices:
                weights.append(0.0)
                continue
            weight = float(len(queues[name]))
            weight *= 1.0 + (len(names) - i) / (len(names) * SOURCE_BIAS)
            if queues[name][0].get("tier_zero"):
                weight *= ANCHOR_BOOST
            if name == last:
                weight *= REPEAT_PENALTY
            weights.append(weight)
        pick = rng.random() * sum(weights)
        chosen = choices[-1]
        total = 0.0
        for name, weight in zip(names, weights):
            if not weight:
                continue
            total += weight
            if pick <= total:
                chosen = name
                break
        out.append(queues[chosen].pop(0))
        if chosen == last:
            run += 1
        else:
            last, run = chosen, 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cards_json")
    ap.add_argument("output_apkg")
    ap.add_argument("--merge-existing")
    ap.add_argument("--kcs", default=None,
                    help="optional kcs.md; orders cards by prerequisite depth")
    # Required, not defaulted. A silent "Default" put a real, valid deck somewhere nobody
    # would ever look for it again -- and the user is the one who knows where it belongs.
    ap.add_argument("--deck-name", required=True,
                    help="the deck name; ::-separated segments make a nested tree "
                         "(e.g. SCHOOL::CIRCUITS::OPAMPS)")
    ap.add_argument("--allow-invalid", action="store_true",
                    help="build despite validate_cards.py errors (diagnosis only)")
    ap.add_argument("--media", action="store_true",
                    help="bundle card media (opt-in; off by default)")
    ap.add_argument("--media-root", default=None,
                    help="root the card media paths are relative to "
                         "(default: the directory holding the cards file)")
    args = ap.parse_args()

    cards = load_cards(args.cards_json)

    depths: dict[str, int] = {}
    if args.kcs:
        from validate_cards import parse_kc_map, requires_depths
        try:
            kc_text = Path(args.kcs).read_text()
        except OSError as e:
            print(f"  ! cannot read --kcs {args.kcs}: {e}", file=sys.stderr)
            return 2
        kcs, _, _, _ = parse_kc_map(kc_text)
        if not kcs:
            print(f"  ! no KC table in {args.kcs}; using source order",
                  file=sys.stderr)
        else:
            depths, cycle = requires_depths(kcs)
            if cycle:
                print(f"  ! KC requires cycle: {' -> '.join(cycle)}; "
                      "using source order", file=sys.stderr)
                depths = {}
    cards = study_order(cards, depths)

    # The build path cannot see a bad front or a leaked delimiter, so the static
    # checks stop it by default. --allow-invalid is for diagnosis, not delivery.
    if not args.allow_invalid:
        from validate_cards import check_cards
        errs, _, _ = check_cards(cards)
        if errs:
            print(f"aborting: {len(errs)} validation error(s) "
                  "(pass --allow-invalid only for diagnosis)", file=sys.stderr)
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
    try:
        from build_native import build_with_anki
    except ImportError:
        print("  ! anki library is required to build decks; run setup.sh or doctor",
              file=sys.stderr)
        return 2
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
