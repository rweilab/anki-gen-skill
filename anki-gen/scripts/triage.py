#!/usr/bin/env python3
"""Choose the smallest review set that still answers the questions worth asking.

WHY THIS EXISTS
---------------
Reviewing every card does not scale and never did. Asked to adjudicate a 55-card deck, the
one real reviewer stopped after nine cards -- and the edits they did propose generalised to
the whole deck anyway, so the remaining forty-six bought nothing.

WHY IT IS SMALL, AND WHY IT IS SHAPED THIS WAY
----------------------------------------------
The set is chosen by AXIS, not by card, because the questions a reviewer can answer are
per-axis and one card usually answers one axis for a whole family of cards:

  RISK     "is anything broken?"    one exemplar per flag PATTERN, not per instance
  FORMAT   "does it read right?"    one per card kind (layer x cloze) the build emits
  BREADTH  "is the coverage right?" one per topic, preferring that topic's tier-zero card
  DEPTH    "what else is in here?"  further picks, only with --per-topic > 1

A previous version took every flagged card plus every tier-zero card plus one per topic,
which on a real 61-card deck spent 25 slots (40% of the deck) and still never showed a
Procedure card: tier-zero and the per-topic sample were buying the same thing twice, and
nothing sampled by kind. This version shows 12 cards (19%), covers all four kinds and 12 of
14 topics, and reports exactly what it did not show so that a SECOND round can be targeted
at the gaps instead of re-reading everything.

OUTPUT
------
review_plan.json, fed to `review_server.py --plan`, which renders just these cards and
labels each one with the axis it serves, so the reviewer knows what question it is for.

    {"cards_json": ..., "total": 61, "selected": 12, "note": "...",
     "second_round": {"topics_not_shown": [...], "kinds_not_shown": [...],
                      "flag_patterns_not_shown": [...]},
     "entries": [{"i": 5, "n": 5, "hash": ..., "topic": ..., "layer": ...,
                  "kind": "risk|format|breadth|depth", "reasons": [...]}]}

`i` and `n` are the 1-based card number in cards.json -- the numbering validate_cards,
roi_report and `--show N` all use. Cards are addressed by topic+hash everywhere else; the
number is a display convenience, and any insert shifts it.

    python3 triage.py cards.json
    python3 triage.py cards.json --per-topic 2 --max 30 -o review_plan.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cardid import card_hash, load_cards                       # noqa: E402
from validate_cards import TIER_ZERO, exact_duplicate_pairs, findings   # noqa: E402

DEFAULT_PER_TOPIC = 1


def is_tier_zero(c: dict) -> bool:
    """The field, or (for older cards) the phrase in the front."""
    return bool(c.get("tier_zero")) or bool(TIER_ZERO.search(str(c.get("front", ""))))


def _short(msg: str) -> str:
    """Drop the `card 7: 'front...' -- ` prefix the validator puts on every line.

    The reviewer is looking at the card; repeating its number and opening words
    only pushes the reason itself off the line.
    """
    return msg.split(" -- ", 1)[1] if " -- " in msg else msg


def flagged_reasons(cards: list[dict]) -> dict[int, list[str]]:
    """card number -> the reasons the validators distrust it. Info lines excluded.

    Exact normalized duplicates are surfaced here; soft front/answer similarity is
    intentionally not part of the default triage path.
    """
    out: dict[int, list[str]] = {}
    for i, sev, msg in findings(cards):
        if i == 0 or sev == "info":
            continue
        out.setdefault(i, []).append(_short(msg))

    for i, j in exact_duplicate_pairs(cards):
        for a, b in ((i, j), (j, i)):
            out.setdefault(a, []).append(f"exact duplicate of card {b}")
    return out


def spread(idxs: list[int], k: int) -> list[int]:
    """k of these indices, evenly spread, deterministically.

    Positional spread rather than "the first k": taking each topic's leading cards
    would sample the same part of every topic, which is exactly the bias a
    stratified sample exists to avoid. For k=1 this is the middle card.
    """
    n = len(idxs)
    if k >= n:
        return list(idxs)
    if k <= 0:
        return []
    return [idxs[min(n - 1, max(0, round((j + 0.5) * n / k - 0.5)))]
            for j in range(k)]


# ------------------------------------------------------------------ selection
# The set is chosen by AXIS, not by card. Four questions the human is there to answer,
# and the cheapest cards that can answer each:
#
#   RISK     "is anything broken?"    ONE exemplar per flag PATTERN. Six near-duplicate
#                                     pairs are one pattern: showing six cards spends six
#                                     slots on one question and answers it no better.
#   FORMAT   "does it read right?"    one per card kind (layer x cloze). A kind missing
#                                     from the sample is invisible -- the previous default
#                                     spent 25 of 61 cards and never showed a Procedure one.
#   BREADTH  "is the coverage right?" one per topic, preferring that topic's tier-zero card,
#                                     which answers the coverage question and "did the
#                                     concept framing work" in the same slot. The previous
#                                     default spent TWO slots per topic on exactly this.
#   DEPTH    "what else is in here?"  further picks per topic, only when --per-topic > 1.
#
# When --max bites, RISK and FORMAT are never trimmed (cheap, structural); BREADTH then
# DEPTH give way. Everything withheld is reported, because a silently small sample reads
# as "there was nothing else to look at" -- and because the withheld list is what makes a
# second, targeted round possible.
DEFAULT_MAX = 12


def kind_label(layer: str, cloze: bool) -> str:
    return f"{'cloze' if cloze else 'basic'} {layer or '?'}"


def stratum_of(c: dict) -> str:
    """A deck-authored sub-kind, if the deck chose to declare one.

    Triage never interprets this: it groups by it and counts it. A deck that cares about
    sub-kinds (a course with several problem "shapes", say) names them; a deck that does not
    leaves the field empty and nothing changes. The taxonomy is the deck's, not the tool's.
    """
    return str(c.get("stratum") or "").strip()


def reason_type(reason: str) -> str:
    """The *pattern* a flag belongs to, so exemplars can be de-duplicated by it.

    "cards 12 and 13 fronts 88% similar" and "cards 21 and 25 fronts 96% similar" are one
    defect; the reviewer needs to see one of them, not every instance.
    """
    r = " ".join(reason.split())
    if r.startswith("near-duplicate front"):
        return "near-duplicate fronts"
    for cut in (" (", " '", ";", ":", " --"):
        i = r.find(cut)
        if i > 8:
            r = r[:i]
    return r[:60]


def select(cards: list[dict], per_topic: int, max_total: int):
    """Return (entries, stats) -- see the axis table above for what each entry is for."""
    flagged = flagged_reasons(cards)
    media_ids = [i for i, c in enumerate(cards, 1) if c.get("media")]
    tz = {i for i, c in enumerate(cards, 1) if is_tier_zero(c)}
    topic_of = {i: str(c.get("topic") or "untopiced") for i, c in enumerate(cards, 1)}
    by_topic: dict[str, list[int]] = defaultdict(list)
    by_kind: dict[tuple, list[int]] = defaultdict(list)
    for i, c in enumerate(cards, 1):
        by_topic[topic_of[i]].append(i)
        # The format axis is keyed by stratum as well as layer/cloze, so a deck-authored
        # sub-kind gets its own slot. Keying on (layer, cloze) alone collapses every
        # "Shape A"/"Shape B" into one Procedure kind: they are then *reported* as "0 of 3
        # shown" forever while nothing is able to act on it, which reads as a broken report
        # rather than a missing slot. A card with no stratum keys on "", so a deck that
        # declares none selects exactly what it did before.
        by_kind[(str(c.get("layer", "")), bool(c.get("cloze")), stratum_of(c))].append(i)
    topics = sorted(by_topic, key=lambda t: (-len(by_topic[t]), t))
    kinds = sorted(by_kind, key=lambda k: (-len(by_kind[k]), str(k)))

    chosen: dict[int, tuple[str, str]] = {}
    pattern_of: dict[int, str] = {}          # risk picks: which pattern they stand for

    def take(i: int, axis: str, why: str) -> None:
        chosen.setdefault(i, (axis, why))

    def taken_in_topic(t: str) -> bool:
        return any(topic_of[i] == t for i in chosen)

    # RISK -- one exemplar per pattern, preferring a topic nothing has covered yet.
    patterns: dict[str, list[int]] = defaultdict(list)
    for i, reasons in flagged.items():
        for r in reasons:
            patterns[reason_type(r)].append(i)
    for pattern in sorted(patterns, key=lambda p: (-len(set(patterns[p])), p)):
        members = sorted(set(patterns[pattern]),
                         key=lambda i: (taken_in_topic(topic_of[i]), i))
        pick = members[0]
        text = next((r for r in flagged[pick] if reason_type(r) == pattern), pattern)
        more = f"  (+{len(members) - 1} more like it)" if len(members) > 1 else ""
        take(pick, "risk", f"flag pattern: {text}{more}")
        pattern_of[pick] = pattern

    # FORMAT -- one per kind, preferring a card that is NOT flagged: a broken exemplar says
    # less about what the format normally looks like.
    for kind in kinds:
        cands = sorted(by_kind[kind],
                       key=lambda i: (i in flagged, taken_in_topic(topic_of[i]), i))
        base = f"{'cloze' if kind[1] else 'basic'} {kind[0] or '?'}"
        label = f"{base} · {kind[2]}" if kind[2] else base
        take(cands[0], "format",
             f"format: the {label} kind" + (f" (one of {len(cands)})" if len(cands) > 1 else ""))

    # MEDIA -- a bounded cross-section of image cards. Every image is worth a
    # human look, but a 100-image deck must not become a 100-card review. The
    # sample scales with the count, is never trimmed by --max, and the rest are
    # reported as unaudited. At least three (or all, if fewer) are shown.
    if media_ids:
        want = max(3, min(8, math.ceil(math.sqrt(len(media_ids)))))
        ordered = ([i for i in media_ids if i not in chosen]
                   + [i for i in media_ids if i in chosen])
        for i in spread(ordered, want):
            take(i, "media", "image card — check the figure")

    # BREADTH -- one per topic, and the topic's tier-zero card when it has one. A topic the
    # risk or format axes already put a card in is SKIPPED: spending a second slot on it buys
    # no new domain coverage, and that slot is better spent on a topic with none (with
    # per_topic > 1 the depth pass below is what goes back for the second card).
    for t in topics:
        cands = [i for i in by_topic[t] if i not in chosen]
        if not cands or (taken_in_topic(t) and per_topic <= 1):
            continue
        anchors = [i for i in cands if i in tz]
        pick = anchors[0] if anchors else cands[len(cands) // 2]
        take(pick, "breadth",
             "anchor: this topic's tier-zero card (the concept the rest hang from)"
             if pick in tz else f"breadth: a typical card in {t}")

    # DEPTH -- only if more than one per topic was asked for.
    for t in topics:
        cands = [i for i in by_topic[t] if i not in chosen]
        for i in spread(cands, max(0, per_topic - 1)):
            take(i, "depth", f"depth: another card from {t}")

    priority = {"risk": 0, "format": 1, "media": 2, "breadth": 3, "depth": 4}
    entries, withheld = [], []
    for i, (axis, why) in sorted(chosen.items(), key=lambda kv: (priority[kv[1][0]], kv[0])):
        if len(entries) >= max_total and axis not in ("risk", "format", "media"):
            withheld.append((i, axis, why))
            continue
        c = cards[i - 1]
        entries.append({
            "i": i, "n": i,
            "hash": card_hash(c),
            "topic": topic_of[i],
            "layer": str(c.get("layer", "")),
            "stratum": stratum_of(c),
            "kc": str(c.get("kc") or ""),
            "kind": axis,               # risk | format | breadth | depth
            "reasons": [why],
        })

    shown_kinds = {(str(cards[e["i"] - 1].get("layer", "")), bool(cards[e["i"] - 1].get("cloze")),
                    stratum_of(cards[e["i"] - 1])) for e in entries}
    shown_topics = {e["topic"] for e in entries}
    shown_ids = {e["i"] for e in entries}
    media_shown = [i for i in media_ids if i in shown_ids]
    shown_patterns = {pattern_of[e["i"]] for e in entries if e["kind"] == "risk"}

    # "total vs shown" per stratum, rather than a list of kinds that were not shown: the
    # format axis takes one card per kind and is never trimmed, so a kinds-not-shown list is
    # empty by construction and reads as "nothing missing" whatever the deck actually holds.
    # "3 exist, 1 shown" is legible on its own and needs no knowledge of the subject.
    any_stratum = any(stratum_of(c) for c in cards)
    def stratum_label(c):
        base = kind_label(str(c.get("layer", "")), bool(c.get("cloze")))
        s = stratum_of(c)
        return f"{base} · {s}" if (any_stratum and s) else base
    strata: dict[str, dict] = {}
    for c in cards:
        e = strata.setdefault(stratum_label(c), {"total": 0, "shown": 0})
        e["total"] += 1
    for e in entries:
        strata[stratum_label(cards[e["i"] - 1])]["shown"] += 1

    # What the budget held back, grouped so forty depth cards read as one line.
    held: dict[tuple, dict] = {}
    for i, axis, why in withheld:
        what = why.split(": ", 1)[-1].split(" (")[0]
        g = held.setdefault((axis, what), {"cards": []})
        g["cards"].append(i)
    stats = {
        "total": len(cards),
        "kinds_total": len(kinds), "kinds_shown": len(shown_kinds),
        "topics_total": len(topics), "topics_shown": len(shown_topics),
        "patterns_total": len(patterns), "patterns_shown": len(shown_patterns),
        "media_total": len(media_ids), "media_shown": len(media_shown),
        "flagged_total": len(flagged),
        "withheld": withheld,
        "strata": strata,
        "withheld_groups": [
            {"axis": a, "what": w, "cards": g["cards"]} for (a, w), g in sorted(held.items())
        ],
        "second_round": {
            "topics_not_shown": [t for t in topics if t not in shown_topics],
            "strata_under_shown": [k for k, v in strata.items()
                                   if v["total"] > v["shown"] and v["total"] > 1],
            "flag_patterns_not_shown": sorted(set(patterns) - shown_patterns),
            "media_not_shown": [i for i in media_ids if i not in shown_ids],
        },
    }
    return entries, stats


def build_plan(cards_json: str, cards: list[dict], entries, stats,
               per_topic: int, max_total: int) -> dict:
    n = stats["total"]
    if not entries:
        note = ("nothing to review: the deck is empty" if n == 0 else
                f"0 of {n} selected — --max {max_total} leaves no room for any card")
    else:
        pct = len(entries) * 100 // max(n, 1)
        note = (f"{len(entries)} of {n} selected ({pct}% of the deck) — covering "
                f"{stats['kinds_shown']}/{stats['kinds_total']} card kinds, "
                f"{stats['topics_shown']}/{stats['topics_total']} topics, "
                f"{stats['patterns_shown']}/{stats['patterns_total']} flag patterns")
        if stats.get("media_total"):
            note += (f"; images {stats['media_shown']}/{stats['media_total']}")
        if stats["flagged_total"] == 0:
            note += ". Nothing is flagged, so the questionable-card axis is empty"
        if stats["withheld"]:
            note += (f". {len(stats['withheld'])} more card(s) were available and are held "
                     f"back by --max (listed below, grouped) — raise it for depth, or cover "
                     f"them in a second round")
    return {
        "cards_json": cards_json,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "per_topic": per_topic,
        "max": max_total,
        "total": n,
        "selected": len(entries),
        "all_selected": len(entries) == n,
        "media_total": stats.get("media_total", 0),
        "media_shown": stats.get("media_shown", 0),
        "note": note,
        "strata": stats["strata"],
        "withheld_groups": stats["withheld_groups"],
        "second_round": stats["second_round"],
        "entries": entries,
    }


def report(plan: dict, cards: list[dict], out: Path) -> None:
    print(f"REVIEW TRIAGE — {plan['note']}")
    print("=" * 78)
    AXIS = [
        ("risk", "IS ANYTHING BROKEN?  one card per flag pattern, not per instance"),
        ("format", "DOES IT READ RIGHT?  one card per kind the build emits"),
        ("breadth", "IS THE COVERAGE RIGHT?  one card per topic"),
        ("media", "IMAGES — check the figure"),
        ("depth", "WHAT ELSE IS IN THE TOPIC?  (only with --per-topic > 1)"),
    ]
    for axis, blurb in AXIS:
        rows = [e for e in plan["entries"] if e["kind"] == axis]
        if not rows:
            continue
        print(f"\n{blurb}")
        for e in rows:
            print(f"  {e['i']:>3}  {e['topic'][:26]:<27}{e['layer']:<11}"
                  f"{e['reasons'][0].split(': ', 1)[-1][:62]}")
    if plan.get("withheld_groups"):
        print("\nHELD BACK BY THE BUDGET")
        for g in plan["withheld_groups"]:
            print(f"  {g['axis']:<8} {g['what'][:44]:<45}{len(g['cards'])} card(s)"
                  f"  ({', '.join(str(c) for c in g['cards'][:8])}"
                  f"{', …' if len(g['cards']) > 8 else ''})")
    if plan.get("strata"):
        print("\nWHAT THE SAMPLE COVERS, BY STRATUM")
        for label, v in sorted(plan["strata"].items()):
            if v["total"] > 1:
                print(f"  {label[:34]:<35}{v['shown']} of {v['total']} shown")
    sr = plan.get("second_round") or {}
    if sr.get("topics_not_shown") or sr.get("flag_patterns_not_shown"):
        print("\nNOT SHOWN — what a second, targeted round should cover:")
        for label, key in (("flags", "flag_patterns_not_shown"), ("topics", "topics_not_shown")):
            if sr.get(key):
                print(f"  {label + ':':<9}{', '.join(sr[key])}")
    print(f"\n  plan written to {out}")
    print(f"  review it: python3 {Path(__file__).with_name('review_server.py')} \\")
    print(f"                 --cards {plan['cards_json']} --plan {out}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Select the review subset for a deck and write review_plan.json.")
    ap.add_argument("cards_json")
    ap.add_argument("-o", "--out", default="review_plan.json",
                    help="plan file to write (default: review_plan.json)")
    ap.add_argument("--per-topic", type=int, default=DEFAULT_PER_TOPIC, metavar="N",
                    help=f"cards per topic beyond the first, for depth "
                         f"(default {DEFAULT_PER_TOPIC} — breadth only)")
    ap.add_argument("--max", type=int, default=DEFAULT_MAX, metavar="M",
                    help=f"cap on the total review set. The risk and format axes are "
                         f"never trimmed to meet it; breadth and depth are (default "
                         f"{DEFAULT_MAX})")
    ap.add_argument("--json", action="store_true", help="print the plan, write nothing")
    args = ap.parse_args()

    cards = load_cards(args.cards_json)
    if not isinstance(cards, list) or not cards:
        print("no cards to triage", file=sys.stderr)
        return 2
    if args.per_topic < 0 or args.max < 0:
        print("--per-topic and --max must not be negative", file=sys.stderr)
        return 2

    entries, stats = select(cards, args.per_topic, args.max)
    plan = build_plan(args.cards_json, cards, entries, stats, args.per_topic, args.max)

    if args.json:
        print(json.dumps(plan, indent=2))
        return 0

    out = Path(args.out)
    out.write_text(json.dumps(plan, indent=2) + "\n")
    report(plan, cards, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
