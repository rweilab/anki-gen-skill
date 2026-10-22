#!/usr/bin/env python3
"""ROI / debloat report for cards.json.

The goal is NOT "make cards smaller". Minimum Information Principle over-applied
strips cards until they carry no context, which is its own failure mode. The two
things that actually waste review time are:

  REDUNDANCY     a card whose answer adds nothing a sibling card does not already
                 give. Paying for it every review is pure overhead.

  BAD BUNDLING   several INDEPENDENT facts sharing one schedule. You know 3 of 4
                 and still fail the card, and the fix you make is aimed at the one
                 you missed. Independent facts want independent intervals.

What must be preserved is the opposite case -- items that always transfer together,
like the four packing properties of one structure. Those belong in one card, and
splitting them multiplies review count for no gain. Splitting is only correct where
the items are independently examinable.

This script measures the mechanical signals. It does not decide; see the DEBLOATER
prompt in SKILL.md, which turns these numbers into accept/reject decisions.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from cardid import load_cards
from validate_cards import similar_answer_pairs

# Exam weights are deliberately NOT baked in. A hardcoded table only ever matches the
# one course it was written for: keyed on "Ch N" in `source`, it sent every card of a
# deck whose citations read differently into "other", and the whole coverage section
# printed dead output. Weighting is now optional (see --exam-weights) and its absence
# means "no verdict", never "0%". Grouping is by `topic`, which every card already
# carries and which is already the deck's organising axis.

# Items that always transfer together -- do NOT flag these for splitting.
CO_CHUNKS = re.compile(r"\b(SC|FCC|BCC|HCP)\b.*\b(SC|FCC|BCC|HCP)\b", re.S)

BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.M)
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.M)
HEADERISH = re.compile(r"^\s*\|[\s:|-]+\|\s*$", re.M)


def strip_math(t: str) -> str:
    return re.sub(r"\$[^$]+\$", " ⟨m⟩ ", t)


def items_in_back(back: str) -> int:
    """Count independent content units: bullets, table rows, and inline enumerations."""
    b = strip_math(back)
    b = HEADERISH.sub("", b)
    bullets = len(BULLET.findall(b))
    rows = max(0, len(TABLE_ROW.findall(b)) - 1)      # minus the header row
    # inline enumerations: "A, B, C and D" inside a bolded lead line
    enum = 0
    for m in re.finditer(r"\*\*([^*\n]{10,})", b):
        seg = m.group(1)
        if seg.count(",") >= 2 and re.search(r"\band\b|/|、", seg):
            enum = max(enum, seg.count(",") + 1)
    return max(bullets, rows, enum)


def always_together(front: str, back: str) -> bool:
    """True when the card's items are one concept -- splitting would lose context."""
    blob = front + " " + back
    return bool(CO_CHUNKS.search(blob)) or bool(
        re.search(r"\b(four|4)\s+(components|vertices|criteria|properties)\b", blob, re.I))


def redundancy(cards) -> list[tuple]:
    """Pairs where one answer largely subsumes the other."""
    out = []
    backs = [strip_math(c["back"]) for c in cards]
    for i in range(len(cards)):
        for j in range(i + 1, len(cards)):
            a, b = backs[i].lower(), backs[j].lower()
            if abs(len(a) - len(b)) > 400:
                continue
            r = SequenceMatcher(None, a, b).ratio()
            if r > 0.88:
                out.append((i + 1, j + 1, round(r, 3)))
    return out


def interference(cards) -> list[tuple]:
    """Near-identical fronts: siblings that compete at the point of retrieval."""
    out = []
    for i in range(len(cards)):
        for j in range(i + 1, len(cards)):
            fi = re.sub(r"[^a-z ]", " ", strip_math(cards[i]["front"]).lower())
            fj = re.sub(r"[^a-z ]", " ", strip_math(cards[j]["front"]).lower())
            r = SequenceMatcher(None, fi, fj).ratio()
            if r > 0.72:
                out.append((i + 1, j + 1, round(r, 3)))
    return out


def repeated_content(cards) -> list[tuple]:
    """Surface-level comparison MISSES restatement. This catches the common cases.

    Two cards can carry the same fact in different words and never register as
    near-duplicates. The reliable proxies for "someone already said this":
      * the same equation, appearing in 2+ cards
      * the same distinctive multi-word phrase, appearing in 3+ cards

    Neither proves redundancy -- an equation repeated in a worked example and a
    summary card can be right. They are flags for the semantic pass, which is
    the part that actually decides. See the DEBLOATER PROMPT.
    """
    eqs: dict[str, list[int]] = defaultdict(list)
    phrases: dict[str, set] = defaultdict(set)
    for i, c in enumerate(cards, 1):
        for m in re.finditer(r"\$\$?(.+?)\$\$?", c["back"]):
            e = re.sub(r"\s+", "", m.group(1))
            if len(e) > 8:
                eqs[e].append(i)
        for m in re.finditer(r"[a-z][a-z ]{28,50}",
                             re.sub(r"[^a-z ]", " ", strip_math(c["back"]).lower())):
            phrases[m.group(0).strip()].add(i)

    out = []
    for e, who in eqs.items():
        if len(who) > 1:
            out.append(("equation", e[:60], sorted(set(who))))
    for ph, who in sorted(phrases.items(), key=lambda kv: -len(kv[1])):
        if len(who) >= 3:
            out.append(("phrase", ph, sorted(who)))
    return out


def cost_fn(cards) -> list[tuple]:
    """Read-time proxy. Back length is real review cost, every single review."""
    rows = []
    for i, c in enumerate(cards, 1):
        rows.append((i, len(c["back"].split()), len(c["front"].split())))
    return sorted(rows, key=lambda r: -r[1])


def topic_of(c) -> str:
    """Group by `topic`, not by a regex over `source`.

    `topic` is required on every card and is already what the deck is organised by.
    `source` is a citation string whose shape varies by course, so parsing it was
    both fragile and the reason coverage went dead on a real deck.
    """
    return str(c.get("topic") or "untopiced")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cards_json")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--exam-weights", default=None,
                    help="JSON file mapping topic -> weight fraction (e.g. "
                         '{"Fourier": 0.3}). Optional: without it the coverage '
                         "section prints counts and no verdict at all.")
    ap.add_argument("--show", type=int, default=None, metavar="N",
                    help="print card N's full front and back, then exit. Lets the "
                         "deblater cite a card without pulling every card's text "
                         "back into the conversation.")
    args = ap.parse_args()

    cards = load_cards(args.cards_json)
    n = len(cards)

    if args.show is not None:
        if not 1 <= args.show <= n:
            print(f"card {args.show} is out of range (1..{n})", file=sys.stderr)
            return 2
        c = cards[args.show - 1]
        print(f"card {args.show}  layer={c.get('layer', '?')}  "
              f"topic={c.get('topic', '?')}  "
              f"source={c.get('source') or c.get('source_ref', '')}")
        print(f"\nFRONT\n{c.get('front', '')}\n\nBACK\n{c.get('back', '')}")
        return 0

    weights: dict[str, float] = {}
    if args.exam_weights:
        weights = json.loads(Path(args.exam_weights).read_text())

    # ---- coverage by topic (weighted only if the caller supplied weights) ----
    ch = Counter(topic_of(c) for c in cards)
    media_ch = Counter(topic_of(c) for c in cards if c.get("media"))
    coverage = []
    for k in sorted(ch, key=lambda t: -ch[t]):
        got = ch[k] / n
        want = weights.get(k)
        coverage.append((k, ch[k], got, want, (got / want) if want else None,
                         media_ch[k]))

    # ---- bundle candidates --------------------------------------------------
    bundles, keep_chunks = [], []
    for i, c in enumerate(cards, 1):
        items = items_in_back(c["back"])
        if items < 3:
            continue
        (keep_chunks if always_together(c["front"], c["back"]) else bundles).append(
            (i, items, c["topic"]))

    # B5: these thresholds deliberately differ from validate_cards.py, which flags
    # near-identical FRONTS (>0.85) as a defect. `interference` here is a softer
    # >0.72 signal that two fronts COMPETE for the same retrieval cue. Different
    # questions, so different bars -- the two are not expected to agree on a given
    # pair, and one firing without the other is not a bug.
    red = redundancy(cards)
    inter = interference(cards)
    overlap = similar_answer_pairs(cards)
    cost = cost_fn(cards)
    rep = repeated_content(cards)

    # ---- anchors: cards other cards depend on ------------------------------
    # A card that defines a term used elsewhere is high ROI: low review cost,
    # unlocks several siblings.
    # B2: the `tier_zero` field IS the anchor marker -- the writer sets it, and the
    # phrase heuristic alone missed every real anchor on a deck that had nine of
    # them: it printed ANCHORS (0) and then told the reader to protect nothing.
    # Anchor-ness is a field, not a guess about wording.
    anchors = []
    for i, c in enumerate(cards, 1):
        if c.get("tier_zero") or re.search(
                r"\b(is defined|are the four|what is a|distinguishes|means)\b",
                c["front"], re.I):
            anchors.append((i, c["front"][:70]))

    if args.json:
        print(json.dumps({
            "cards": n,
            "coverage": coverage,
            "bundle_candidates": bundles,
            "keep_together": keep_chunks,
            "redundant_pairs": red,
            "interference_pairs": inter,
            "answer_overlap": overlap,
            "restatement": [(k,w,wh) for k,w,wh in rep],
            "costliest": cost[:12],
            "anchors": anchors,
        }, indent=2, default=str))
        return 0

    print(f"ROI / DEBLOAT REPORT — {n} cards")
    print("=" * 78)

    weighted = bool(weights)
    print("\nCOVERAGE BY TOPIC" + (" (weighted)" if weighted else ""))
    if not weighted:
        # State plainly what this section is NOT doing. The old hardcoded table,
        # when it matched no card, printed a screenful of "unscored" rows that read
        # like findings.
        print("  no exam weights supplied — counts only, no coverage verdict.")
        print("  pass --exam-weights FILE to compare against an expected weight.")
    hdr = f"  {'topic':<28}{'cards':>6}{'share':>8}{'media':>7}"
    if weighted:
        hdr += f"{'weight':>9}   verdict"
    print(hdr)
    for k, cnt, got, want, ratio, media in coverage:
        line = f"  {k[:27]:<28}{cnt:>6}{got*100:>7.0f}%{media:>7}"
        if weighted:
            if want is None:
                verdict = "no weight given"
            elif ratio < 0.6:
                verdict = f"UNDER by {1/ratio:.1f}x"
            elif ratio > 1.8:
                verdict = f"OVER by {ratio:.1f}x"
            else:
                verdict = "ok"
            w = f"{want*100:.0f}%" if want else "-"
            line += f"{w:>9}   {verdict}"
        print(line)
    no_media = sorted(k for k in ch if not media_ch[k])
    media_refs = sum(len(c.get("media") or []) for c in cards)
    media_unique = len({m.get("file") if isinstance(m, dict) else str(m)
                        for c in cards for m in (c.get("media") or [])})
    print(f"\nMEDIA: {sum(media_ch.values())}/{n} cards, {media_refs} refs / "
          f"{media_unique} unique files"
          + (f"; topics without images: {', '.join(no_media)}" if no_media else ""))

    # B3: a flat count is unusable at volume -- one real deck produced 42 restatement
    # and 34 split flags on a deck that was already correct, and triaging that noise
    # cost more than the report saved. Cap hard, and say how many were withheld.
    CAP = 8
    print(f"\nRESTATEMENT FLAGS — {len(rep)} total (candidates, not verdicts)")
    for kind, what, who in rep[:CAP]:
        print(f"  {kind:<9} cards {who}  {what!r}")
    if len(rep) > CAP:
        print(f"  ... {len(rep) - CAP} more suppressed. Most repeats are REQUIRED "
              f"duplication — a glossary repeats on every card that uses it, and "
              f"worked examples echo their setup — so check by value ownership "
              f"(which card owns this fact?), not by count.")
    if not rep:
        print("  none")

    print(f"\nREDUNDANCY (answer subsumed by a sibling) — {len(red)} pair(s)")
    for i, j, r in red[:15]:
        print(f"  card {i} ~ card {j}  ({r})")

    print(f"\nINTERFERENCE (near-identical fronts compete) — {len(inter)} pair(s)")
    for i, j, r in inter[:15]:
        print(f"  card {i} ~ card {j}  ({r})")

    print(f"\nANSWER OVERLAP (same ground; merge or justify a contrast) — {len(overlap)} pair(s)")
    for i, j, r in overlap[:15]:
        print(f"  card {i} ~ card {j}  ({r:.0%})")
    if not overlap:
        print("  none")

    print(f"\nSPLIT CANDIDATES ({len(bundles)}) — independent facts sharing one schedule")
    for i, items, topic in bundles[:CAP]:
        print(f"  card {i:>3}  {items} items  [{topic}]")
    if len(bundles) > CAP:
        print(f"  ... {len(bundles) - CAP} more suppressed. Apply the real test to each: "
              f"does knowing one imply knowing the others? If yes it is a CHUNK and "
              f"splitting only multiplies review count. Only independently examinable "
              f"items are worth splitting.")
    if not bundles:
        print("  none")

    print(f"\nKEEP AS ONE CHUNK ({len(keep_chunks)}) — items transfer together")
    for i, items, topic in keep_chunks[:12]:
        print(f"  card {i:>3}  {items} items  [{topic}]")

    print(f"\nCOSTLIEST BREADS (review time, paid every review)")
    for i, b, f in cost[:8]:
        print(f"  card {i:>3}  back {b:>3}w  front {f:>2}w")

    print(f"\nANCHORS ({len(anchors)}) — cheap cards that unlock siblings; protect these")
    for i, f in anchors[:12]:
        print(f"  card {i:>3}  {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())