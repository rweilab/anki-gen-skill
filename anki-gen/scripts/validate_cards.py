#!/usr/bin/env python3
"""Static checks on cards.json, before anything is built.

Run this every time. Every failure below was a real bug that shipped unnoticed:
the deck still imported fine, it just looked broken on screen.

  1. control-char corruption   LaTeX written in a non-raw Python string
  2. LaTeX delimiter imbalance braces/\\( )/\\[ ] not closed
  3. rendered-output leaks     stray $, literal **, markdown tables/lists
  4. forbidden fronts          computation demands (see FORBIDDEN below)
  5. empty / stub cards
  6. near-duplicate fronts
  7. glossary signal           symbol card without a definitions section (info)
  8. missing provenance        no `source`, or a source with no locator
  9. KC coverage              missing/unknown kc, unresolved requires, 1:1 map
 10. evidence quote           source-dependent quote missing or not in the extract
"""
import argparse
import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cardid import load_cards   # noqa: E402
from render import DERIVED_SOURCES, to_html   # noqa: E402

# Scoped to FRONTS. A back legitimately says "set them equal and solve" as a method
# step, or "convert before you compute". Rejecting those was a false positive that
# trained us to ignore the check.
FORBIDDEN_FRONT = re.compile(
    r"\b(solve|calculate|compute|evaluate|prove|show that|derive)\b"
    r"|find the value|determine the value|what is the value of|what is the result of",
    re.I,
)

CTRL = re.compile(r"[\x07\x08\x09\x0b\x0c\x0d][A-Za-z]")
FRONT_REF = re.compile(
    r"\b(the|this|that)\s+(slide|circuit|figure|diagram|graph|example)|"
    r"slide's example|shown\s+(above|below)", re.I)
SYM = re.compile(r"\\?[A-Za-z]_\{?[A-Za-z0-9]+\}?|\\[A-Za-z]+")


def _tag_key(value) -> str:
    return str(value).strip().lower().replace(" ", "_").replace("&", "and")


# ---------------------------------------------------------------------------
# IMPLICIT COMPUTATION DEMAND
#
# FORBIDDEN_FRONT only catches explicit verbs ("compute X"). The real failure is
# a front that supplies given data and asks for a value OUT -- "What are the atom
# percents?", "What is the correct Q_v?" -- which is unanswerable without doing
# the calculation. That phrasing contains no forbidden verb, so it slipped through
# and produced a deck of unanswerable cards.
#
# Heuristic: a front that carries physical quantities (units, numbers) AND asks
# for a value is a computation prompt.
# ---------------------------------------------------------------------------
QUANTITY = re.compile(
    r"\b(percents?|per\s?cents?|densit(?:y|ies)|values?|numbers?|answers?|results?|"
    r"mole fractions?|Q_v)\b"
    r"|\b(?:at|wt)\s*%|\bat\.%|wt\.%", re.I)
ASKS_VALUE = re.compile(
    # Gerunds like "solving for Q_v" or "working out N" describe the *situation*
    # rather than demanding an output, so they are not value demands on their own.
    r"(what (is|are) the|what would (it|they) be|find the|"
    r"determine the|calculate the|state the (value|numbers?)|"
    r"what value|come out to|should (?:it|they|copper|chromium|the))\b", re.I)
# physical quantities as given data: a number carrying a unit, or an assigned symbol
GIVEN_DATA = re.compile(
    r"\d+(?:\.\d+)?\s*(?:g/cm\^?3|g/m\^?3|g/mol|kg|g\b|eV|nm|°C|K\b|%)"
    r"|\d+\s*×\s*10\^"
    r"|(?:ρ|\\rho|A|Q_v)\s*=",
    re.I)


# comparative questions ("which has the lowest/highest") are recall from a printed
# table; a bare "what percent/value does X have" is a request for a computed number.
COMPARATIVE = re.compile(r"\b(lowest|highest|most|least|largest|smallest|greater|"
                         r"less|above|below|more|fewer|first|last)\b", re.I)

# SCOPE LIMIT -- read before trusting a clean run.
# These two branches catch the explicit shape: given data + a request for a value.
# They do NOT catch every implicit computation prompt. Known miss:
#   "What percent ionic character do MgO and CH4 have?"   -> not flagged, but it
#   demands a number off the Pauling formula and should be reframed.
# A third branch was tried and reverted: keying on "what + quantity, no comparative"
# also fired on recallable table cards ("what are the APF values for SC, BCC, FCC and
# HCP?"), so it traded real recall cards for theoretical coverage.
#
# Consequence: a clean validate_cards run does NOT mean every card is answerable from
# memory. Per-card human review against the recallability test is a required pipeline
# step, not a formality. See "The recallability test" in SKILL.md.


def is_computation_prompt(front: str) -> str | None:
    """Return a reason string if the front demands a computed value, else None.

    High-precision heuristic. Catches the explicit given-data-plus-value-out shape;
    blind to computation demands phrased without given data.
    """
    if FORBIDDEN_FRONT.search(front):
        return "explicit computation verb"
    f = re.sub(r"\$[^$]+\$", " MATH ", front)      # math payload is given data, not phrasing
    if GIVEN_DATA.search(f) and ASKS_VALUE.search(f) and QUANTITY.search(front):
        return "supplies given data and asks for a value out"
    if ASKS_VALUE.search(f) and QUANTITY.search(front) and re.search(r"\b\d+\b", f):
        return "asks for a numeric result"
    return None

# Symbols whose meaning the exam expects you to be able to state.
STRUCT_GLOSSARY = re.compile(
    r"\*\*(?:glossary|symbols|legend|notation)\b"
    r"|^\s*[-*]?\s*\$?\\?[A-Za-z]_?\{?[A-Za-z0-9]*\}?\$?\s*=", re.I | re.M)

TIER_ZERO = re.compile(r"tier\s*[- ]?zero|tier\s*0", re.I)
CMP = re.compile(r'(lowest|highest|most|least|rank|among)\b', re.I)
FORMULA = re.compile(r"\$[^$]+\$|\b(?:formula|equation)\b", re.I)
CODE_SPAN = re.compile(r"`[^`]*`", re.S)
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
POINTER = re.compile(
    r"\b(?:see|refer to|check)\b[^.?!\n]{0,40}\bcard\b"
    r"|\b(?:the|this|that)\s+(?:next|previous|above|below|earlier|later)\s+card\b",
    re.I)

MATH_SPAN = re.compile(r"\$[^$]+\$", re.S)
HTML_CODE = re.compile(r"<code>.*?</code>", re.I | re.S)
BARE_SUB = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-zρ]|[A-Z][A-Z]?)_"
    r"(?:[A-Za-z0-9]{1,16}|\{[A-Za-z0-9]{1,16}\})")
HTML_BR = re.compile(r"<br\s*/?>", re.I)

PROCEDURE_DECISION = re.compile(
    r"\b(?:which|what)\b[^?\n]{0,80}\b(?:method|principle|law|test|approach|"
    r"technique|next step|next move|first move)\b|\bwhat are the next steps\b", re.I)

# Card families. `stratum` is the retrieval form; `kc` groups cards by the
# knowledge component they practice. Keep the set small so triage and review
# grouping cannot drift into one-off labels.
STRATA = {
    "concept", "mechanism", "condition", "procedure", "representation",
    "error", "schema", "integration", "boundary", "metacognition",
}
KC_HEADING = re.compile(r"(?mi)^(#{1,2})\s+KCs\b.*$")


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def _requires(raw: str) -> list[str]:
    raw = str(raw or "").strip()
    if not raw or raw in {"-", "—", "none", "None", "[]"}:
        return []
    return [x.strip().strip("`") for x in re.split(r"[,;]", raw) if x.strip()]


def parse_kc_map(text: str) -> tuple[dict[str, dict], list[str], bool, bool]:
    """Read the compact `KCs` table from kcs.md (legacy: authoring_ledger.md).

    New format: `kc | type | claim | why | requires | evidence_quote | source`.
    `type` is optional. Legacy 5-column maps without `why`/`evidence_quote` still
    parse, but get no value or evidence check. The heading may be `# KCs` or
    `## KCs`; the table ends at the next h1/h2 heading.
    """
    matches = list(KC_HEADING.finditer(text or ""))
    if not matches:
        return {}, [], False, False
    match = matches[-1]
    block = (text or "")[match.end():]
    block = re.split(r"(?m)^#{1,2}\s+", block, maxsplit=1)[0]
    rows: dict[str, dict] = {}
    duplicates: list[str] = []
    header: list[str] | None = None
    has_evidence = False
    has_why = False
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("```"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        if cells[0].lower() in {"kc_id", "kc", "id"}:
            header = [c.lower() for c in cells]
            has_evidence = "evidence_quote" in header
            has_why = "why" in header or "value" in header
            continue
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells if c):
            continue
        if header:
            values = {name: (cells[i] if i < len(cells) else "")
                      for i, name in enumerate(header)}
            kc_id = values.get("kc_id") or values.get("kc") or values.get("id", "")
            kc_type = values.get("type", "")
            claim = values.get("claim", "")
            why = values.get("why") or values.get("value", "")
            source = values.get("source", "")
            evidence = values.get("evidence_quote", "")
            raw_requires = values.get("requires", "")
        else:
            kc_id, kc_type, claim, source = cells[:4]
            why = ""
            evidence = ""
            raw_requires = cells[4] if len(cells) >= 5 else ""
        kc_id = str(kc_id or "").strip()
        if not kc_id:
            continue
        if kc_id in rows:
            duplicates.append(kc_id)
        rows[kc_id] = {
            "type": str(kc_type or "").strip(),
            "claim": str(claim or "").strip(),
            "why": str(why or "").strip(),
            "source": str(source or "").strip(),
            "evidence_quote": str(evidence or "").strip(),
            "requires": _requires(raw_requires),
        }
    return rows, duplicates, has_evidence, has_why


def kc_findings(cards: list[dict], kc_text: str,
                source_text: str | None = None,
                require_map: bool = False) -> list[tuple[str, str]]:
    """KC value/coverage checks.

    Hard errors are structural: missing map, missing/unknown kc, duplicate id,
    missing claim/why, exact duplicate claim, unresolved requires, ungrounded
    evidence. Single-card KCs and a 1:1 map are warnings; value is judged by the
    adversarial and human reviews, not by a card count.
    """
    kcs, duplicates, has_evidence, has_why = parse_kc_map(kc_text or "")
    if not kcs:
        if require_map:
            return [("err", "kcs.md has no parsable KC table; start it with "
                            "`# KCs` or `## KCs` and a pipe table")]
        return []
    out: list[tuple[str, str]] = []
    if require_map and not has_why:
        out.append(("err", "kcs.md is missing the `why` column; every KC needs a "
                           "one-line value case"))
    if require_map and not has_evidence:
        out.append(("err", "kcs.md is missing the `evidence_quote` column; use "
                           "`derived` for self-contained KCs"))
    for kc_id in duplicates:
        out.append(("err", f"duplicate KC id {kc_id!r} in the KC map"))
    counts: dict[str, int] = {}
    for i, card in enumerate(cards, 1):
        kc_id = str(card.get("kc") or "").strip()
        label = f"card {i}: {str(card.get('front', ''))[:52]!r}"
        if not kc_id:
            out.append(("err", f"{label} -- missing 'kc'; every card names a KC"))
        elif kc_id not in kcs:
            out.append(("err", f"{label} -- kc {kc_id!r} is not in the KC map (kcs.md)"))
        else:
            counts[kc_id] = counts.get(kc_id, 0) + 1
        stratum = str(card.get("stratum") or "").strip()
        if stratum and stratum not in STRATA:
            out.append(("warn", f"{label} -- unknown stratum {stratum!r}; use one of "
                               f"{', '.join(sorted(STRATA))}, or omit it and use the KC type"))

    if len(kcs) > 1 and all(counts.get(kc_id, 0) == 1 for kc_id in kcs):
        out.append(("warn", "every KC has exactly one card; the map mirrors the deck. "
                           "Inspect for card labels; one-card KCs are allowed when the "
                           "card is a complete high-value decision."))

    for kc_id, row in kcs.items():
        count = counts.get(kc_id, 0)
        if not row["claim"]:
            out.append(("err", f"KC {kc_id!r} -- missing 'claim'"))
        if has_why and row["why"].strip().lower() in {"", "-", "—", "none", "n/a", "na"}:
            out.append(("err", f"KC {kc_id!r} -- missing 'why'; state why this KC is "
                               "worth remembering"))
        if count == 0:
            out.append(("warn", f"KC {kc_id!r} has no cards; coverage gap"))
        elif count == 1 and row["type"] in {"concept", "mechanism"}:
            out.append(("warn", f"KC {kc_id!r} is a single-card {row['type']}; "
                               "justify it in `why` or add a second retrieval angle "
                               "only if it adds value"))
        for req in row["requires"]:
            if req != "external" and req not in kcs:
                out.append(("err", f"KC {kc_id!r} requires unknown KC {req!r}"))

    seen_claims: dict[str, str] = {}
    for kc_id, row in kcs.items():
        key = _norm_text(row["claim"])
        if not key:
            continue
        if key in seen_claims:
            out.append(("err", f"KCs {seen_claims[key]!r} and {kc_id!r} have the exact "
                               "same claim; they are one KC, not two"))
        else:
            seen_claims[key] = kc_id

    if source_text and has_evidence:
        corpus = _norm_text(source_text)
        for kc_id, row in kcs.items():
            src = str(row.get("source") or "").strip()
            if src.lower() in DERIVED_SOURCES:
                continue
            quote = str(row.get("evidence_quote") or "").strip()
            if not quote or quote in {"-", "—", "none", "None", "[]"}:
                out.append(("err", f"KC {kc_id!r} -- source-dependent KCs need an "
                                   "evidence_quote in kcs.md"))
                continue
            norm = _norm_text(quote)
            if len(norm) < 20:
                out.append(("warn", f"KC {kc_id!r} -- evidence_quote is very short"))
            if norm not in corpus:
                out.append(("err", f"KC {kc_id!r} -- evidence_quote is not in the "
                                   "extracted source"))
    return out


def findings(cards):
    """Every check below, as (card_index, severity, message) records.

    1-based `card_index` matches the numbering used everywhere else in the skill
    (roi_report, the review page, `--show N`). Deck-level lines carry index 0.

    Exists so `triage.py` can select the cards worth a human's time from the SAME
    checks this script runs, rather than growing a second, drifting copy of them.
    check_cards() is a thin formatter over this and remains the public CLI output;
    the messages are byte-identical to what it printed before.
    """
    out: list[tuple[int, str, str]] = []
    back_verb_cards = []      # see B4 below: counted, not warned per-card

    def add(i, sev, msg):
        out.append((i, sev, msg))

    for i, c in enumerate(cards, 1):
        label = f"card {i}: {str(c.get('front', ''))[:52]!r}"
        for key in ("front", "back", "layer", "topic", "deck"):
            if key not in c or not str(c.get(key, "")).strip():
                add(i, "err", f"{label} -- missing/empty {key!r}")

        # Tags: the topic heads every card and every deck tag, so it has to be a
        # chapter a student could look up. A layer code in this field is the
        # specific mistake of reaching for the vocabulary you happen to have in
        # front of you -- it renders as the card's own label ("L2"), which tells
        # the reader nothing and tags every understanding card in the deck.
        topic = str(c.get("topic", "")).strip()
        if topic in ("L1", "L2", "L3", "Procedure", "Recall", "Understanding",
                     "Boundary", "Boundaries"):
            add(i, "err", f"{label} -- topic is the layer {topic!r}, not a subject; "
                          f"a topic is a chapter name ('Unit Cells', 'Dislocations')")

        # Objects are the sniper tags. Bounded at two on purpose: a third stops
        # being a name for a thing and starts being a paraphrase of the front.
        objects = c.get("objects") or []
        if isinstance(objects, str):
            objects = [objects]
            add(i, "err", f"{label} -- 'objects' is a string, not a list; "
                          f'it must be a JSON array, e.g. "objects": ["fcc", "cu"]')
        if isinstance(objects, list):
            seen_o = {}
            for o in objects:
                key = _tag_key(o)
                if not str(o).strip():
                    add(i, "err", f"{label} -- empty entry in 'objects'")
                elif key == _tag_key(topic):
                    # Anki folds tags case-insensitively, so this one is silently
                    # dropped at build time: the topic already carries the name.
                    add(i, "warn", f"{label} -- object {str(o)!r} is the topic tag; "
                                   f"Anki will fold the two together and drop it")
                elif key in seen_o:
                    add(i, "warn", f"{label} -- duplicate object {str(o)!r} "
                                   f"(same as {seen_o[key]!r} after lowercase)")
                else:
                    seen_o[key] = str(o).strip()
            if len(objects) > 2:
                add(i, "warn", f"{label} -- {len(objects)} object tags "
                              f"(max 2): {objects!r}; keep the ones the card is "
                              f"actually about")

        # Media is opt-in at build time, but the shape is always checked. A string
        # is the legacy form (file only, back); an object adds side/caption/source.
        media_list = c.get("media") or []
        if not isinstance(media_list, list):
            add(i, "err", f"{label} -- 'media' must be a list")
        else:
            for m in media_list:
                if isinstance(m, str):
                    mfile, mside = m, "back"
                elif isinstance(m, dict):
                    mfile = str(m.get("file") or "").strip()
                    mside = str(m.get("side") or "back").lower()
                else:
                    add(i, "err", f"{label} -- media entry must be a string or object")
                    continue
                if not mfile:
                    add(i, "err", f"{label} -- media entry has no file")
                    continue
                if mside not in ("front", "back"):
                    add(i, "err", f"{label} -- media side {mside!r} (use front/back)")
                if ".." in Path(mfile).parts:
                    add(i, "err", f"{label} -- media path escapes the root: {mfile!r}")
            if len(media_list) > 2:
                add(i, "warn", f"{label} -- {len(media_list)} media entries (max 2); "
                              "the extra ones will be skipped at build")
            has_front = any(isinstance(m, dict)
                            and str(m.get("side") or "back").lower() == "front"
                            for m in media_list)
            if FRONT_REF.search(str(c.get("front", ""))) and not has_front:
                add(i, "warn",
                    f"{label} -- front refers to an image/example but has no front "
                    "media; put the image on the front or inline the data")

        # 8. provenance. build_native.py renders `source` as the card footer;
        # `source_ref` is an older spelling of the same field and still works.
        # A card with no citation cannot be checked against the material later,
        # which is the entire point of carrying one -- so absence is an error,
        # and a citation with no locator (no page/slide/question/chapter number)
        # is a warning, because it names a document but not a place in it.
        src = str(c.get("source") or c.get("source_ref") or "").strip()
        if not src:
            add(i, "err",
                f"{label} -- no source. Use a locator (lecture + page/slide, "
                "homework question, textbook chapter) or `source: \"derived\"` "
                "for self-contained math/definitions.")
        elif src.lower() in DERIVED_SOURCES:
            pass
        elif not re.search(r"\d", src):
            add(i, "warn",
                f"{label} -- source {src!r} carries no locator (no page, slide, "
                "question or chapter number), so it cannot be pinpointed again.")
        elif len(src) > 110:
            add(i, "warn",
                f"{label} -- source is {len(src)} chars; use the canonical short "
                "label (e.g. 'DigiKey · RTOS 04 · Memory Management @ 01:32') and "
                "keep the full URL in source_url")
        source_url = str(c.get("source_url") or "").strip()
        if source_url:
            if not re.match(r"^https?://\S+$", source_url, re.I):
                add(i, "err", f"{label} -- source_url must be an http(s) URL")
            elif re.search(r"(youtube\.com|youtu\.be)", source_url, re.I) and                     not re.search(r"[?&]t=\d+", source_url):
                add(i, "warn", f"{label} -- YouTube source_url has no t=<seconds>")

        front, back = str(c.get("front", "")), str(c.get("back", ""))
        layer = c.get("layer", "")

        if ENZYME_ASK.search(front) and not ENZYME_NAME.search(back):
            add(i, "err", f"{label} -- front asks which enzyme but the back names no "
                          "enzyme (answer first, then explain)")

        # 1. escape corruption
        for f, t in (("front", front), ("back", back)):
            if CTRL.search(t):
                bad = CTRL.search(t).group(0)
                add(i, "err", f"{label} -- control char 0x{ord(bad[0]):02x} in {f}; "
                              f"use a raw (r\"...\") string when writing LaTeX")

        # 2. delimiter balance in the SOURCE
        for f, t in (("front", front), ("back", back)):
            if t.count("$$") % 2:
                add(i, "err", f"{label} -- odd number of $$ in {f}")
            if t.count(r"\(") != t.count(r"\)") or t.count(r"\[") != t.count(r"\]"):
                add(i, "err", f"{label} -- unbalanced MathJax delimiters in {f}")
            for m in re.finditer(r"\$([^$]+?)\$", t, re.S):
                if m.group(1).count("{") != m.group(1).count("}"):
                    add(i, "err", f"{label} -- brace imbalance in math: {m.group(1)[:40]!r}")

        # 3. rendered leaks
        for f, t in (("front", front), ("back", back)):
            h = to_html(t)
            # A literal `$` is sometimes genuinely required -- a card explaining the
            # delimiter rules cannot say "no $ is enabled" without one. render.py puts
            # inline code in <code>, so strip those spans before hunting for a stray
            # delimiter, or the explanation is reported as the defect.
            h_prose = re.sub(r"<code>.*?</code>", "", h, flags=re.S)
            if re.search(r"(?<!\\)\$", h_prose):
                add(i, "err", f"{label} -- stray $ survived rendering in {f}")
            if h.count(r"\(") != h.count(r"\)") or h.count(r"\[") != h.count(r"\]"):
                add(i, "err", f"{label} -- MathJax delimiters unbalanced after render ({f})")
            if CTRL.search(h):
                add(i, "err", f"{label} -- control char present after render ({f})")

        # Strip display math BEFORE inline. Stripping only $...$ leaves the outer
        # delimiters of a $$...$$ block behind, and the leftover '$' then mis-pairs
        # with a later inline span -- swallowing a ** and reporting "unmatched **"
        # on a card that was perfectly fine.
        # FRONTS ONLY, deliberately: this check never runs on backs, and backs
        # legitimately mix $$ with $...$ (32 cards in one real deck did). Do not
        # "fix" that by extending this to backs.
        raw_md = CODE_SPAN.sub("", front)
        raw_md = re.sub(r"\$\$.*?\$\$", "", raw_md, flags=re.S)
        raw_md = re.sub(r"\$[^$]+\$", "", raw_md, flags=re.S)
        # parity, not presence: a matched **bold** is 2 markers; an unclosed one is odd
        if raw_md.count("**") % 2:
            add(i, "err", f"{label} -- unmatched ** in front (would render literally)")
        if re.match(r"^\s*[-*]\s", front):
            add(i, "warn", f"{label} -- front starts with a markdown bullet")

        # 4. computation demands -- explicit verbs and implicit prompts alike
        why = is_computation_prompt(front)
        procedure_decision = layer == "Procedure" and bool(PROCEDURE_DECISION.search(front))
        if why and layer != "L3" and not procedure_decision:
            add(i, "err", f"{label} -- computation prompt in front ({why}); a front "
                          "must be answerable from memory, not by working it out")
        # B4: a computation verb in a BACK is fine by the skill's own scoping rule --
        # a back may legitimately say "set them equal and solve". Emitting one warning
        # per card produced 10 identical lines on a real deck and buried the warnings
        # that mattered. Counted and reported once, in `info`.
        if FORBIDDEN_FRONT.search(back):
            back_verb_cards.append(i)

        # 6. Comparison/ranking fronts must embed decision data.
        # If a front asks "which... lowest/highest/most/least/rank among ..."
        # it must embed the decision data (table with |, digits, or $math$).
        # Warn instead of error: some legitimate comparison fronts are pure recall
        # (e.g., "which of the four Hume-Rothery criteria fails?").
        f = c.get('front', '')
        if CMP.search(f) and not re.search(r'[|\d$]', f):
            add(i, "warn",
                f"{label} -- comparison front lacks embedded data (no table |, "
                "no digits, no $math$). Front must carry the decision data so the "
                "answer is readable without external lookup.")

        # 5. stubs
        if len(front.strip()) < 15:
            add(i, "err", f"{label} -- front too short")
        if len(back.strip()) < 25:
            add(i, "err", f"{label} -- back too short")
        if layer not in {"L1", "L2", "L3", "Procedure"}:
            add(i, "err", f"{label} -- bad layer {layer!r}")

        # D4: the Procedure layer's whole contract is that the front STATES its
        # demand -- "Which method applies here?" or "What are the next steps?" --
        # because a front showing a problem plus a halfway state is otherwise
        # ambiguous about whether to finish it, name the next step, or name the
        # method. Nothing checked that, so such a card passed every gate and was
        # unanswerable in review.
        if layer == "Procedure" and "?" not in front:
            add(i, "warn",
                f"{label} -- Procedure front asks no question; state the demand "
                "explicitly (which method / what are the next steps)")
        # Cloze is a deliberate choice here: the deck carries a real cloze note
        # type, so deletions render as independent cards. What IS worth flagging is
        # a card marked cloze with no deletion, or unmarked cloze syntax.
        is_cloze_flag = bool(c.get("cloze"))
        has_deletion = bool(re.search(r"\{c\d+::", front))
        if is_cloze_flag and not has_deletion:
            add(i, "err", f"{label} -- flagged cloze but front has no {{cN::}} deletion")
        if has_deletion and not is_cloze_flag:
            add(i, "err", f"{label} -- front contains cloze syntax but card is not "
                          "flagged cloze; it would render literally as a Basic note")
        if is_cloze_flag:
            blanks = list(re.finditer(r"\{\{c\d+::", front))
            if len(blanks) >= 2:
                for blank in blanks:
                    before = front[max(0, blank.start() - 50):blank.start()]
                    if not re.search(r"[:=]\s*$", before):
                        add(i, "warn",
                            f"{label} -- multi-blank cloze needs a label before "
                            "each blank (e.g. 'Tolerance:', 'Power:', 'Typical use:')")
                        break

        # F2: a cloze front should have ONE retrieval target -- the blank. A second
        # question means every sibling card grades two things at once ("... {{c1::x}}
        # ... What is the rule behind all four?"), a bundling failure created inside
        # what looked like a clean enumeration.
        #
        # Paragraph-scoped on purpose. A question in the SAME paragraph as a deletion
        # is usually that blank's own prompt ("**Which symbol?** ... {{c1::[uvw]}}"),
        # which rule 6 requires -- flagging those was a false positive on a real deck.
        # Only a question in a paragraph with NO deletion is a second target.
        if is_cloze_flag:
            for para in re.split(r"\n\s*\n", front):
                if "?" in para and not re.search(r"\{\{c\d+::", para):
                    add(i, "warn",
                        f"{label} -- cloze front asks a question away from the blanks "
                        f"({para.strip()[:40]!r}); does this front test two things? If "
                        "so, give the second question its own card.")
                    break

        # 7. glossary presence on symbol-bearing cards. Info, not warning: a
        # forced glossary on every symbol card is over-scaffolding, which hurts
        # an expert learner. The review checklist still asks for it.
        has_sym = len(set(SYM.findall(front) + SYM.findall(back))) >= 3
        if has_sym and layer in {"L1", "L2"} and not STRUCT_GLOSSARY.search(back):
            add(i, "info",
                f"{label} -- symbol-heavy card with no glossary/definition "
                "in the back; check it during review rather than adding boilerplate")

        # 9. unterminated cloze deletion. Anki closes at the first '}}'; a card
        # with no close at all renders the remainder as literal text. Braces
        # inside a deletion are rejected by build_native.check_cloze_braces.
        if is_cloze_flag:
            for m in re.finditer(r"\{\{c(\d+)::", front):
                j, depth = m.end(), 2
                while j < len(front) and depth > 0:
                    if front[j] == "{":
                        depth += 1
                    elif front[j] == "}":
                        depth -= 1
                    j += 1
                if depth > 0:
                    add(i, "err",
                        f"{label} -- cloze deletion c{m.group(1)} never closes; "
                        "the rest of the card would render literally")
                    break

        # 10. literal markdown images. extract_slides writes ![..](..) into its
        # markdown; copying that into a card ships unrendered text because Anki
        # renders no markdown. Use the media field instead.
        for f, t in (("front", front), ("back", back)):
            prose = CODE_SPAN.sub("", t)
            if MARKDOWN_IMAGE.search(prose):
                add(i, "err",
                    f"{label} -- literal markdown image in {f}; use the card's "
                    "media field (file/side/caption/source), not ![..](..)")

        # 11. cross-card pointers. Each card is reviewed alone, in random order;
        # a pointer to a sibling resolves to nothing where it is needed.
        if POINTER.search(CODE_SPAN.sub("", back)):
            add(i, "err",
                f"{label} -- back points at another card; write the information "
                "in this card instead (rule 26)")

    layers = Counter(c.get("layer") for c in cards)
    topics = Counter(c.get("topic") for c in cards)
    add(0, "info", f"{len(cards)} cards | layers {dict(layers)}")

    # Rule 6: a formula-bearing topic needs one concept card before its formulas.
    # Warning only, and only from three formula cards up: a two-card topic is often
    # intentional, and the model must not add a card just to silence a checker.
    formula_topics = Counter(
        str(c.get("topic") or "")
        for c in cards
        if c.get("layer") in {"L1", "L2"}
        and FORMULA.search(f"{c.get('front', '')}\n{c.get('back', '')}"))
    tier_topics = {str(c.get("topic") or "") for c in cards
                   if c.get("tier_zero") or TIER_ZERO.search(str(c.get("front", "")))}
    for topic, count in sorted(formula_topics.items()):
        if count >= 3 and topic not in tier_topics:
            add(0, "warn",
                f"topic {topic!r} has {count} formula cards and no tier-zero "
                "concept card; consider one, but do not add it automatically")
    if len(cards) >= 8:
        singles = sorted(t for t, n in topics.items() if n == 1)
        if len(singles) >= max(3, len(topics) // 2):
            add(0, "warn", f"{len(singles)} one-card topics "
                          f"({', '.join(singles[:6])}); a topic is the chapter/lecture "
                          f"heading, not a subtopic — merge these into their parent")
        if len(topics) > max(4, len(cards) // 3):
            add(0, "warn", f"{len(topics)} topics for {len(cards)} cards; topic is the "
                          f"chapter/lecture heading, not a card or subtopic — do not "
                          f"artificially split one chapter")
        for topic, count in sorted(topics.items()):
            if count > 15:
                add(0, "warn", f"topic {topic!r} has {count} cards; 4–15 is the "
                               "healthy range — check for restatement before adding "
                               "more (warning only, never an automatic cut)")
    # tier-zero may be flagged as a field, or (older cards) by front text
    tz = sum(1 for c in cards
             if c.get("tier_zero") or TIER_ZERO.search(str(c.get("front", ""))))
    add(0, "info", f"{len(topics)} topics | tier-zero cards: {tz}")
    # Object tags are only worth having if they repeat -- a tag on one card names
    # nothing you can search for. One-per-deck is the signal to re-pick them.
    objs = Counter(str(o).strip().lower()
                   for c in cards
                   for o in (c.get("objects") or [])
                   if str(o).strip())
    if objs:
        singletons = sorted(o for o, k in objs.items() if k == 1)
        add(0, "info", f"{len(objs)} object tags | "
                       f"most common: {', '.join(f'{o}({k})' for o, k in objs.most_common(6))}")
        if len(objs) >= 3 and len(singletons) > len(objs) / 2:
            add(0, "warn", f"{len(singletons)} of {len(objs)} object tags appear on a "
                           f"single card ({', '.join(singletons[:6])}); an object "
                           "tag should name a thing more than one card is about")
    if back_verb_cards:
        add(0, "info", f"{len(back_verb_cards)} card(s) use an instructional verb in the "
                       "back (expected -- a back may describe method)")
    return out


DUPLICATE_FRONT_RATIO = 0.85


def _norm_card(c: dict) -> tuple[str, str]:
    front = " ".join(str(c.get("front", "")).split()).casefold()
    back = " ".join(str(c.get("back", "")).split()).casefold()
    return front, back


def exact_duplicate_pairs(cards) -> list[tuple[int, int]]:
    """1-based pairs whose normalized front+back are identical.

    Deterministic and O(n). This is the only in-deck duplicate check on the
    default path; near-duplicate/front-similarity heuristics are opt-in via
    `--deep`, because on a real deck they produced contrast false positives and
    cost more model attention than they saved.
    """
    seen: dict[tuple[str, str], int] = {}
    out = []
    for i, c in enumerate(cards, 1):
        key = _norm_card(c)
        if key in seen:
            out.append((seen[key], i))
        else:
            seen[key] = i
    return out


def similar_front_pairs(cards) -> list[tuple[int, int, float]]:
    """[(i, j, ratio)] for front pairs above DUPLICATE_FRONT_RATIO, 1-based, i < j.

    Deliberately a function rather than a warning emitted inline from `findings`:
    triage.py needs the PAIRS and their ratios, not the sentence describing them.
    It used to recover them by regex-parsing this module's message text, so
    rewording the message would have silently stopped pairs being recombined.
    Both readers now call this one definition.
    """
    out = []
    for i in range(len(cards)):
        for j in range(i + 1, len(cards)):
            a, b = str(cards[i].get("front", "")), str(cards[j].get("front", ""))
            r = SequenceMatcher(None, a, b).ratio()
            if r > DUPLICATE_FRONT_RATIO:
                out.append((i + 1, j + 1, r))
    return out


ENZYME_ASK = re.compile(r"\b(?:which|what|name)\b[^?]{0,100}\benzyme\b", re.I)
ENZYME_NAME = re.compile(r"\b(?!enzyme\b)[a-z]{4,}(?:ase|zyme)\b", re.I)




TAG_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "in", "is", "it", "of", "on", "or", "that", "the", "this", "to", "what",
    "when", "where", "which", "who", "why", "with",
}
CONTRAST_FRONT = re.compile(
    r"\b(vs\.?|versus|bounded|unbounded|difference|different|instead|"
    r"contrast|compare|comparison)\b", re.I)


def _tag_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower())
            if len(w) > 2 and w not in TAG_STOP}


def tag_leak_findings(cards):
    """Tags are front-visible. A one-topic object tag that only appears in the
    answer is an error; a topic that does so is a warning (topics are context).

    Broad object buckets are context, not answers, so they are exempt.
    """
    spans = {}
    for c in cards:
        for obj in (c.get("objects") or []):
            spans.setdefault(_tag_key(obj), set()).add(str(c.get("topic", "")))
    out = []
    for i, c in enumerate(cards, 1):
        front = _tag_words(str(c.get("front", "")))
        back = _tag_words(str(c.get("back", "")))
        tags = []
        topic = str(c.get("topic", "")).strip()
        if topic:
            tags.append(("topic", topic))
        for obj in (c.get("objects") or []):
            key = _tag_key(obj)
            if spans.get(key) and len(spans[key]) > 1:
                continue
            tags.append(("object", str(obj)))
        for kind, tag in tags:
            words = _tag_words(tag)
            if not words or not words <= back or words & front:
                continue
            if kind == "topic" and len(tag.split()) > 2:
                continue
            hint = ("confirm it is chapter context, not the answer"
                    if kind == "topic" else
                    "tags are visible before answering, so do not reveal the answer")
            out.append((i, "err" if kind == "object" else "warn",
                        f"{kind} tag {tag!r} appears only in the answer; {hint}"))
    return out


def math_format_findings(cards):
    """Warn on plain-text symbols and literal <br> in card text.

    Math and code spans are exempt: a programming deck may legitimately write
    `x_1` inside backticks. The scan is intentionally narrow to single-letter or
    Greek symbols with a subscript, not arbitrary snake_case prose.
    """
    out = []
    for i, c in enumerate(cards, 1):
        for field in ("front", "back"):
            text = str(c.get(field, ""))
            br = HTML_BR.search(text)
            if br:
                out.append((i, "warn", f"literal <br> in {field}; use a blank line "
                                      "or two trailing spaces for a hard break"))
            clean = MATH_SPAN.sub(" ", text)
            clean = CODE_SPAN.sub(" ", clean)
            clean = HTML_CODE.sub(" ", clean)
            m = BARE_SUB.search(clean)
            if m:
                token = m.group(0)
                out.append((i, "warn", f"bare symbol {token!r} in {field}; write it "
                                      "in MathJax, e.g. $P_{0}$ (use _{\text{...}} "
                                      "for word subscripts)"))
    return out


def similar_answer_pairs(cards) -> list[tuple[int, int, float]]:
    """[(i, j, containment)] for same-topic/source cards whose answers overlap.

    Front similarity alone flags contrasts (stack vs heap, bounded vs unbounded).
    This uses answer vocabulary instead, and skips pairs whose fronts explicitly
    signal a contrast. Warning-only: it asks for a merge-or-keep decision.
    """
    out = []
    backs = [_tag_words(str(c.get("back", ""))) for c in cards]
    contrast = [bool(CONTRAST_FRONT.search(str(c.get("front", "")))) for c in cards]
    for i in range(len(cards)):
        for j in range(i + 1, len(cards)):
            a, b = cards[i], cards[j]
            same_topic = a.get("topic") == b.get("topic")
            same_source = (str(a.get("source", "")).split(" @ ")[0]
                           == str(b.get("source", "")).split(" @ ")[0])
            if not (same_topic or same_source) or contrast[i] or contrast[j]:
                continue
            shared = backs[i] & backs[j]
            if len(shared) < 6:
                continue
            ratio = len(shared) / min(len(backs[i]), len(backs[j]))
            if ratio >= 0.40:
                out.append((i + 1, j + 1, round(ratio, 3)))
    return out


def check_cards(cards, deep: bool = False, ledger_text: str | None = None,
                source_text: str | None = None, require_kc_map: bool = False):
    """The CLI's (errors, warnings, info) view.

    Exact normalized duplicates are always errors. Soft front/answer similarity
    is only computed with `deep=True`: it is useful for an explicit debloat pass
    but was mostly contrast-family noise on a real deck.

    `ledger_text` is the kcs.md table (legacy: authoring_ledger.md) and enables the KC
    map checks; `source_text` enables evidence-quote grounding. Both are optional so standalone callers and legacy decks keep
    working.
    """
    fs = findings(cards)
    errs = [m for _, s, m in fs if s == "err"]
    seen: set[str] = set()
    warns = [m for _, s, m in fs if s == "warn" and not (m in seen or seen.add(m))]
    info = [m for _, s, m in fs if s == "info"]

    kcs, _, _, _ = parse_kc_map(ledger_text or "")
    extra = kc_findings(cards, ledger_text or "", source_text=source_text,
                        require_map=require_kc_map)
    for sev, msg in extra:
        if sev == "err":
            errs.append(msg)
        elif sev == "warn":
            warns.append(msg)
        else:
            info.append(msg)
    if kcs:
        info.append(f"KC map: {len(kcs)} KC(s) | "
                    f"{sum(1 for c in cards if c.get('kc'))}/{len(cards)} "
                    "card(s) linked")

    for i, j in exact_duplicate_pairs(cards):
        errs.append(f"cards {i} and {j} are exact duplicates "
                    "(same normalized front and back)")

    math_findings = math_format_findings(cards)
    warns.extend(f"card {i}: {msg}" for i, sev, msg in math_findings
                 if sev == "warn")

    tag_findings = tag_leak_findings(cards)
    errs.extend(f"card {i}: {msg}" for i, sev, msg in tag_findings if sev == "err")
    warns.extend(f"card {i}: {msg}" for i, sev, msg in tag_findings if sev == "warn")

    if deep:
        for i, j, r in similar_front_pairs(cards):
            warns.append(f"cards {i} and {j} fronts {r:.0%} similar")
        for i, j, r in similar_answer_pairs(cards):
            warns.append(f"cards {i} and {j} answers {r:.0%} overlapping; "
                         "merge or keep only if they are a contrast")
    return errs, warns, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cards_json")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--deep", action="store_true",
                    help="also run soft front/answer similarity (opt-in debloat)")
    ap.add_argument("--ledger", help="kcs.md (or legacy authoring_ledger.md) with a ## KCs map")
    ap.add_argument("--source", help="extracted source markdown for quote grounding")
    args = ap.parse_args()

    cards = load_cards(args.cards_json)
    ledger = Path(args.ledger).read_text() if args.ledger else None
    source = Path(args.source).read_text() if args.source else None
    require_map = bool(args.ledger and Path(args.ledger).name == "kcs.md")
    errs, warns, info = check_cards(cards, deep=args.deep, ledger_text=ledger,
                                    source_text=source,
                                    require_kc_map=require_map)

    if args.json:
        print(json.dumps({"valid": not errs, "errors": errs, "warnings": warns,
                          "info": info}, indent=2))
    else:
        for line in info:
            print(line)
        print(f"\n{len(errs)} error(s), {len(warns)} warning(s)")
        for e in errs:
            print("  ERROR  ", e)
        for w in warns[:20]:
            print("  warn   ", w)
        if len(warns) > 20:
            print(f"  ... and {len(warns) - 20} more warnings")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())