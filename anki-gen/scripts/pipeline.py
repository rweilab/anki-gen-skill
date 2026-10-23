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
    pipeline.py --sources Lec/*.pdf --work .anki-gen-temp/midterm1
    pipeline.py --cards cards.jsonl --work .anki-gen-temp/midterm1 --gates-only
    pipeline.py --sources "https://youtube.com/playlist?list=..." --work "$WORK" \
        --images yes --vision auto --vision-max 12

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


def _media_images(sources: list[str], mode: str) -> str:
    if mode != "auto":
        return mode
    from media_transcribe import is_media, kind, media_files
    for source in sources:
        path = Path(source[7:] if source.startswith("file://") else source)
        if path.is_file():
            if is_media(path) and kind(path) == "video":
                return "yes"
        elif path.is_dir():
            if any(kind(p) == "video" for p in media_files(str(path))):
                return "yes"
        else:
            return "yes"
    return "no"


def stage_media(sources: list[str], out: Path, images: str, model: str,
                language: str, force: bool, whole_playlist: bool = False,
                items: str = "", title: str = "", device: str = "cpu",
                initial_prompt: str | None = None) -> dict:
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
    remote = [s for s in sources
              if not Path(s[7:] if s.startswith("file://") else s).exists()]
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
        sources = [str(batch)] + remote
    try:
        chunks = failed = 0
        all_videos: list[dict] = []
        all_failures: list[dict] = []
        for source in sources:
            cmd = [sys.executable, str(Path(__file__).with_name("extract_video.py")),
                   source, "--work", str(out), "--images", images,
                   "--model", model, "--language", language, "--device", device]
            if whole_playlist:
                cmd.append("--whole-playlist")
            if items:
                cmd += ["--items", items]
            if title:
                cmd += ["--title", title]
            if initial_prompt:
                cmd += ["--initial-prompt", initial_prompt]
            if force:
                cmd.append("--force-transcribe")
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                failed += 1
                print(f"pipeline.py: media failed for {source}: {r.stderr[-300:]}",
                      file=sys.stderr)
                continue
            try:
                meta = json.loads((out / "video_meta.json").read_text())
                chunks += int(meta.get("chunks") or 0)
                all_failures.extend(meta.get("failures") or [])
                all_videos.extend(
                    json.loads(line) for line in
                    (out / "videos.jsonl").read_text().splitlines() if line.strip())
            except (OSError, json.JSONDecodeError):
                failed += 1
        # Each child writes its own videos.jsonl / video_toc.md / video_meta.json.
        # With more than one source those files held only the last child. Merge
        # what succeeded so the source map and citations stay complete.
        if len(sources) > 1:
            (out / "videos.jsonl").write_text("".join(
                json.dumps(v, ensure_ascii=False) + "\n" for v in all_videos))
            toc = ["# Video source map", ""]
            for v in all_videos:
                toc += [f"## {v.get('title', v.get('id', ''))}",
                        f"- id: {v.get('id', '')}",
                        f"- {v.get('source_label', '')} @ 00:00"]
                if v.get("source_url"):
                    toc.append(f"- {v['source_url']}")
                toc += [f"- cues: {v.get('cues', 0)}", ""]
            if all_failures:
                toc.append("## Skipped")
                toc += [f"- {f.get('id', '')} — {f.get('reason', '')} — "
                        f"{f.get('title', '')}" for f in all_failures]
                toc.append("")
            (out / "video_toc.md").write_text("\n".join(toc))
            (out / "video_meta.json").write_text(json.dumps(
                {"videos": all_videos, "chunks": chunks,
                 "failures": all_failures}, indent=2) + "\n")
            try:
                from extract_video import write_combined_transcripts
                write_combined_transcripts(out, all_videos)
            except Exception as e:
                print(f"pipeline.py: could not merge transcripts: {e}",
                      file=sys.stderr)
        return {"videos": len(all_videos), "chunks": chunks, "failed": failed}
    finally:
        if cleanup:
            cleanup.cleanup()


def stage_extract(sources: list[str], out: Path, manifest_full: bool,
                  date_filter: str | None = None,
                  page_crops: str = "auto") -> dict:
    from extract_pdf import run_batch

    manifest = run_batch(sources, out, date_filter, manifest_full, page_crops)
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
                media: bool, media_root: str | None, strict: bool,
                merge_existing: str | None = None) -> dict:
    """Build and validate the package in one process, returning a compact result."""
    target = apkg or (out / "deck.apkg")
    cmd = [sys.executable, str(Path(__file__).with_name("build_apkg.py")),
           str(cards_path), str(target), "--deck-name", deck_name]
    if media:
        cmd += ["--media", "--media-root", str(media_root or cards_path.parent)]
    if merge_existing:
        cmd += ["--merge-existing", merge_existing]
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


def stage_context(out: Path, cards_path: Path, deck_name: str,
                  profile: str = "") -> dict:
    """Persist the compact dossier before stage 14 deletes the work tree."""
    from deck_context import pack
    return pack(out, {"deck_name": deck_name, "profile": profile},
                cards_path=cards_path)


def stage_vision(out: Path, max_n: int, max_seconds: float,
                 timeout: float) -> dict:
    """One bounded vision pass over canonical frames; report is work-local."""
    frames_path = out / "frames.jsonl"
    if not frames_path.is_file():
        return {"checked": 0, "stopped": "", "error": "no frames.jsonl"}
    rows = []
    try:
        rows = [json.loads(line) for line in frames_path.read_text().splitlines()
                if line.strip()]
    except json.JSONDecodeError:
        return {"checked": 0, "stopped": "", "error": "bad frames.jsonl"}
    candidates = [
        r for r in rows
        if r.get("best") and r.get("attach") in ("direct", "confirm")
        and (r.get("canonical", True))
        and r.get("local_kind") not in ("likely_code", "likely_webpage")
    ]
    if not candidates:
        return {"checked": 0, "stopped": "", "error": "no canonical frames"}
    candidates.sort(key=lambda r: ({"high": 0, "medium": 1}.get(
        r.get("quality"), 2), r.get("time", 0)))
    script = (Path(__file__).resolve().parents[2] / "image-vision" /
              "scripts" / "vision_check.py")
    if not script.is_file():
        return {"checked": 0, "stopped": "", "error": f"missing {script}"}
    paths = [str(out / r["file"]) for r in candidates[:max(1, max_n)]]
    report = out / "vision.jsonl"
    cmd = [sys.executable, str(script), *paths, "--report", str(report),
           "--max", str(max(1, max_n)), "--max-seconds", str(max_seconds),
           "--timeout", str(timeout), "--mode", "frame"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    summary = {}
    for line in reversed(r.stdout.splitlines()):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "checked" in obj:
            summary = obj
            break
    if r.returncode != 0 and not summary:
        return {"checked": 0, "stopped": "",
                "error": (r.stderr or r.stdout)[-300:]}
    return {"checked": summary.get("checked", 0),
            "stopped": summary.get("stopped", ""),
            "errors": summary.get("errors", 0),
            "report": str(report)}


ARTIFACTS = ("intake.md", "scope_gate.md", "authoring_ledger.md")


def artifact_state(out: Path) -> dict[str, bool]:
    """Which mandatory evidence files exist and are non-empty."""
    return {name: (out / name).is_file() and (out / name).stat().st_size > 0
            for name in ARTIFACTS}


def evidence_line(cards: list[dict], out: Path) -> str:
    """A compact, human-readable evidence summary; no card text."""
    arts = artifact_state(out)
    prov = sum(1 for c in cards
               if str(c.get("source") or c.get("source_ref") or "").strip()
               and any(ch.isdigit() for ch in str(c.get("source") or "")))
    tz_topics = {str(c.get("topic") or "") for c in cards if c.get("tier_zero")}
    topics = {str(c.get("topic") or "") for c in cards}
    media = sum(1 for c in cards if c.get("media"))
    flags = " ".join(f"{name.replace('.md', '')}={'ok' if ok else 'MISSING'}"
                     for name, ok in arts.items())
    return (f"evidence   {flags} | provenance {prov}/{len(cards)} | "
            f"tier-zero {len(tz_topics)}/{len(topics)} topic(s) | image cards {media}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="pipeline.py",
        description="Extract, validate, triage and ROI in one call.")
    ap.add_argument("--sources", nargs="*", default=None,
                    help="PDFs, videos, audio, or directories to extract (batch mode)")
    ap.add_argument("--cards", default=None,
                    help="an existing deck (.json or .jsonl) to gate instead of extracting")
    ap.add_argument("--out", default=None, help="work directory for this topic")
    ap.add_argument("--work", default=None, help="alias for --out (work directory)")
    ap.add_argument("--deck-name", default=None,
                    help="deck name for --build and the summary")
    ap.add_argument("--manifest-full", action="store_true",
                    help="list every image path in the manifest (diagnosis only)")
    ap.add_argument("--images", choices=("yes", "no", "auto"), default="auto",
                    help="extract frames from video sources; auto enables them for video")
    ap.add_argument("--model", default="auto", help="local Whisper model or auto")
    ap.add_argument("--language", default="en", help="local language, or auto")
    ap.add_argument("--device", default="cpu", help="local Whisper device")
    ap.add_argument("--initial-prompt", default=None,
                    help="optional course terms for local transcription")
    ap.add_argument("--force-transcribe", action="store_true")
    ap.add_argument("--whole-playlist", action="store_true")
    ap.add_argument("--items", default="", help="playlist range, e.g. 2-5 or 2,4")
    ap.add_argument("--title", default="", help="local recording title")
    ap.add_argument("--date-filter", default=None,
                    help="directory sources newer than this, e.g. 'last week'")
    ap.add_argument("--page-crops", choices=("auto", "all", "off"), default="auto",
                    help="PDF/slide figure page crops (default: auto)")
    ap.add_argument("--merge-existing", default=None,
                    help="existing .apkg to merge into (idempotent by card hash)")
    ap.add_argument("--build", action="store_true",
                    help="build and validate the .apkg after gates")
    ap.add_argument("--out-apkg", default=None)
    ap.add_argument("--media", action="store_true")
    ap.add_argument("--media-root", default=None)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--allow-missing-artifacts", action="store_true",
                    help="build without intake.md/scope_gate.md/authoring_ledger.md "
                         "(draft or diagnosis only)")
    ap.add_argument("--no-context", action="store_true",
                    help="do not persist the deck dossier after a successful build")
    ap.add_argument("--anki-profile", default="",
                    help="Anki profile name to record in the deck dossier")
    ap.add_argument("--per-topic", type=int, default=1)
    ap.add_argument("--max", dest="max_total", type=int, default=12)
    ap.add_argument("--gates-only", action="store_true",
                    help="skip extraction; just validate/triage/ROI the --cards deck")
    ap.add_argument("--vision", choices=("off", "auto"), default="off",
                    help="opt-in bounded vision pass over canonical frames")
    ap.add_argument("--vision-max", type=int, default=12)
    ap.add_argument("--vision-seconds", type=float, default=180)
    ap.add_argument("--vision-timeout", type=float, default=20)
    args = ap.parse_args(argv)

    errors, warnings = preflight()
    for warning in warnings:
        print(f"pipeline.py: warn: {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"pipeline.py: {error}", file=sys.stderr)
        return 2
    if not args.out and not args.work:
        print("pipeline.py: pass --work (or --out) as the work directory",
              file=sys.stderr)
        return 2
    out_arg = args.work or args.out
    if str(out_arg).lower().endswith(".apkg"):
        print("pipeline.py: --work/--out is a work directory, not the .apkg; "
              "use --out-apkg for the deck", file=sys.stderr)
        return 2
    out = Path(out_arg)
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
            med = stage_media(media_sources, out,
                              _media_images(media_sources, args.images),
                              args.model, args.language, args.force_transcribe,
                              args.whole_playlist, args.items, args.title,
                              args.device, args.initial_prompt)
            lines.append(f"media      {med['videos']} source(s), {med['chunks']} chunks"
                         + (f", {med['failed']} FAILED" if med['failed'] else ""))
            if med["failed"] and not med["videos"]:
                print("\n".join(lines))
                return 1
        if doc_sources:
            ex = stage_extract(doc_sources, out, args.manifest_full,
                               args.date_filter, args.page_crops)
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
            for s in ex["manifest"]["sources"]:
                if s.get("warning"):
                    lines.append(f"           ! {s['tag']}: {s['warning']}")
        if args.vision == "auto":
            v = stage_vision(out, args.vision_max, args.vision_seconds,
                             args.vision_timeout)
            if v.get("error"):
                lines.append(f"vision     skipped: {v['error']}")
            else:
                lines.append(f"vision     {v['checked']} checked, "
                             f"{v.get('stopped') or 'ok'}, report {_short(v['report'], root)}")
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
        lines.append(evidence_line(load_cards(Path(args.cards)), out))
        if args.deck_name:
            lines.append(f"deck-name  {args.deck_name}")
        if args.build:
            if not args.deck_name:
                print("pipeline.py: --build requires --deck-name", file=sys.stderr)
                return 2
            missing = [name for name, ok in artifact_state(out).items() if not ok]
            if missing and not args.allow_missing_artifacts:
                print("pipeline.py: refusing --build: missing required evidence "
                      f"({', '.join(missing)}). Write them in {out} or pass "
                      "--allow-missing-artifacts for a draft.", file=sys.stderr)
                return 2
            if g["errors"]:
                print("pipeline.py: refusing --build while validation errors remain",
                      file=sys.stderr)
                return 1
            target = (Path(args.out_apkg) if args.out_apkg else
                      Path.cwd() / f"{Path(args.cards).stem}.apkg")
            b = stage_build(Path(args.cards), out, args.deck_name,
                            target, args.media, args.media_root, args.strict,
                            args.merge_existing)
            if b["ok"]:
                lines.append(f"build      {b['apkg']}")
                if b.get("build"):
                    lines.append(f"build-info {b['build']}")
                lines.append(f"validate   {b['validation']}")
                if not args.no_context:
                    try:
                        c = stage_context(out, Path(args.cards), args.deck_name, args.anki_profile)
                        lines.append(f"context    {c['cards']} card(s) -> {c['path']}")
                    except Exception as e:
                        print(f"pipeline.py: warn: deck context not persisted: {e}",
                              file=sys.stderr)
            else:
                lines.append(f"build      FAILED: {b['error']}")
                return 1

    print("\n".join(lines))
    # Exit non-zero on a validation error so a caller can branch without parsing text.
    return 1 if (g and g["errors"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
