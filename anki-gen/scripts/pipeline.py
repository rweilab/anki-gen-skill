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
It does the mechanical work: extract, validate, triage, ROI, and the review
summary/actions skeleton. It prints a summary and the paths, and **nothing else belongs
in context** -- read the artifacts by path when a later stage needs one.

It does NOT classify or write cards. Those are judgements, and they stay with the model
(see the SKILL.md authoring step). This script's job is to make the mechanical half cost one
step instead of twenty.

Usage
-----
    pipeline.py --sources Lec/*.pdf --work .anki-gen-temp/midterm1
    pipeline.py --cards cards.jsonl --work .anki-gen-temp/midterm1 --gates-only

Media sources are processed one at a time with progress and `pipeline_state.json`;
`--resume` skips completed sources. A corpus too large for one context still belongs in
separate runs, not one giant context.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cardid import card_hash, last_row_per_card, load_cards  # noqa: E402
from preflight import check as preflight            # noqa: E402
from validate_cards import fix_for                   # noqa: E402

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


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _extract_busy(out: Path) -> bool:
    """A live extraction in this work dir; stale state is not a lock."""
    state = _load_state(out)
    if state.get("status") != "running" or state.get("stage") not in ("extract", "media"):
        return False
    pid = state.get("pid")
    return bool(pid) and int(pid) != os.getpid() and _pid_alive(pid)


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


DOC_SUFFIXES = {".pdf", ".pptx", ".txt", ".md", ".tex", ".html", ".htm"}


def _split_sources(sources: list[str],
                   exclude: Path | None = None) -> tuple[list[str], list[str]]:
    """Expand a mixed directory into media and document files.

    A directory containing both a recording and a PDF used to be classified as
    media-only, so the PDF silently disappeared. Pure media or pure document
    directories keep their existing batch path. `exclude` keeps the work dir out
    when the caller passes a course root that contains it.
    """
    exclude = exclude.resolve() if exclude else None

    def allowed(path: Path) -> bool:
        if not exclude:
            return True
        try:
            path.resolve().relative_to(exclude)
            return False
        except ValueError:
            return True

    media, docs = [], []
    for source in sources:
        path = Path(source[7:] if source.startswith("file://") else source)
        if not allowed(path):
            continue
        if path.is_dir():
            files = [p for p in path.rglob("*") if p.is_file() and allowed(p)]
            media_files = [p for p in files if _is_media_source(str(p))]
            doc_files = [p for p in files if p.suffix.lower() in DOC_SUFFIXES]
            if media_files and doc_files:
                media.extend(str(p) for p in media_files)
                docs.extend(str(p) for p in doc_files)
            elif media_files:
                media.extend(str(p) for p in media_files)
            elif doc_files and exclude:
                docs.extend(str(p) for p in doc_files)
            else:
                docs.append(source)
        elif _is_media_source(source):
            media.append(source)
        else:
            docs.append(source)
    return media, docs


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
    path = out / "sources.md"
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text("\n".join(blocks))
    tmp.replace(path)
    (out / "sources.ready").write_text(_now() + "\n")


def stage_extract(sources: list[str], out: Path,
                  date_filter: str | None = None,
                  page_crops: str = "auto") -> dict:
    from extract_pdf import run_batch

    manifest = run_batch(sources, out, date_filter, False, page_crops)
    _write_sources_md(out, manifest)
    ok = [s for s in manifest["sources"] if not s.get("error")]
    chars = sum(s.get("chars", 0) for s in ok)
    figs = sum(s.get("images", 0) if isinstance(s.get("images"), int) else 0 for s in ok)
    return {"sources": len(ok), "failed": len(manifest["failed"]),
            "chars": chars, "figures": figs, "manifest": manifest}



REVIEW_ACTIONS = "review_actions.json"
LEGACY_REVIEW_ACTIONS = "review_actions.md"


def _feedback_paths(out: Path) -> list[Path]:
    """Scale review logs plus the optional recall pass."""
    paths = [p for p in sorted(out.glob("review_feedback*.jsonl"))
             if p.is_file() and p.stat().st_size > 0]
    recall = out / "review_recall.jsonl"
    if recall.is_file() and recall.stat().st_size > 0:
        paths.append(recall)
    return paths


def _feedback_rows(out: Path) -> tuple[list[dict], list[dict]]:
    """Last row per card for the scale and recall logs, separately."""
    scale: dict[str, dict] = {}
    recall: dict[str, dict] = {}
    for path in _feedback_paths(out):
        rows = []
        try:
            rows = [json.loads(line) for line in path.read_text().splitlines()
                    if line.strip()]
        except (OSError, json.JSONDecodeError):
            continue
        target = recall if "recall" in path.name else scale
        target.update(last_row_per_card(rows))
    return list(scale.values()), list(recall.values())


def _card_number(row: dict, cards: list[dict], by_hash: dict[str, int]) -> int | None:
    h = str(row.get("hash") or "")
    if h in by_hash:
        return by_hash[h]
    n = row.get("n", row.get("i"))
    if isinstance(n, int) and 1 <= n <= len(cards):
        return n
    return None


def _feedback_sha(out: Path) -> str:
    digest = hashlib.sha256()
    for path in _feedback_paths(out):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _review_actions_doc(cards: list[dict], plan: dict, out: Path,
                        scale_rows: list[dict], recall_rows: list[dict]) -> dict:
    by_hash = {card_hash(c): i for i, c in enumerate(cards, 1)}
    score5, score1, score4, kept = [], {}, [], []
    for row in scale_rows:
        n = _card_number(row, cards, by_hash)
        if n is None:
            continue
        score = row.get("score")
        comment = str(row.get("comment") or "").strip()
        if score == 5:
            score5.append({"card": n, "hash": card_hash(cards[n - 1]),
                           "reason": comment})
        elif score == 1:
            c = cards[n - 1]
            key = (str(c.get("topic") or ""), str(c.get("stratum") or ""),
                   str(c.get("kc") or ""))
            score1.setdefault(key, {"cards": [], "comments": []})
            score1[key]["cards"].append(n)
            if comment:
                score1[key]["comments"].append(f"{n}: {comment}")
        elif score == 4:
            score4.append({"card": n, "reason": comment, "decision": ""})
        elif score in (2, 3):
            kept.append(n)
    recalled_no = []
    for row in recall_rows:
        if row.get("recall") is False:
            n = _card_number(row, cards, by_hash)
            if n is not None:
                recalled_no.append(n)

    done = {}
    try:
        done = json.loads((out / "review_done").read_text())
    except (OSError, json.JSONDecodeError):
        pass
    deck_note = str(done.get("deck_note") or "").strip()

    groups = []
    for (topic, stratum, kc), item in sorted(score1.items()):
        groups.append({
            "cards": item["cards"],
            "topic": topic,
            "stratum": stratum,
            "kc": kc,
            "comments": item["comments"],
            "action": "",
            "target": "",
            "net_delta": 0,
        })
    return {
        "schema": 1,
        "status": "open",
        "feedback_sha": _feedback_sha(out),
        "deck_note": deck_note,
        "score1": groups,
        "score5": score5,
        "score4": score4,
        "recall_failures": [{"card": n} for n in recalled_no],
        "kept": kept,
        "second_round": plan.get("second_round") or {},
    }


VALID_REVIEW_ACTIONS = {"merge", "relevel", "replace", "keep anchor"}


def _score1_actions_complete(text: str) -> bool:
    """Legacy Markdown check: a resolved score-1 block must name a valid action/target."""
    in_score1 = False
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if re.match(r"^##\s+", line):
            if in_score1 and current:
                blocks.append(current)
                current = []
            in_score1 = bool(re.match(r"^##\s+Score\s+1\b", line, re.I))
            continue
        if not in_score1:
            continue
        if re.match(r"^\s*-\s*\[[ xX]\]", line):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if in_score1 and current:
        blocks.append(current)
    for block in blocks:
        body = "\n".join(block)
        action = re.search(r"(?mi)^\s*action:\s*(.+?)\s*$", body)
        target = re.search(r"(?mi)^\s*target:\s*(.+?)\s*$", body)
        if not action:
            return False
        if action.group(1).strip().strip("`").lower() not in VALID_REVIEW_ACTIONS:
            return False
        if not target or not target.group(1).strip():
            return False
    return True


def _legacy_review_actions_state(action: Path, paths: list[Path],
                                 cards_path: Path | None) -> dict:
    """Read a v1.5.6 review_actions.md; remove this branch at 2.0."""
    latest = max(p.stat().st_mtime for p in paths)
    text = action.read_text()
    match = re.search(r"(?mi)^status:\s*(\S+)", text)
    state = match.group(1).strip("`").lower() if match else "unset"
    if state != "resolved":
        return {"required": True, "state": state, "path": action, "legacy": True}
    if not _score1_actions_complete(text):
        return {"required": True, "state": "incomplete", "path": action, "legacy": True}
    if action.stat().st_mtime < latest:
        return {"required": True, "state": "stale", "path": action, "legacy": True}
    if cards_path is not None and cards_path.is_file():
        if action.stat().st_mtime < cards_path.stat().st_mtime:
            return {"required": True, "state": "stale", "path": action, "legacy": True}
    return {"required": True, "state": "resolved", "path": action, "legacy": True}


def review_actions_state(out: Path, cards_path: Path | None = None,
                         cards: list[dict] | None = None) -> dict:
    """Whether feedback requires a resolved action file, and whether it is current."""
    paths = _feedback_paths(out)
    if not paths:
        return {"required": False, "state": "not-run", "path": None, "legacy": False}
    action = out / REVIEW_ACTIONS
    legacy = out / LEGACY_REVIEW_ACTIONS
    if cards is None and cards_path is not None and cards_path.is_file():
        try:
            cards = load_cards(cards_path)
        except (OSError, ValueError, json.JSONDecodeError):
            cards = None

    if action.is_file():
        try:
            doc = json.loads(action.read_text())
        except (OSError, json.JSONDecodeError):
            return {"required": True, "state": "invalid", "path": action,
                    "legacy": False}
        state = str(doc.get("status") or "unset").lower()
        if state != "resolved":
            return {"required": True, "state": state, "path": action,
                    "legacy": False}
        if doc.get("feedback_sha") != _feedback_sha(out):
            return {"required": True, "state": "stale", "path": action,
                    "legacy": False}
        for item in doc.get("score1") or []:
            action_name = str(item.get("action") or "").strip().strip("`").lower()
            target = str(item.get("target") or "").strip()
            if action_name not in VALID_REVIEW_ACTIONS or not target:
                return {"required": True, "state": "incomplete", "path": action,
                        "legacy": False}
        hashes = {card_hash(c) for c in (cards or [])}
        for item in doc.get("score5") or []:
            if str(item.get("hash") or "") in hashes:
                return {"required": True, "state": "incomplete", "path": action,
                        "legacy": False}
        return {"required": True, "state": "resolved", "path": action,
                "legacy": False}

    if legacy.is_file():
        return _legacy_review_actions_state(legacy, paths, cards_path)

    return {"required": True, "state": "missing", "path": action, "legacy": False}


def _ensure_review_actions(out: Path, cards: list[dict], plan: dict,
                           cards_path: Path | None = None) -> dict:
    state = review_actions_state(out, cards_path, cards)
    if (state["required"] and state["state"] in ("missing", "stale")
            and not ((out / LEGACY_REVIEW_ACTIONS).is_file()
                     and not (out / REVIEW_ACTIONS).is_file())):
        scale_rows, recall_rows = _feedback_rows(out)
        doc = _review_actions_doc(cards, plan, out, scale_rows, recall_rows)
        (out / REVIEW_ACTIONS).write_text(json.dumps(doc, indent=2) + "\n")
        state = review_actions_state(out, cards_path, cards)
    return state


def _read_optional(path: Path) -> str:
    try:
        return path.read_text() if path.is_file() else ""
    except OSError:
        return ""


def _scope_section(text: str) -> str:
    match = re.search(r"(?ms)^##\s+Scope\s*$(.*?)(?=^##\s+|\Z)", text)
    return match.group(1).strip() if match else ""


def _scope_text(out: Path) -> str:
    intake = _read_optional(out / "intake.md")
    section = _scope_section(intake)
    if section:
        return "## Scope\n\n" + section + "\n"
    return _read_optional(out / "scope_gate.md")


def _intake_images(out: Path) -> str:
    """The intake's image decision, if it wrote one."""
    match = re.search(r"(?mi)^\s*-?\s*images\s*:\s*(yes|no)\b",
                      _read_optional(out / "intake.md"))
    return match.group(1).lower() if match else ""


def _extracted_figures(out: Path) -> int:
    """Figure count from extraction state, falling back to source manifests."""
    state = _load_state(out)
    count = (state.get("extract") or {}).get("figures")
    if isinstance(count, int):
        return count
    total = 0
    for path in out.glob("*/figures.json"):
        try:
            rows = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(rows, list):
            total += len(rows)
    return total


def write_review_packet(out: Path, cards: list[dict], plan: dict,
                        ledger_text: str | None) -> Path:
    """A compact, packet-only input for the optional adversarial reviewer.

    The reviewer sees selected cards, their KC rows/evidence, and the intake/scope
    context. It never receives the full deck or extracted corpus.
    """
    from validate_cards import parse_kc_map

    selected = list(plan.get("entries") or [])
    chosen = [cards[e["i"] - 1] for e in selected
              if isinstance(e.get("i"), int) and 1 <= e["i"] <= len(cards)]
    selected_kcs = {str(c.get("kc") or "").strip() for c in chosen
                    if str(c.get("kc") or "").strip()}
    kcs, _, _, _ = parse_kc_map(ledger_text or "")
    shown = set(selected_kcs)
    for kc_id in list(selected_kcs):
        shown.update(req for req in (kcs.get(kc_id) or {}).get("requires", [])
                     if req != "external" and req in kcs)

    lines = ["# Review packet", "",
             "Read only this packet. Do not open the full card deck or source corpus.",
             ""]
    intake = _read_optional(out / "intake.md")
    scope = "" if _scope_section(intake) else _read_optional(out / "scope_gate.md")
    if intake:
        lines += ["## Intake", "", intake.strip(), ""]
    if scope:
        lines += ["## Scope gate", "", scope.strip(), ""]
    if shown and kcs:
        header = "| kc_id | type | claim | source | evidence_quote | requires |"
        rule = "|---|---|---|---|---|---|"
        lines += ["## KCs", "", header, rule]
        for kc_id in sorted(shown):
            row = kcs.get(kc_id)
            if not row:
                continue
            req = ", ".join(row.get("requires") or []) or "—"
            quote = row.get("evidence_quote") or "—"
            lines.append(f"| {kc_id} | {row.get('type','')} | {row.get('claim','')} | "
                         f"{row.get('source','')} | {quote} | {req} |")
        lines.append("")

    lines += ["## Cards", ""]
    for e in selected:
        i = e.get("i")
        if not isinstance(i, int) or not 1 <= i <= len(cards):
            continue
        c = cards[i - 1]
        topic = str(c.get("topic") or "")
        stratum = str(c.get("stratum") or "")
        kc_id = str(c.get("kc") or "")
        lines += [f"### card {i} — {topic} / {stratum} / {kc_id}", "",
                  "Front:", str(c.get("front") or ""), "",
                  "Back:", str(c.get("back") or ""), "",
                  f"Source: {c.get('source') or c.get('source_ref') or ''}"]
        media = c.get("media") or []
        if media:
            lines.append("Media:")
            for m in media:
                if isinstance(m, dict):
                    lines.append(f"- {m.get('file','')} — {m.get('caption','')}")
                else:
                    lines.append(f"- {m}")
        if e.get("reasons"):
            lines.append("Why selected: " + "; ".join(map(str, e["reasons"])))
        lines.append("")

    path = out / "review_packet.md"
    path.write_text("\n".join(lines).rstrip() + "\n")
    return path


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


def stage_gates(cards_path: Path, out: Path) -> dict:
    """Validate, triage and ROI on the written deck. Consumes the FILE, returns counts."""
    from validate_cards import check_cards, parse_kc_map
    from triage import select, build_plan
    from media_index import audit_cards
    import roi_report

    cards = load_cards(cards_path)
    kc_path = out / "kcs.md"
    if not kc_path.is_file():
        kc_path = out / "authoring_ledger.md"
    ledger_text = kc_path.read_text() if kc_path.is_file() else None
    corpus_parts = []
    for name in ("sources.md", "transcripts.md"):
        path = out / name
        if path.is_file():
            corpus_parts.append(path.read_text())
    source_text = "\n\n".join(corpus_parts) or None
    errs, warns, info = check_cards(cards, ledger_text=ledger_text,
                                    source_text=source_text,
                                    require_kc_map=kc_path.name == "kcs.md")

    entries, stats = select(cards, 1, 12)
    plan = build_plan(str(cards_path), cards, entries, stats, 1, 12)
    plan_path = out / "review_plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n")

    # ROI is a report, not a gate; its output goes to a file so it never enters context
    # unless someone asks. The summary is the interface.
    roi_path = out / "roi.txt"
    roi_text = roi_report.report(cards)
    roi_path.write_text(roi_text)
    split_cards, restatements = _roi_risks(roi_text)
    media_risks = audit_cards(cards, out)
    ceiling = None
    scope_text = _scope_text(out)
    match = re.search(r"(?mi)^\s*Ceiling\s*[:~-]?\s*(\d+)", scope_text)
    if match:
        ceiling = int(match.group(1))
        if len(cards) > ceiling:
            warns.append(f"deck has {len(cards)} cards, above its own "
                         f"Ceiling {ceiling}; park or justify")
    figures = _extracted_figures(out)
    if _intake_images(out) == "no" and figures:
        warns.append(f"{figures} figure(s) extracted but intake says images: no; "
                     "confirm the caller opted out, or turn images on")
    review = _ensure_review_actions(out, cards, plan, cards_path)
    packet_path = write_review_packet(out, cards, plan, ledger_text)
    kc_map, _, _, _ = parse_kc_map(ledger_text or "")
    layers = Counter(str(c.get("layer") or "?") for c in cards)
    strata = Counter(str(c.get("stratum") or "unspecified") for c in cards)
    gates_path = out / "gates.json"
    gates_path.write_text(json.dumps(
        {"cards": len(cards), "errors": errs, "warnings": warns, "info": info},
        indent=2) + "\n")

    return {"cards": len(cards), "errors": len(errs), "warnings": len(warns),
            "errs": errs, "warns": warns, "gates": gates_path,
            "selected": len(entries), "total": len(cards),
            "plan": plan_path, "roi": roi_path, "packet": packet_path,
            "roi_split": split_cards, "roi_restatements": restatements,
            "media_risks": media_risks, "review": review,
            "kc_total": len(kc_map),
            "kc_linked": sum(1 for c in cards if c.get("kc")),
            "ceiling": ceiling,
            "layers": dict(layers), "strata": dict(strata)}


def stage_build(cards_path: Path, out: Path, deck_name: str, apkg: Path | None,
                media: bool, media_root: str | None,
                merge_existing: str | None = None) -> dict:
    """Build and validate the package in one process, returning a compact result."""
    target = apkg or (out / "deck.apkg")
    cmd = [sys.executable, str(Path(__file__).with_name("build_apkg.py")),
           str(cards_path), str(target), "--deck-name", deck_name]
    if media:
        cmd += ["--media", "--media-root", str(media_root or cards_path.parent)]
    if merge_existing:
        cmd += ["--merge-existing", merge_existing]
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
    """Persist the dossier through the revision CLI, keeping core imports separate."""
    cmd = [sys.executable, str(Path(__file__).with_name("revision.py")),
           "context", "pack", "--work", str(out), "--cards", str(cards_path),
           "--deck", deck_name, "--json"]
    if profile:
        cmd += ["--profile", profile]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout)[-300:])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"revision context pack returned no JSON: {exc}") from exc


def artifact_state(out: Path) -> dict[str, bool]:
    """Which mandatory evidence files exist and are non-empty.

    New runs put scope in intake.md; legacy runs may still carry scope_gate.md.
    New runs write kcs.md; legacy runs may still carry authoring_ledger.md.
    """
    intake = out / "intake.md"
    state = {"intake.md": intake.is_file() and intake.stat().st_size > 0,
             "scope": bool(_scope_section(_read_optional(intake)))
                      or ((out / "scope_gate.md").is_file()
                          and (out / "scope_gate.md").stat().st_size > 0)}
    kc = next((out / name for name in ("kcs.md", "authoring_ledger.md")
               if (out / name).is_file() and (out / name).stat().st_size > 0), None)
    state["kcs.md"] = kc is not None
    return state


def evidence_line(cards: list[dict], out: Path) -> str:
    """A compact, human-readable evidence summary; no card text."""
    arts = artifact_state(out)
    sources = [str(c.get("source") or c.get("source_ref") or "").strip()
               for c in cards]
    prov = sum(1 for src in sources if src and any(ch.isdigit() for ch in src))
    derived = sum(1 for src in sources if src.lower() == "derived")
    tz_topics = {str(c.get("topic") or "") for c in cards if c.get("tier_zero")}
    topics = {str(c.get("topic") or "") for c in cards}
    media = sum(1 for c in cards if c.get("media"))
    flags = " ".join(f"{name.replace('.md', '')}={'ok' if ok else 'MISSING'}"
                     for name, ok in arts.items())
    return (f"evidence   {flags} | provenance {prov}/{len(cards)} "
            f"({derived} derived) | tier-zero {len(tz_topics)}/{len(topics)} "
            f"topic(s) | image cards {media}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="pipeline.py",
        description="Extract, validate, triage, ROI, and review actions in one call.")
    ap.add_argument("--sources", nargs="*", default=None,
                    help="PDFs, videos, audio, or directories to extract (batch mode)")
    ap.add_argument("--cards", default=None,
                    help="an existing deck (.json or .jsonl) to gate instead of extracting")
    ap.add_argument("--out", default=None, help="work directory for this topic")
    ap.add_argument("--work", default=None, help="alias for --out (work directory)")
    ap.add_argument("--deck-name", default=None,
                    help="deck name for --build and the summary")
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
    ap.add_argument("--allow-missing-artifacts", action="store_true",
                    help="build without intake.md, scope, or kcs.md "
                         "(draft or diagnosis only)")
    ap.add_argument("--context", action="store_true",
                    help="persist the deck dossier after a successful build (opt-in)")
    ap.add_argument("--no-context", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--anki-profile", default="",
                    help="Anki profile name to record in the deck dossier")
    ap.add_argument("--gates-only", action="store_true",
                    help="skip extraction; just validate/triage/ROI the --cards deck")
    ap.add_argument("--resume", action="store_true",
                    help="skip media sources already marked done in pipeline_state.json")
    ap.add_argument("--status", action="store_true",
                    help="print the last pipeline state and exit")
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
    if args.sources and not args.gates_only and _extract_busy(out):
        print("pipeline.py: another extraction is still running in this work "
              "dir; wait for it or use a different --out", file=sys.stderr)
        return 2
    _mark(out, "run", "running")

    if args.gates_only and not args.cards:
        print("pipeline.py: --gates-only requires --cards", file=sys.stderr)
        return 2
    if not args.gates_only and not args.sources and not args.cards:
        print("pipeline.py: pass --sources to extract, or --cards to gate an existing "
              "deck (or --gates-only with --cards)", file=sys.stderr)
        return 2
    if args.sources and not args.gates_only:
        media_sources, doc_sources = _split_sources(args.sources, exclude=out)
        if not media_sources and not doc_sources:
            print("pipeline.py: no sources left after excluding the work dir",
                  file=sys.stderr)
            return 2
        _mark(out, "extract", "running", pid=os.getpid())
        if media_sources:
            med = stage_media(media_sources, out,
                              _media_images(media_sources, args.images),
                              args.model, args.language, args.force_transcribe,
                              args.whole_playlist, args.items, args.title,
                              args.device, args.initial_prompt,
                              resume=args.resume)
            lines.append(f"media      {med['videos']} video(s), {med['chunks']} chunks"
                         + (f", {med['failed']} FAILED" if med['failed'] else ""))
            if med["failed"] and not med["videos"] and not doc_sources:
                print("\n".join(lines))
                return 1
        if doc_sources:
            _mark(out, "extract", "running", sources=doc_sources)
            ex = stage_extract(doc_sources, out, args.date_filter,
                               args.page_crops)
            if not ex["sources"]:
                lines.append(f"extract    0 source(s), {ex['failed']} FAILED")
                print("\n".join(lines))
                return 1
            lines.append(f"extract    {ex['sources']} source(s), {ex['chars']:,} chars"
                         f", {ex['figures']} figures"
                         + (f", {ex['failed']} FAILED" if ex["failed"] else ""))
            if ex["figures"]:
                lines.append(f"images     {ex['figures']} figure(s); default on "
                             "unless the caller opted out")
            if ex["failed"]:
                for s in ex["manifest"]["sources"]:
                    if s.get("error"):
                        lines.append(f"           ! {s['tag']}: {s['error']}")
            for s in ex["manifest"]["sources"]:
                if s.get("warning"):
                    lines.append(f"           ! {s['tag']}: {s['warning']}")
            _mark(out, "extract", "done", sources=len(ex["manifest"]["sources"]),
                  failed=ex["failed"], figures=ex["figures"])
        reads = []
        if doc_sources:
            reads.append("sources.md")
        if media_sources:
            reads.append("transcripts.md")
        lines.append(f"NEXT       read {' and '.join(reads) or 'the extracts'} "
                     "once; write intake.md § Scope and kcs.md before cards.jsonl; "
                     "re-run with --cards for the gates")

    g = None
    if args.cards:
        _mark(out, "gates", "running")
        g = stage_gates(Path(args.cards), out)
        _mark(out, "gates", "done", cards=g["cards"], errors=g["errors"],
              warnings=g["warnings"], media_risks=len(g["media_risks"]),
              roi_split=len(g["roi_split"]))
        lines.append(f"gates      {g['cards']} card(s): {g['errors']} error(s), "
                     f"{g['warnings']} warning(s)")
        for msg in g["errs"][:20]:
            lines.append(f"error      {msg}")
            hint = fix_for(msg)
            if hint:
                lines.append(f"           fix: {hint}")
        if len(g["errs"]) > 20:
            lines.append(f"           ... and {len(g['errs']) - 20} more errors; "
                         f"see {_short(g['gates'], root)}")
        for msg in g["warns"][:10]:
            lines.append(f"warn       {msg}")
        if len(g["warns"]) > 10:
            lines.append(f"           ... and {len(g['warns']) - 10} more warnings; "
                         f"see {_short(g['gates'], root)}")
        lines.append(f"gates-json {_short(g['gates'], root)}")
        lines.append(f"triage     {g['selected']} of {g['total']} selected -> "
                     f"{_short(g['plan'], root)}")
        lines.append(f"roi        {_short(g['roi'], root)}")
        lines.append(f"packet     {_short(g['packet'], root)}")
        shape = " | ".join(f"{name} {g['layers'].get(name, 0)}"
                            for name in ("L1", "L2", "L3", "Procedure"))
        lines.append(f"shape      {shape}")
        strata = ", ".join(f"{name} {count}" for name, count in
                           sorted(g["strata"].items(), key=lambda x: (-x[1], x[0])))
        lines.append(f"strata     {strata or 'none'}")
        if g["roi_split"]:
            shown = ", ".join(str(card) for card in g["roi_split"][:8])
            lines.append(f"roi-split  {len(g['roi_split'])} candidate(s): {shown}")
        if g["media_risks"]:
            shown = "; ".join(
                f"card {risk['card']} {risk['risk']}"
                for risk in g["media_risks"][:8])
            lines.append(f"media      {len(g['media_risks'])} risk(s): {shown}")
        lines.append(evidence_line(load_cards(Path(args.cards)), out))
        if g["kc_total"]:
            lines.append(f"kc         {g['kc_linked']}/{g['cards']} card(s) linked "
                         f"to {g['kc_total']} KC(s)")
        rv = g["review"]
        if rv["required"]:
            lines.append(f"review     {rv['state']} -> {_short(rv['path'], root)}")
            review = f"review {rv['state']}"
        else:
            lines.append("review     not run")
            review = "review not run"
        if g["errors"] or g["media_risks"] or (rv["required"] and rv["state"] != "resolved"):
            state = "BLOCKED"
        elif g["warnings"]:
            state = "READY WITH WARNINGS"
        else:
            state = "READY"
        lines.append(f"quality    static {g['errors']} error(s); "
                     f"media {len(g['media_risks'])} risk(s); "
                     f"roi {len(g['roi_split'])} split(s); {review}; {state}")
        if args.deck_name:
            lines.append(f"deck-name  {args.deck_name}")
        if args.build:
            if g["review"]["required"] and g["review"]["state"] != "resolved":
                print("pipeline.py: refusing --build: review feedback exists but "
                      f"{g['review']['path'].name} is {g['review']['state']}. "
                      "Fill every score-1 action/target, set `status: resolved`, "
                      "and re-run the gates.",
                      file=sys.stderr)
                return 1
            if g["media_risks"]:
                print("pipeline.py: refusing --build: media risks remain. Fix them.",
                      file=sys.stderr)
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
                            target, args.media, args.media_root,
                            args.merge_existing)
            if b["ok"]:
                _mark(out, "build", "done", target=b["apkg"])
                lines.append(f"build      {b['apkg']}")
                if b.get("build"):
                    lines.append(f"build-info {b['build']}")
                lines.append(f"validate   {b['validation']}")
                done = "DONE WITH WARNINGS" if g["warnings"] else "DONE"
                if not rv["required"]:
                    done += " — NOT REVIEWED"
                lines.append(f"status     {done}")
                if args.context:
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
