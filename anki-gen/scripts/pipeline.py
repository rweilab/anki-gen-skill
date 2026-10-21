#!/usr/bin/env python3
"""Run the mechanical half of the deck pipeline in ONE call, and print a short summary.

Why this exists
---------------
Every stage used to hand off through the model's context, so a 10-lecture deck cost ~20
bash round-trips and the ad-hoc Python to stitch them together. Measured on a real run:
86 steps, 84% of them carrying a single tool call, and 190k chars of self-written shell
against 39k of calls into the skill's own scripts. A step is the cost, not a token --
every step re-sends the whole context -- so collapsing five stages into one call is worth
more than any wording change.

What it does and does not do
----------------------------
It does the mechanical work: extract, validate, triage, ROI. It prints a
summary and the paths, and **nothing else belongs in context** -- read the artifacts by
path when a later stage actually needs one.

It does NOT classify or write cards. Those are judgements, and they stay with the model
(see SKILL.md stage 5 and 7). This script's job is to make the mechanical half cost one
step instead of twenty.

Usage
-----
    pipeline.py --sources Lec/*.pdf --out .anki-gen-temp/midterm1
    pipeline.py --cards cards.jsonl --out .anki-gen-temp/midterm1 --gates-only

Deliberately no `--resume` and no chunking: this is one pass over one target. A corpus
too large for one context is the job of the checkpointing work, not of this script.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cardid import load_cards                       # noqa: E402


def _short(path: Path, root: Path) -> str:
    """A path relative to the run root, so the summary stays one line per stage."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def stage_extract(sources: list[str], out: Path, manifest_full: bool) -> dict:
    from extract_pdf import run_batch

    manifest = run_batch(sources, out, None, manifest_full)
    ok = [s for s in manifest["sources"] if not s.get("error")]
    chars = sum(s.get("chars", 0) for s in ok)
    figs = sum(s.get("images", 0) if isinstance(s.get("images"), int) else 0 for s in ok)
    return {"sources": len(ok), "failed": len(manifest["failed"]),
            "chars": chars, "figures": figs, "manifest": manifest}


def stage_gates(cards_path: Path, out: Path, per_topic: int, max_total: int) -> dict:
    """Validate, triage and ROI on the written deck. Consumes the FILE, returns counts."""
    from validate_cards import check_cards
    from triage import select, build_plan
    import roi_report

    cards = load_cards(cards_path)
    errs, warns, info = check_cards(cards)

    entries, stats = select(cards, per_topic, max_total)
    plan = build_plan(str(cards_path), cards, entries, stats, per_topic, max_total)
    plan_path = out / "review_plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")

    # ROI is a report, not a gate; its output goes to a file so it never enters context
    # unless someone asks. Capture rather than print: the summary is the interface.
    # roi_report.main() parses sys.argv itself (no argv parameter), so argv is set for
    # the call and restored after -- the alternative is duplicating its report code.
    roi_path = out / "roi.txt"
    import io
    import contextlib
    buf = io.StringIO()
    saved_argv = sys.argv
    try:
        sys.argv = ["roi_report.py", str(cards_path)]
        with contextlib.redirect_stdout(buf):
            roi_report.main()
    except SystemExit:
        pass
    finally:
        sys.argv = saved_argv
    roi_path.write_text(buf.getvalue())

    return {"cards": len(cards), "errors": len(errs), "warnings": len(warns),
            "selected": len(entries), "total": len(cards),
            "plan": plan_path, "roi": roi_path}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="pipeline.py",
        description="Extract, validate, triage and ROI in one call.")
    ap.add_argument("--sources", nargs="*", default=None,
                    help="PDFs / directories / files to extract (batch mode)")
    ap.add_argument("--cards", default=None,
                    help="an existing deck (.json or .jsonl) to gate instead of extracting")
    ap.add_argument("--out", required=True, help="work directory for this topic")
    ap.add_argument("--deck-name", default=None,
                    help="recorded in the summary only; the build takes it separately")
    ap.add_argument("--manifest-full", action="store_true",
                    help="list every image path in the manifest (diagnosis only)")
    ap.add_argument("--per-topic", type=int, default=1)
    ap.add_argument("--max", dest="max_total", type=int, default=12)
    ap.add_argument("--gates-only", action="store_true",
                    help="skip extraction; just validate/triage/ROI the --cards deck")
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    root = Path.cwd()
    lines: list[str] = []

    if args.gates_only and not args.cards:
        print("pipeline.py: --gates-only requires --cards", file=sys.stderr)
        return 2
    if not args.gates_only and not args.sources and not args.cards:
        print("pipeline.py: pass --sources to extract, or --cards to gate an existing "
              "deck (or --gates-only with --cards)", file=sys.stderr)
        return 2
    if args.sources and not args.gates_only:
        ex = stage_extract(args.sources, out, args.manifest_full)
        if not ex["sources"]:
            lines.append(f"extract    0 source(s), {ex['failed']} FAILED")
            print("\n".join(lines))
            return 1
        lines.append(f"extract    {ex['sources']} source(s), {ex['chars']:,} chars"
                     f", {ex['figures']} figures"
                     + (f", {ex['failed']} FAILED" if ex["failed"] else ""))
        if ex["failed"]:
            for s in ex["manifest"]["sources"]:
                if s.get("error"):
                    lines.append(f"           ! {s['tag']}: {s['error']}")
        # The model's turn is here: classify and write the deck. Stage 5/7.
        lines.append("NEXT       classify the sources, then write cards.jsonl "
                     "(stage 5 -> 7); re-run with --cards for the gates")

    g = None
    if args.cards:
        g = stage_gates(Path(args.cards), out, args.per_topic, args.max_total)
        lines.append(f"gates      {g['cards']} card(s): {g['errors']} error(s), "
                     f"{g['warnings']} warning(s)")
        lines.append(f"triage     {g['selected']} of {g['total']} selected -> "
                     f"{_short(g['plan'], root)}")
        lines.append(f"roi        {_short(g['roi'], root)}")
        if args.deck_name:
            lines.append(f"deck-name  {args.deck_name}")

    print("\n".join(lines))
    # Exit non-zero on a validation error so a caller can branch without parsing text.
    return 1 if (g and g["errors"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
