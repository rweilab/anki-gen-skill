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
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cardid import load_cards                       # noqa: E402
from preflight import check as preflight            # noqa: E402


def _short(path: Path, root: Path) -> str:
    """A path relative to the run root, so the summary stays one line per stage."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _is_media_source(source: str) -> bool:
    from media_transcribe import is_media
    path = Path(source[7:] if source.startswith("file://") else source)
    if path.is_file():
        return is_media(path)
    if path.is_dir():
        return any(is_media(p) for p in path.rglob("*") if p.is_file())
    low = source.lower()
    return "youtube.com/" in low or "youtu.be/" in low


def stage_media(sources: list[str], out: Path, images: str, model: str,
                language: str, force: bool) -> dict:
    """Transcribe local/URL media and frames in one extraction command per source."""
    from media_transcribe import is_media, media_files
    local_files = []
    for s in sources:
        p = Path(s[7:] if s.startswith("file://") else s)
        if p.is_file() and is_media(p):
            local_files.append(p)
        elif p.is_dir():
            local_files.extend(media_files(str(p)))
    cleanup = None
    if len(local_files) > 1:
        cleanup = tempfile.TemporaryDirectory(dir=out)
        batch = Path(cleanup.name)
        used = {}
        for p in local_files:
            name = p.name
            if name in used:
                used[name] += 1
                name = f"{p.stem}-{used[name]}{p.suffix}"
            else:
                used[name] = 1
            link = batch / name
            link.symlink_to(p.resolve())
            side = p.with_suffix(".vtt")
            if side.is_file():
                (batch / f"{link.stem}.vtt").symlink_to(side.resolve())
            side = p.with_suffix(".srt")
            if side.is_file():
                (batch / f"{link.stem}.srt").symlink_to(side.resolve())
        sources = [str(batch)]
    try:
        videos = chunks = 0
        failed = 0
        for source in sources:
            cmd = [sys.executable, str(Path(__file__).with_name("extract_video.py")),
                   source, "--work", str(out), "--images", images,
                   "--model", model, "--language", language]
            if force:
                cmd.append("--force-transcribe")
            r = subprocess.run(cmd, capture_output=True, text=True)
            meta_path = out / "video_meta.json"
            if r.returncode != 0:
                failed += 1
                print(f"pipeline.py: media failed for {source}: {r.stderr[-300:]}",
                      file=sys.stderr)
                continue
            try:
                meta = json.loads(meta_path.read_text())
                videos += len(meta.get("videos") or [])
                chunks += int(meta.get("chunks") or 0)
            except (OSError, json.JSONDecodeError):
                failed += 1
        return {"videos": videos, "chunks": chunks, "failed": failed}
    finally:
        if cleanup:
            cleanup.cleanup()


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


def stage_build(cards_path: Path, out: Path, deck_name: str, apkg: Path | None,
                media: bool, media_root: str | None, strict: bool) -> dict:
    """Build and validate the package in one process, returning a compact result."""
    target = apkg or (out / "deck.apkg")
    cmd = [sys.executable, str(Path(__file__).with_name("build_apkg.py")),
           str(cards_path), str(target), "--deck-name", deck_name]
    if media:
        cmd += ["--media", "--media-root", str(media_root or cards_path.parent)]
    if strict:
        cmd.append("--strict")
    built = subprocess.run(cmd, capture_output=True, text=True)
    if built.returncode != 0:
        return {"ok": False, "apkg": None, "error": built.stderr[-500:] or built.stdout[-500:]}
    validated = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("validate_apkg.py")),
         str(target)], capture_output=True, text=True)
    if validated.returncode != 0:
        return {"ok": False, "apkg": str(target),
                "error": validated.stderr[-500:] or validated.stdout[-500:]}
    summary = " | ".join(line.strip() for line in built.stdout.splitlines()
                         if line.strip())
    return {"ok": True, "apkg": str(target), "validation": validated.stdout.strip(),
            "build": summary[-500:]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="pipeline.py",
        description="Extract, validate, triage and ROI in one call.")
    ap.add_argument("--sources", nargs="*", default=None,
                    help="PDFs, videos, audio, or directories to extract (batch mode)")
    ap.add_argument("--cards", default=None,
                    help="an existing deck (.json or .jsonl) to gate instead of extracting")
    ap.add_argument("--out", required=True, help="work directory for this topic")
    ap.add_argument("--deck-name", default=None,
                    help="deck name for --build and the summary")
    ap.add_argument("--manifest-full", action="store_true",
                    help="list every image path in the manifest (diagnosis only)")
    ap.add_argument("--images", choices=("yes", "no"), default="no",
                    help="extract frames from local/video sources")
    ap.add_argument("--model", default="auto", help="local Whisper model or auto")
    ap.add_argument("--language", default="en", help="local language, or auto")
    ap.add_argument("--force-transcribe", action="store_true")
    ap.add_argument("--build", action="store_true",
                    help="build and validate the .apkg after gates")
    ap.add_argument("--out-apkg", default=None)
    ap.add_argument("--media", action="store_true")
    ap.add_argument("--media-root", default=None)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--per-topic", type=int, default=1)
    ap.add_argument("--max", dest="max_total", type=int, default=12)
    ap.add_argument("--gates-only", action="store_true",
                    help="skip extraction; just validate/triage/ROI the --cards deck")
    args = ap.parse_args(argv)

    errors, warnings = preflight()
    for warning in warnings:
        print(f"pipeline.py: warn: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"pipeline.py: {error}", file=sys.stderr)
        return 2
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
        media_sources = [s for s in args.sources if _is_media_source(s)]
        doc_sources = [s for s in args.sources if s not in media_sources]
        if media_sources:
            med = stage_media(media_sources, out, args.images, args.model,
                              args.language, args.force_transcribe)
            lines.append(f"media      {med['videos']} source(s), {med['chunks']} chunks"
                         + (f", {med['failed']} FAILED" if med['failed'] else ""))
            if med["failed"] and not med["videos"]:
                print("\n".join(lines))
                return 1
        if doc_sources:
            ex = stage_extract(doc_sources, out, args.manifest_full)
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
        if args.build:
            if not args.deck_name:
                print("pipeline.py: --build requires --deck-name", file=sys.stderr)
                return 2
            if g["errors"]:
                print("pipeline.py: refusing --build while validation errors remain",
                      file=sys.stderr)
                return 1
            target = (Path(args.out_apkg) if args.out_apkg else
                      Path.cwd() / f"{Path(args.cards).stem}.apkg")
            b = stage_build(Path(args.cards), out, args.deck_name,
                            target, args.media, args.media_root, args.strict)
            if b["ok"]:
                lines.append(f"build      {b['apkg']}")
                if b.get("build"):
                    lines.append(f"build-info {b['build']}")
                lines.append(f"validate   {b['validation']}")
            else:
                lines.append(f"build      FAILED: {b['error']}")
                return 1

    print("\n".join(lines))
    # Exit non-zero on a validation error so a caller can branch without parsing text.
    return 1 if (g and g["errors"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
