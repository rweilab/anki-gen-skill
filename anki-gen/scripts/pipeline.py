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

Media sources are processed one at a time with progress and `pipeline_state.json`;
`--resume` skips completed sources. A corpus too large for one context still belongs in
separate runs, not one giant context.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cardid import load_cards                       # noqa: E402
from preflight import check as preflight            # noqa: E402

STATE_FILE = "pipeline_state.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _load_state(out: Path) -> dict:
    try:
        return json.loads((out / STATE_FILE).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(out: Path, state: dict) -> None:
    state["updated_at"] = _now()
    path = out / STATE_FILE
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)


def _mark(out: Path, stage: str, status: str, **fields) -> None:
    state = _load_state(out)
    state["stage"] = stage
    state["status"] = status
    state.update(fields)
    _write_state(out, state)


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


def _run_media(cmd: list[str], log: Path) -> int:
    """Run a media child, showing its progress while keeping the full log."""
    with log.open("w") as handle:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="", flush=True)
            handle.write(line)
            handle.flush()
        return proc.wait()


def stage_media(sources: list[str], out: Path, images: str, model: str,
                language: str, force: bool, whole_playlist: bool = False,
                items: str = "", title: str = "", device: str = "cpu",
                initial_prompt: str | None = None,
                resume: bool = False) -> dict:
    """Transcribe local/URL media one source at a time with progress and resume."""
    from media_transcribe import is_media, media_files
    units = []
    for source in sources:
        path = Path(source[7:] if source.startswith("file://") else source)
        if path.is_dir():
            units.extend(str(p.resolve()) for p in media_files(str(path)))
        elif path.is_file() and is_media(path):
            units.append(str(path.resolve()))
        else:
            units.append(source)
    state = _load_state(out)
    media = state.setdefault("media", {})
    # A previous run cannot still be alive when this one starts. Mark its
    # running entry as interrupted so --status and --resume tell the truth.
    for prior in media.values():
        if prior.get("status") == "running":
            prior["status"] = "interrupted"
            prior["finished_at"] = _now()
            prior.setdefault("error", "previous run was interrupted")
    all_videos, all_failures = [], []
    chunks = failed = 0
    for index, source in enumerate(units, 1):
        key = source
        prior = media.get(key) or {}
        if resume and prior.get("status") == "done":
            all_videos.extend(prior.get("videos") or [])
            all_failures.extend(prior.get("failures") or [])
            chunks += int(prior.get("chunks") or 0)
            print(f"[media {index}/{len(units)}] resume skip {Path(source).name}",
                  flush=True)
            continue
        media[key] = {"status": "running", "started_at": _now(),
                      "index": index, "total": len(units),
                      "videos_done": 0, "videos_total": 0}
        state["stage"] = "media"
        state["status"] = "running"
        state["source"] = key
        state["source_index"] = index
        state["source_total"] = len(units)
        _write_state(out, state)
        print(f"[media {index}/{len(units)}] start {Path(source).name}",
              flush=True)
        log = out / "logs" / f"media-{index:02d}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(Path(__file__).with_name("extract_video.py")),
               source, "--work", str(out), "--images", images,
               "--model", model, "--language", language, "--device", device]
        if whole_playlist:
            cmd.append("--whole-playlist")
        if items:
            cmd += ["--items", items]
        if title and len(units) == 1:
            cmd += ["--title", title]
        if initial_prompt:
            cmd += ["--initial-prompt", initial_prompt]
        if force:
            cmd.append("--force-transcribe")
        if resume:
            cmd.append("--resume")
        code = _run_media(cmd, log)
        if code != 0:
            failed += 1
            media[key] = {"status": "failed", "finished_at": _now(),
                          "log": str(log), "error": _tail(log),
                          "videos_done": 0, "videos_total": 0}
            state["status"] = "failed"
            _write_state(out, state)
            print(f"[media {index}/{len(units)}] failed; log {log}", flush=True)
            continue
        try:
            meta = json.loads((out / "video_meta.json").read_text())
            videos = [json.loads(line) for line in
                      (out / "videos.jsonl").read_text().splitlines()
                      if line.strip()]
        except (OSError, json.JSONDecodeError):
            failed += 1
            media[key] = {"status": "failed", "finished_at": _now(),
                          "log": str(log), "error": "missing video output",
                          "videos_done": 0, "videos_total": 0}
            state["status"] = "failed"
            _write_state(out, state)
            print(f"[media {index}/{len(units)}] failed; no video output",
                  flush=True)
            continue
        failures = list(meta.get("failures") or [])
        status = "partial" if failures else "done"
        media[key] = {"status": status, "finished_at": _now(), "log": str(log),
                      "videos": videos, "chunks": int(meta.get("chunks") or 0),
                      "failures": failures,
                      "videos_done": len(videos) - len(failures),
                      "videos_total": len(videos)}
        all_videos.extend(videos)
        all_failures.extend(failures)
        chunks += int(meta.get("chunks") or 0)
        state["status"] = "partial" if failures else "running"
        _write_state(out, state)
        print(f"[media {index}/{len(units)}] {len(videos)} video(s), "
              f"{len(failures)} failed", flush=True)
    if all_videos:
        (out / "videos.jsonl").write_text("".join(
            json.dumps(v, ensure_ascii=False) + "\n" for v in all_videos))
        (out / "video_meta.json").write_text(json.dumps(
            {"videos": all_videos, "chunks": chunks,
             "failures": all_failures}, indent=2) + "\n")
        toc = ["# Video source map", ""]
        for video in all_videos:
            toc += [f"## {video.get('title', video.get('id', ''))}",
                    f"- id: {video.get('id', '')}",
                    f"- {video.get('source_label', '')} @ 00:00"]
            if video.get("source_url"):
                toc.append(f"- {video['source_url']}")
            toc += [f"- cues: {video.get('cues', 0)}", ""]
        if all_failures:
            toc.append("## Skipped")
            toc += [f"- {f.get('id', '')} — {f.get('reason', '')} — "
                    f"{f.get('title', '')}" for f in all_failures]
            toc.append("")
        (out / "video_toc.md").write_text("\n".join(toc))
        try:
            from extract_video import write_combined_transcripts
            write_combined_transcripts(out, all_videos)
        except Exception as e:
            print(f"pipeline.py: could not merge transcripts: {e}",
                  file=sys.stderr)
    state["stage"] = "media"
    state["status"] = ("failed" if failed else
                       "partial" if all_failures else "done")
    state["media_failed"] = len(all_failures) + failed
    _write_state(out, state)
    return {"videos": len(all_videos), "chunks": chunks,
            "failed": failed + len(all_failures)}


def _tail(path: Path, limit: int = 300) -> str:
    try:
        return path.read_text()[-limit:].strip()
    except OSError:
        return ""



def _write_sources_md(out: Path, manifest: dict) -> None:
    blocks = ["# Sources", "",
              "Read once when classifying; use a per-source file for a narrow check.",
              ""]
    for source in manifest["sources"]:
        if source.get("error") or not source.get("md"):
            continue
        md = out / source["md"]
        body = md.read_text() if md.is_file() else ""
        blocks += [f"## {source['tag']} — {source.get('source_path', '')}", "",
                   body.strip(), ""]
    (out / "sources.md").write_text("\n".join(blocks))


def stage_extract(sources: list[str], out: Path, manifest_full: bool,
                  date_filter: str | None = None,
                  page_crops: str = "auto") -> dict:
    from extract_pdf import run_batch

    manifest = run_batch(sources, out, date_filter, manifest_full, page_crops)
    _write_sources_md(out, manifest)
    ok = [s for s in manifest["sources"] if not s.get("error")]
    chars = sum(s.get("chars", 0) for s in ok)
    figs = sum(s.get("images", 0) if isinstance(s.get("images"), int) else 0 for s in ok)
    return {"sources": len(ok), "failed": len(manifest["failed"]),
            "chars": chars, "figures": figs, "manifest": manifest}


def _roi_risks(text: str) -> tuple[list[int], int]:
    split_cards: list[int] = []
    restatements = 0
    if "SPLIT CANDIDATES" in text:
        section = text.split("SPLIT CANDIDATES", 1)[1].split("\n\n", 1)[0]
        split_cards = [int(n) for n in re.findall(r"^\s+card\s+(\d+)", section, re.M)]
    match = re.search(r"RESTATEMENT FLAGS\s+—\s+(\d+)", text)
    if match:
        restatements = int(match.group(1))
    return split_cards, restatements


def stage_gates(cards_path: Path, out: Path, per_topic: int, max_total: int) -> dict:
    """Validate, triage and ROI on the written deck. Consumes the FILE, returns counts."""
    from validate_cards import check_cards
    from triage import select, build_plan
    from media_index import audit_cards
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
    split_cards, restatements = _roi_risks(buf.getvalue())
    media_risks = audit_cards(cards, out)

    return {"cards": len(cards), "errors": len(errs), "warnings": len(warns),
            "selected": len(entries), "total": len(cards),
            "plan": plan_path, "roi": roi_path,
            "roi_split": split_cards, "roi_restatements": restatements,
            "media_risks": media_risks}


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


def _vision_candidates(rows: list[dict]) -> list[dict]:
    """Only ambiguous frames need a vision call; direct frames are attachable."""
    return [r for r in rows
            if r.get("best") and r.get("attach") == "confirm"
            and (r.get("canonical", True))
            and r.get("local_kind") not in ("likely_code", "likely_webpage")]


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
    candidates = _vision_candidates(rows)
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
    ap.add_argument("--resume", action="store_true",
                    help="skip media sources already marked done in pipeline_state.json")
    ap.add_argument("--status", action="store_true",
                    help="print the last pipeline state and exit")
    ap.add_argument("--allow-media-risk", action="store_true",
                    help="build despite media risks (diagnosis only)")
    ap.add_argument("--vision", choices=("off", "auto"), default="off",
                    help="opt-in bounded vision pass over confirm frames")
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
    if args.status:
        state = _load_state(out)
        if not state:
            print("no pipeline state")
            return 0
        try:
            meta = json.loads((out / "video_meta.json").read_text())
        except (OSError, json.JSONDecodeError):
            meta = {}
        videos = list(meta.get("videos") or [])
        failures = list(meta.get("failures") or [])
        current = state.get("source")
        for key, entry in state.get("media", {}).items():
            if key == current and entry.get("status") in (
                    "running", "partial", "failed"):
                entry["videos_done"] = max(0, len(videos) - len(failures))
                entry["videos_total"] = len(videos)
                entry["failures"] = failures
        print(json.dumps(state, indent=2))
        return 0
    _mark(out, "run", "running")

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
                              args.device, args.initial_prompt,
                              resume=args.resume)
            lines.append(f"media      {med['videos']} video(s), {med['chunks']} chunks"
                         + (f", {med['failed']} FAILED" if med['failed'] else ""))
            if med["failed"] and not med["videos"]:
                print("\n".join(lines))
                return 1
        if doc_sources:
            _mark(out, "extract", "running", sources=doc_sources)
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
            _mark(out, "extract", "done", sources=len(ex["manifest"]["sources"]),
                  failed=ex["failed"])
        if args.vision == "auto":
            v = stage_vision(out, args.vision_max, args.vision_seconds,
                             args.vision_timeout)
            if v.get("error"):
                lines.append(f"vision     skipped: {v['error']}")
            else:
                lines.append(f"vision     {v['checked']} checked, "
                             f"{v.get('stopped') or 'ok'}, report {_short(v['report'], root)}")
        reads = []
        if doc_sources:
            reads.append("sources.md")
        if media_sources:
            reads.append("transcripts.md")
        lines.append(f"NEXT       read {' and '.join(reads) or 'the extracts'} "
                     "once, classify, write authoring_ledger.md before "
                     "cards.jsonl (stage 5 -> 7); re-run with --cards for the gates")

    g = None
    if args.cards:
        _mark(out, "gates", "running")
        g = stage_gates(Path(args.cards), out, args.per_topic, args.max_total)
        _mark(out, "gates", "done", cards=g["cards"], errors=g["errors"],
              warnings=g["warnings"], media_risks=len(g["media_risks"]),
              roi_split=len(g["roi_split"]))
        lines.append(f"gates      {g['cards']} card(s): {g['errors']} error(s), "
                     f"{g['warnings']} warning(s)")
        lines.append(f"triage     {g['selected']} of {g['total']} selected -> "
                     f"{_short(g['plan'], root)}")
        lines.append(f"roi        {_short(g['roi'], root)}")
        if g["roi_split"]:
            shown = ", ".join(str(card) for card in g["roi_split"][:8])
            lines.append(f"roi-split  {len(g['roi_split'])} candidate(s): {shown}")
        if g["media_risks"]:
            shown = "; ".join(
                f"card {risk['card']} {risk['risk']}"
                for risk in g["media_risks"][:8])
            lines.append(f"media      {len(g['media_risks'])} risk(s): {shown}")
        lines.append(evidence_line(load_cards(Path(args.cards)), out))
        review_logs = list(out.glob("review_feedback*.jsonl"))
        review = "review log present (sample only)" if review_logs else "review not run"
        status = "NOT READY" if g["errors"] else "NOT CERTIFIED"
        lines.append(f"quality    static {g['errors']} error(s); "
                     f"media {len(g['media_risks'])} risk(s); "
                     f"roi {len(g['roi_split'])} split(s); {review}; {status}")
        if args.deck_name:
            lines.append(f"deck-name  {args.deck_name}")
        if args.build:
            if g["media_risks"] and not args.allow_media_risk:
                print("pipeline.py: refusing --build: media risks remain. Fix "
                      "them or pass --allow-media-risk for diagnosis.", file=sys.stderr)
                return 1
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
            _mark(out, "build", "running", target=str(target))
            b = stage_build(Path(args.cards), out, args.deck_name,
                            target, args.media, args.media_root, args.strict,
                            args.merge_existing)
            if b["ok"]:
                _mark(out, "build", "done", target=b["apkg"])
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
                _mark(out, "build", "failed", error=b["error"])
                lines.append(f"build      FAILED: {b['error']}")
                return 1

    print("\n".join(lines))
    # Exit non-zero on a validation error so a caller can branch without parsing text.
    return 1 if (g and g["errors"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
