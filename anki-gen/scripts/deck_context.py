#!/usr/bin/env python3
"""Persistent, compact deck dossiers.

A new deck's `.apkg` is disposable; the reasoning behind it is not. This module
writes a dossier under `${XDG_DATA_HOME:-~/.local/share}/anki-gen/decks/` with
distilled context only: topic takeaways, course style/notation, learner
preferences, deck-shape decisions, future work, card records, source anchors,
media-candidate metadata, and adaptive previews. It never stores full media,
full source corpora, the Anki database, or hidden reasoning traces.

The packer is deterministic. Model-authored sections are short curated notes
written while the source context is still on hand (a `curated.json` in the work
directory, or edited directly in the dossier); this module does not re-read the
corpus to summarize it.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cardid import card_hash, last_row_per_card, load_cards  # noqa: E402

SCHEMA = 1
APP_VERSION = (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()
PREVIEW_TARGETS = (320, 640, 768, 1024)
CORE_FILES = ("deck_context.md", "topics.jsonl", "style.md", "notation.json",
              "learner.md", "preferences.json", "decisions.md", "future_work.md",
              "cards.jsonl", "authoring_ledger.md", "scope_gate.md", "intake.md",
              "sources.jsonl", "source_excerpts.jsonl", "media_candidates.jsonl")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def data_root() -> Path:
    override = os.environ.get("ANKI_GEN_DATA_HOME")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base).expanduser() / "anki-gen"


def decks_root() -> Path:
    return data_root() / "decks"


def deck_dir(deck_key: str) -> Path:
    return decks_root() / deck_key


def _slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return value[:48] or "deck"


def identity(deck) -> dict:
    if isinstance(deck, str):
        deck = {"deck_name": deck}
    deck = dict(deck or {})
    name = str(deck.get("deck_name") or deck.get("deck") or "").strip()
    if not name:
        raise ValueError("deck identity needs deck_name")
    notetypes = deck.get("notetypes") or ["3-Layer STEM", "3-Layer STEM Cloze"]
    if isinstance(notetypes, str):
        notetypes = [notetypes]
    return {
        "profile": str(deck.get("profile") or ""),
        "deck_id": str(deck.get("deck_id") or ""),
        "deck_name": name,
        "notetypes": list(notetypes),
    }


def deck_key(deck) -> str:
    ident = identity(deck)
    raw = "|".join((ident["deck_name"], ident["profile"],
                    ",".join(ident["notetypes"])))
    return f"{_slug(ident['deck_name'])}-{hashlib.sha1(raw.encode()).hexdigest()[:10]}"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def write_json(path: Path, obj) -> None:
    _atomic_write(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    _atomic_write(path, "".join(json.dumps(r, ensure_ascii=False) + "\n"
                                for r in rows))


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    try:
        text = path.read_text()
    except OSError:
        return rows
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text()
    except OSError:
        return default


def _index() -> dict:
    return _read_json(decks_root() / "index.json",
                      {"schema": SCHEMA, "decks": {}}) or {"schema": SCHEMA,
                                                           "decks": {}}


def _save_index(index: dict) -> None:
    write_json(decks_root() / "index.json", index)


def _index_entry(ident: dict, key: str | None = None,
                 aliases: list[str] | None = None) -> dict:
    return {"deck_name": ident["deck_name"], "profile": ident["profile"],
            "deck_id": ident["deck_id"], "notetypes": ident["notetypes"],
            "aliases": aliases or [], "updated_at": now()}


def register(ident: dict, key: str | None = None, aliases: list[str] | None = None) -> str:
    key = key or deck_key(ident)
    index = _index()
    old = index["decks"].get(key, {})
    merged_aliases = sorted({*(old.get("aliases") or []), *(aliases or []),
                             old.get("deck_name", "")} - {ident["deck_name"]})
    index["decks"][key] = _index_entry(ident, key, merged_aliases)
    _save_index(index)
    return key


def resolve(selector: str | None = None) -> str | None:
    """Find a dossier by key, deck name, alias, or deck id."""
    index = _index()
    decks = index.get("decks", {})
    if selector:
        want = str(selector)
        if want in decks:
            return want
        low = want.casefold()
        for key, entry in decks.items():
            names = [entry.get("deck_name", ""), *(entry.get("aliases") or [])]
            if any(str(n).casefold() == low for n in names):
                return key
            if entry.get("deck_id") and str(entry["deck_id"]) == want:
                return key
        return None
    keys = sorted(k for k in decks if deck_dir(k).is_dir())
    return keys[0] if len(keys) == 1 else None


def find_by_deck_id(deck_id: str) -> str | None:
    for key, entry in _index().get("decks", {}).items():
        if entry.get("deck_id") and str(entry["deck_id"]) == str(deck_id):
            return key
    return None


def _hash_file(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return ""


def plain_text(value) -> str:
    """A stable text form for matching live Anki fields to dossier cards.

    Anki holds rendered HTML while the dossier holds authoring text. Matching
    normalizes both sides (tags, source footer, media, markdown emphasis, math
    delimiters, whitespace) without ever using the content hash as identity.
    """
    s = html.unescape(str(value or ""))
    s = re.sub(r"<div[^>]*class=\"src\"[^>]*>.*?</div>", " ", s,
               flags=re.S | re.I)
    s = re.sub(r"<img[^>]*>", " ", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"</(?:p|li|div|h\d|tr)>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace(r"\(", "$").replace(r"\)", "$")
    s = s.replace(r"\[", "$$").replace(r"\]", "$$")
    s = re.sub(r"\*\*|__|`", "", s)
    s = re.sub(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+", "", s)
    return re.sub(r"\s+", " ", s).strip().casefold()


def card_key(row: dict) -> tuple[str, str]:
    return (plain_text(row.get("front")), plain_text(row.get("back")))


def _extract_why(back: str) -> str:
    m = re.search(r"\*\*Why:\*\*\s*(.+)", str(back or ""), re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def _row_from_card(card: dict, existing: dict | None = None,
                   review_score=None) -> dict:
    existing = existing or {}
    content = card_hash(card)
    return {
        "rev_id": existing.get("rev_id") or str(uuid.uuid4()),
        "anki_note_id": existing.get("anki_note_id"),
        "guid": existing.get("guid") or content,
        "front": str(card.get("front", "")),
        "back": str(card.get("back", "")),
        "layer": str(card.get("layer", "")),
        "topic": str(card.get("topic", "")),
        "deck": str(card.get("deck", "")),
        "objects": list(card.get("objects") or []),
        "tier_zero": bool(card.get("tier_zero", existing.get("tier_zero", False))),
        "cloze": bool(card.get("cloze", existing.get("cloze", False))),
        "stratum": str(card.get("stratum") or existing.get("stratum") or ""),
        "retrieval_target": str(card.get("retrieval_target")
                                or existing.get("retrieval_target") or ""),
        "why": str(card.get("why") or existing.get("why")
                   or _extract_why(card.get("back", ""))),
        "source": str(card.get("source") or card.get("source_ref") or ""),
        "source_url": str(card.get("source_url") or ""),
        "media": list(card.get("media") or []),
        "content_hash": content,
        "scheduling_fingerprint": existing.get("scheduling_fingerprint"),
        "review_score": (review_score if review_score is not None
                         else card.get("review_score", existing.get("review_score"))),
        "state": existing.get("state", "live"),
        "confidence": existing.get("confidence", "authored"),
    }


def _match_existing(card: dict, rows: list[dict],
                    used: set[int]) -> tuple[int, dict] | None:
    key = (plain_text(card.get("front")), plain_text(card.get("back")))
    for i, row in enumerate(rows):
        if i not in used and card_key(row) == key:
            return i, row
    content = card_hash(card)
    for i, row in enumerate(rows):
        if i not in used and row.get("content_hash") == content:
            return i, row
    for i, row in enumerate(rows):
        if i not in used and row.get("guid") == content:
            return i, row
    return None


def _cards_path(workdir: Path) -> Path | None:
    for name in ("cards.jsonl", "cards.json"):
        p = workdir / name
        if p.is_file():
            return p
    return None


def _sources(workdir: Path) -> list[dict]:
    rows: list[dict] = []
    manifest = _read_json(workdir / "manifest.json", {}) or {}
    for src in manifest.get("sources", []) or []:
        path = str(src.get("source_path") or "")
        rows.append({
            "type": src.get("source_type") or "",
            "path": path if not path.startswith(("http://", "https://")) else "",
            "url": path if path.startswith(("http://", "https://")) else "",
            "title": Path(path).name if path else "",
            "locator": src.get("md") or "",
            "hash": _hash_file(Path(path)) if path and Path(path).is_file() else "",
            "fetched_at": manifest.get("generated_at") or "",
            "error": src.get("error") or "",
        })
    for v in _read_jsonl(workdir / "videos.jsonl"):
        local = str(v.get("local_path") or "")
        rows.append({
            "type": v.get("source_type") or "video",
            "path": local,
            "url": v.get("source_url") or v.get("url") or "",
            "title": v.get("title") or "",
            "locator": v.get("source_label") or "",
            "hash": _hash_file(Path(local)) if local and Path(local).is_file() else "",
            "fetched_at": "",
            "captions": v.get("transcript_source") or "",
        })
    seen, out = set(), []
    for row in rows:
        key = (row.get("type"), row.get("path") or row.get("url"),
               row.get("title"), row.get("locator"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def preview_long_edge(kind: str = "", labels=None, contact_sheet: bool = False) -> int:
    """Adaptive preview size: no hard cap, 320 only for contact sheets."""
    if contact_sheet:
        return 320
    label_count = len(labels or [])
    if label_count >= 8:
        return 1024
    if label_count >= 3 or str(kind).lower() in (
            "diagram", "schematic", "page-crop", "slide-crop", "table"):
        return 768
    return 640


def _vision_map(workdir: Path) -> dict[str, dict]:
    out = {}
    for f in sorted(workdir.rglob("vision*.jsonl")):
        for row in _read_jsonl(f):
            result = row.get("result")
            if isinstance(result, dict) and row.get("file"):
                out[Path(row["file"]).name] = result
    return out


def _make_preview(src: Path, out_dir: Path, digest: str, kind: str,
                  labels: list[str]) -> tuple[str, dict]:
    """Write a PNG/JPEG preview; return (relative path, metadata)."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return "", {"error": "Pillow is not installed"}
    target = preview_long_edge(kind, labels)
    try:
        with Image.open(src) as raw:
            im = ImageOps.exif_transpose(raw).convert("RGB")
        im.thumbnail((target, target), Image.LANCZOS)
        line_art = str(kind).lower() in (
            "diagram", "schematic", "page-crop", "slide-crop", "table",
            "figure", "frame")
        ext = ".png" if line_art else ".jpg"
        path = out_dir / f"{digest[:12]}_{target}{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if ext == ".png":
            im.save(path, "PNG", optimize=True)
        else:
            im.save(path, "JPEG", quality=86, optimize=True, progressive=True)
        width, height = im.size
        return path.relative_to(out_dir.parent).as_posix(), {
            "width": width, "height": height,
            "target": target, "low_res": target > max(width, height)}
    except Exception as e:
        return "", {"error": str(e)}


def _media_candidates(workdir: Path, cards: list[dict],
                      dossier: Path) -> list[dict]:
    used_files = set()
    for card in cards:
        for m in card.get("media") or []:
            name = m if isinstance(m, str) else (m or {}).get("file")
            if name:
                used_files.add(Path(str(name)).name)
    vision = _vision_map(workdir)
    raw: list[dict] = []
    for f in sorted(workdir.rglob("figures.json")):
        for g in _read_json(f, []) or []:
            if not isinstance(g, dict) or not g.get("file"):
                continue
            prefix = f.parent.relative_to(workdir).as_posix()
            rel = f"{prefix}/{g['file']}" if prefix != "." else g["file"]
            raw.append({
                "file": rel, "kind": g.get("kind") or "figure",
                "quality": g.get("quality") or "unknown",
                "source": g.get("source") or "",
                "source_url": g.get("source_url") or "",
                "locator": (f"p.{g['page']}" if g.get("page") else
                            f"slide {g.get('slide')}" if g.get("slide") else ""),
                "sha256": g.get("sha256") or "", "caption": g.get("caption") or "",
                "labels": [], "why": g.get("flags") or [],
            })
    for f in sorted(workdir.rglob("frames.jsonl")):
        for r in _read_jsonl(f):
            if not r.get("best") or r.get("attach") not in ("direct", "confirm"):
                continue
            raw.append({
                "file": r.get("file") or "", "kind": "frame",
                "quality": r.get("quality") or "unknown",
                "source": r.get("source") or "",
                "source_url": r.get("source_url") or "",
                "locator": r.get("timecode") or "",
                "sha256": "", "caption": r.get("caption") or "",
                "labels": [], "why": [r.get("reason") or ""],
            })
    thumb_dir = dossier / "thumbnails"
    out, seen = [], set()
    for row in raw:
        if row["quality"] not in ("high", "medium"):
            continue
        key = (row["file"], row["source"])
        if key in seen:
            continue
        seen.add(key)
        src = workdir / row["file"]
        v = vision.get(Path(row["file"]).name, {})
        labels = list(v.get("labels") or row.get("labels") or [])
        item = {
            "file": row["file"],
            "original_path": str(src.resolve()) if src.is_file() else "",
            "sha256": row.get("sha256") or (_hash_file(src) if src.is_file() else ""),
            "source": row["source"], "source_url": row["source_url"],
            "locator": row["locator"], "kind": v.get("kind") or row["kind"],
            "quality": row["quality"],
            "vision": {"kind": v.get("kind", ""), "shows": v.get("shows", ""),
                       "labels": labels},
            "used": Path(row["file"]).name in used_files,
            "why_unused": "",
            "preview": "",
        }
        if not item["used"]:
            item["why_unused"] = ", ".join(
                x for x in row.get("why") or [] if x) or "not selected by the author"
            if src.is_file():
                rel, meta = _make_preview(src, thumb_dir, item["sha256"] or
                                          hashlib.sha256(item["file"].encode()).hexdigest(),
                                          item["kind"], labels)
                if rel:
                    item["preview"] = rel
                    item["preview_meta"] = meta
                elif meta.get("error"):
                    print(f"deck_context.py: preview skipped for {row['file']}: "
                          f"{meta['error']}", file=sys.stderr)
        out.append(item)
    return out


def _review_scores(workdir: Path) -> dict[str, int]:
    """Last review score per card hash, when the review log is still present."""
    scores: dict[str, int] = {}
    for name in ("review_feedback.jsonl", "review_recall.jsonl"):
        path = workdir / name
        if not path.is_file():
            continue
        last = last_row_per_card(_read_jsonl(path))
        for key, row in last.items():
            score = row.get("score")
            if score is not None:
                scores[str(key)] = int(score)
    return scores


def _curated(workdir: Path) -> dict:
    return _read_json(workdir / "curated.json", {}) or {}


def _topics(rows: list[dict], existing: list[dict], curated: dict) -> list[dict]:
    old = {str(t.get("topic")): t for t in existing}
    cur = curated.get("topics") or {}
    order, groups = [], {}
    for row in rows:
        topic = str(row.get("topic") or "")
        if topic not in groups:
            order.append(topic)
            groups[topic] = []
        groups[topic].append(row)
    out = []
    for topic in order:
        group = groups[topic]
        prev = old.get(topic, {})
        c = cur.get(topic) if isinstance(cur, dict) else {}
        c = c or {}
        sources = []
        for row in group:
            s = row.get("source") or row.get("source_url")
            if s and s not in sources:
                sources.append(s)
        out.append({
            "topic": topic,
            "takeaways": list(prev.get("takeaways") or c.get("takeaways") or []),
            "notation": list(prev.get("notation") or c.get("notation") or []),
            "sources": sources,
            "target_cards": prev.get("target_cards", c.get("target_cards")),
            "actual_cards": len(group),
            "anchors": list(prev.get("anchors") or c.get("anchors") or
                            [r.get("front", "") for r in group if r.get("tier_zero")]),
            "gaps": list(prev.get("gaps") or c.get("gaps") or []),
            "decisions": list(prev.get("decisions") or c.get("decisions") or []),
            "coverage": prev.get("coverage") or c.get("coverage") or "",
        })
    return out


def _bullets(items, empty="- (not recorded)") -> str:
    if isinstance(items, str):
        return items.strip() or empty
    items = [str(i).strip() for i in (items or []) if str(i).strip()]
    return "\n".join(f"- {i}" for i in items) if items else empty


def _deck_context_md(ident: dict, topics: list[dict], style: str, learner: str,
                     decisions: str, future: str) -> str:
    lines = [f"# Deck dossier — {ident['deck_name']}", "",
             "Distilled context only. Cards, evidence, and revision history live "
             "beside this file; no full source or media is stored.", "",
             "## Topics"]
    for t in topics:
        lines += [f"### {t['topic']} ({t['actual_cards']} cards)"]
        if t.get("takeaways"):
            lines += [f"- {x}" for x in t["takeaways"]]
        else:
            lines.append("- (no takeaways recorded yet)")
        if t.get("gaps"):
            lines.append("Gaps: " + "; ".join(t["gaps"]))
        lines.append("")
    lines += ["## Style", "", _bullets(style), "",
              "## Learner", "", _bullets(learner), "",
              "## Decisions", "", _bullets(decisions), "",
              "## Future work", "", _bullets(future), ""]
    return "\n".join(lines)


def _artifacts(workdir: Path) -> dict[str, str]:
    out = {}
    for name in ("intake.md", "scope_gate.md", "authoring_ledger.md"):
        p = workdir / name
        if p.is_file():
            out[name] = p.read_text()
    return out


def _checksum(directory: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        rel = path.relative_to(directory).as_posix()
        if rel in ("manifest.json", "_export.json") or rel.startswith("revisions/"):
            continue
        h.update(rel.encode() + b"\0")
        h.update(path.read_bytes())
    return h.hexdigest()


def _write_dossier(ident: dict, key: str, rows: list[dict], topics: list[dict],
                   sources: list[dict], media: list[dict], *,
                   confidence: str = "authored", curated: dict | None = None,
                   artifacts: dict[str, str] | None = None,
                   existing: dict | None = None) -> dict:
    target = deck_dir(key)
    target.mkdir(parents=True, exist_ok=True)
    curated = curated or {}
    existing = existing or {}
    styles = {
        "style.md": _read_text(target / "style.md", existing.get("style", "")),
        "learner.md": _read_text(target / "learner.md", existing.get("learner", "")),
        "decisions.md": _read_text(target / "decisions.md",
                                   existing.get("decisions", "")),
        "future_work.md": _read_text(target / "future_work.md",
                                     existing.get("future", "")),
    }
    # A dossier is the durable record. Once a section exists, a later pack
    # preserves it; curated.json is used when the dossier has no section yet.
    for name, curated_key in (("style.md", "style"), ("learner.md", "learner"),
                              ("decisions.md", "decisions"),
                              ("future_work.md", "future_work")):
        if (target / name).is_file() and (target / name).read_text().strip():
            continue
        value = curated.get(curated_key)
        if value:
            styles[name] = value if isinstance(value, str) else _bullets(value)
    for name, text in styles.items():
        if not text:
            text = {"style.md": "# Course style\n\n- (not recorded)",
                    "learner.md": "# Learner\n\n- (not recorded)",
                    "decisions.md": "# Deck-shape decisions\n\n- (not recorded)",
                    "future_work.md": "# Future work\n\n- (not recorded)"}[name]
        _atomic_write(target / name, text.rstrip() + "\n")

    prefs = _read_json(target / "preferences.json", existing.get("preferences", {})) or {}
    if not prefs and curated.get("preferences"):
        prefs = curated["preferences"]
    write_json(target / "preferences.json", prefs)

    notation = _read_json(target / "notation.json", existing.get("notation", {})) or {}
    if not notation and curated.get("notation"):
        notation = curated["notation"]
    write_json(target / "notation.json", notation)

    write_jsonl(target / "topics.jsonl", topics)
    write_jsonl(target / "cards.jsonl", rows)
    write_jsonl(target / "sources.jsonl", sources)
    if not (target / "source_excerpts.jsonl").exists():
        write_jsonl(target / "source_excerpts.jsonl", [])
    write_jsonl(target / "media_candidates.jsonl", media)

    if artifacts is not None:
        for name, text in artifacts.items():
            _atomic_write(target / name, text)
    elif not confidence == "reconstructed":
        for name in ("intake.md", "scope_gate.md", "authoring_ledger.md"):
            if not (target / name).exists():
                _atomic_write(target / name, f"# {name[:-3]}\n\n- (not recorded)\n")
    else:
        for name in ("intake.md", "scope_gate.md", "authoring_ledger.md"):
            if not (target / name).exists():
                _atomic_write(target / name,
                              f"# {name[:-3]}\n\n- Reconstructed from AnkiConnect; "
                              "no authored ledger is available.\n")

    deck_md = _deck_context_md(ident, topics, styles["style.md"],
                               styles["learner.md"], styles["decisions.md"],
                               styles["future_work.md"])
    _atomic_write(target / "deck_context.md", deck_md)

    sections = {}
    for p in sorted(target.rglob("*")):
        if p.is_file() and not p.relative_to(target).as_posix().startswith("revisions/"):
            rel = p.relative_to(target).as_posix()
            sections[rel] = p.stat().st_size
    preview_bytes = sum(v for k, v in sections.items() if k.startswith("thumbnails/"))
    total = sum(sections.values())
    manifest = _read_json(target / "manifest.json", {}) or {}
    created = manifest.get("created_at") or now()
    info = _index().get("decks", {}).get(key, {})
    manifest = {
        "schema": SCHEMA,
        "app_version": APP_VERSION,
        "created_at": created,
        "updated_at": now(),
        "confidence": confidence,
        "anki": {
            "profile": ident["profile"] or info.get("profile", ""),
            "deck_id": ident["deck_id"] or info.get("deck_id", ""),
            "deck_name": ident["deck_name"],
            "notetypes": ident["notetypes"],
        },
        "counts": {"cards": len(rows), "topics": len(topics),
                   "sources": len(sources), "media_candidates": len(media)},
        "source_hashes": {s.get("locator") or s.get("title") or s.get("url"): s.get("hash")
                          for s in sources if s.get("hash")},
        "last_attach": manifest.get("last_attach", ""),
        "last_update": manifest.get("last_update", ""),
        "sections": sections,
        "previews_bytes": preview_bytes,
        "previews_share": round(preview_bytes / total, 3) if total else 0.0,
    }
    manifest["checksum"] = _checksum(target)
    write_json(target / "manifest.json", manifest)
    register(ident, key)
    return {"key": key, "path": str(target), "manifest": manifest,
            "cards": len(rows), "topics": len(topics),
            "media_candidates": len(media), "sources": len(sources)}


def save(ident, rows: list[dict], *, sources=None, media=None,
         confidence: str = "authored", curated: dict | None = None,
         artifacts: dict[str, str] | None = None) -> dict:
    ident = identity(ident)
    key = register(ident)
    existing_ctx = load(key, strict=False) or {}
    existing_topics = existing_ctx.get("topics", [])
    topics = _topics(rows, existing_topics, curated or {})
    return _write_dossier(ident, key, rows, topics,
                          sources if sources is not None else existing_ctx.get("sources", []),
                          media if media is not None else existing_ctx.get("media_candidates", []),
                          confidence=confidence, curated=curated,
                          artifacts=artifacts, existing=existing_ctx)


def pack(workdir, deck, curated: dict | None = None,
         cards_path=None) -> dict:
    """Pack existing artifacts into a dossier. Returns a compact summary."""
    workdir = Path(workdir).resolve()
    ident = identity(deck)
    key = register(ident)
    existing_ctx = load(key, strict=False) or {}
    path = Path(cards_path) if cards_path else _cards_path(workdir)
    if path is None or not path.is_file():
        raise ValueError(f"no cards.jsonl/cards.json in {workdir}")
    cards = load_cards(path)
    scores = _review_scores(workdir)
    old_rows = existing_ctx.get("cards", [])
    used: set[int] = set()
    rows = []
    for card in cards:
        match = _match_existing(card, old_rows, used)
        old = None
        if match is not None:
            i, old = match
            used.add(i)
        rows.append(_row_from_card(card, old, scores.get(card_hash(card))))
    curated = curated if curated is not None else _curated(workdir)
    sources = _sources(workdir)
    media = _media_candidates(workdir, cards, deck_dir(key))
    return _write_dossier(ident, key, rows, _topics(rows, existing_ctx.get("topics", []), curated),
                          sources, media, curated=curated,
                          artifacts=_artifacts(workdir), existing=existing_ctx)


def load(deck_key_or_selector: str | None = None, *, strict: bool = True) -> dict | None:
    key = resolve(deck_key_or_selector)
    if not key:
        if strict and deck_key_or_selector:
            raise FileNotFoundError(f"no dossier for {deck_key_or_selector!r}")
        return None
    target = deck_dir(key)
    if not target.is_dir():
        if strict:
            raise FileNotFoundError(f"dossier directory missing: {target}")
        return None
    return {
        "key": key, "path": target,
        "manifest": _read_json(target / "manifest.json", {}) or {},
        "cards": _read_jsonl(target / "cards.jsonl"),
        "topics": _read_jsonl(target / "topics.jsonl"),
        "sources": _read_jsonl(target / "sources.jsonl"),
        "media_candidates": _read_jsonl(target / "media_candidates.jsonl"),
        "preferences": _read_json(target / "preferences.json", {}) or {},
        "notation": _read_json(target / "notation.json", {}) or {},
        "style": _read_text(target / "style.md"),
        "learner": _read_text(target / "learner.md"),
        "decisions": _read_text(target / "decisions.md"),
        "future": _read_text(target / "future_work.md"),
        "deck_context": _read_text(target / "deck_context.md"),
    }


def write_cards(deck_key_or_selector: str, rows: list[dict]) -> None:
    key = resolve(deck_key_or_selector)
    if not key:
        raise FileNotFoundError(f"no dossier for {deck_key_or_selector!r}")
    write_jsonl(deck_dir(key) / "cards.jsonl", rows)


def update_manifest(deck_key_or_selector: str, **fields) -> dict:
    key = resolve(deck_key_or_selector)
    if not key:
        raise FileNotFoundError(f"no dossier for {deck_key_or_selector!r}")
    target = deck_dir(key)
    manifest = _read_json(target / "manifest.json", {}) or {}
    for name, value in fields.items():
        if isinstance(value, dict) and isinstance(manifest.get(name), dict):
            manifest[name].update(value)
        else:
            manifest[name] = value
    manifest["updated_at"] = now()
    manifest["checksum"] = _checksum(target)
    write_json(target / "manifest.json", manifest)
    return manifest


def revision_dir(deck_key_or_selector: str, stamp: str | None = None) -> Path:
    key = resolve(deck_key_or_selector)
    if not key:
        raise FileNotFoundError(f"no dossier for {deck_key_or_selector!r}")
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = deck_dir(key) / "revisions" / stamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def validate(context: dict | None = None, deck_key_or_selector: str | None = None) -> dict:
    ctx = context or load(deck_key_or_selector)
    if not ctx:
        return {"errors": ["no dossier"], "warnings": []}
    errors, warnings = [], []
    manifest = ctx.get("manifest") or {}
    if manifest.get("schema") != SCHEMA:
        errors.append(f"manifest schema {manifest.get('schema')!r} != {SCHEMA}")
    rows = ctx.get("cards") or []
    seen_ids, seen_keys = set(), {}
    for i, row in enumerate(rows, 1):
        rev = row.get("rev_id")
        if not rev:
            errors.append(f"card {i}: missing rev_id")
        elif rev in seen_ids:
            errors.append(f"card {i}: duplicate rev_id {rev}")
        seen_ids.add(rev)
        for field in ("front", "back", "topic", "source"):
            if not str(row.get(field) or "").strip():
                errors.append(f"card {i}: missing {field}")
        if not row.get("why") or not row.get("retrieval_target"):
            warnings.append(f"card {i}: no why/retrieval target recorded")
        key = card_key(row)
        if key in seen_keys and row.get("state", "live") == "live":
            warnings.append(f"card {i}: same text as card {seen_keys[key]}")
        else:
            seen_keys[key] = i
        expected = card_hash({"front": row.get("front", ""),
                              "back": row.get("back", "")})
        if row.get("content_hash") and row["content_hash"] != expected:
            warnings.append(f"card {i}: content_hash is stale (fingerprint only)")
    for topic in ctx.get("topics") or []:
        if not topic.get("takeaways"):
            warnings.append(f"topic {topic.get('topic')!r}: no takeaways recorded")
        if not topic.get("sources"):
            warnings.append(f"topic {topic.get('topic')!r}: no source anchors")
        if not (topic.get("anchors") or topic.get("coverage")):
            warnings.append(f"topic {topic.get('topic')!r}: no anchor or coverage note")
    for media in ctx.get("media_candidates") or []:
        if media.get("quality") in ("high", "medium") and not media.get("used"):
            if not media.get("preview") and not media.get("preview_meta", {}).get("error"):
                warnings.append(f"unused media without preview: {media.get('file')}")
    if not (ctx.get("learner") or "").strip() or "(not recorded)" in (ctx.get("learner") or ""):
        warnings.append("learner preferences are not recorded")
    return {"errors": errors, "warnings": warnings}


def export(deck_key_or_selector: str, out_path) -> Path:
    key = resolve(deck_key_or_selector)
    if not key:
        raise FileNotFoundError(f"no dossier for {deck_key_or_selector!r}")
    source = deck_dir(key)
    out_path = Path(out_path).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    manifest = _read_json(source / "manifest.json", {}) or {}
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(p for p in source.rglob("*") if p.is_file()):
            rel = path.relative_to(source).as_posix()
            z.write(path, rel)
        meta = {"schema": SCHEMA, "deck_key": key, "app_version": APP_VERSION,
                "exported_at": now(), "checksum": _checksum(source),
                "deck_name": manifest.get("anki", {}).get("deck_name", "")}
        z.writestr("_export.json", json.dumps(meta, indent=2) + "\n")
    os.replace(tmp, out_path)
    return out_path


def _safe_rel(name: str) -> bool:
    path = Path(name)
    return not path.is_absolute() and ".." not in path.parts


def import_archive(path, *, attach: bool = False, url: str | None = None) -> dict:
    """Restore a dossier archive. Optionally re-attach note IDs via AnkiConnect."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(path)
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if any(not _safe_rel(n) for n in names):
            raise ValueError("archive contains an unsafe path")
        meta = json.loads(z.read("_export.json")) if "_export.json" in names else {}
        key = str(meta.get("deck_key") or "").strip()
        if not key:
            raise ValueError("archive is missing _export.json with a deck_key")
        decks_root().mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=str(decks_root())) as td:
            stage = Path(td)
            for name in names:
                if name == "_export.json" or name.endswith("/"):
                    continue
                dest = stage / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(name))
            checksum = _checksum(stage)
            if meta.get("checksum") and checksum != meta["checksum"]:
                raise ValueError("archive checksum does not match")
            target = deck_dir(key)
            if target.exists():
                backup = data_root() / "backups" / f"{key}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(target, backup)
            target.mkdir(parents=True, exist_ok=True)
            for item in sorted(stage.iterdir()):
                dest = target / item.name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
    manifest = _read_json(deck_dir(key) / "manifest.json", {}) or {}
    register(identity(manifest.get("anki", {})), key)
    attached = None
    if attach:
        import revision
        attached = revision.attach_key(key, url=url)
    return {"key": key, "path": str(deck_dir(key)), "manifest": manifest,
            "attached": attached}


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Inspect deck dossiers.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack")
    p.add_argument("work")
    p.add_argument("--deck", required=True)
    p.add_argument("--deck-id", default="")
    p.add_argument("--profile", default="")
    p.add_argument("--notetypes", nargs="*", default=None)
    p.add_argument("--json", action="store_true")
    v = sub.add_parser("validate")
    v.add_argument("--deck", required=True)
    v.add_argument("--json", action="store_true")
    e = sub.add_parser("export")
    e.add_argument("--deck", required=True)
    e.add_argument("--out", required=True)
    i = sub.add_parser("import")
    i.add_argument("archive")
    i.add_argument("--no-attach", action="store_true")
    i.add_argument("--url", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "pack":
        result = pack(a.work, {"deck_name": a.deck, "deck_id": a.deck_id,
                               "profile": a.profile, "notetypes": a.notetypes})
        print(json.dumps(result, indent=2) if a.json else
              f"dossier {result['key']}: {result['cards']} card(s), "
              f"{result['topics']} topic(s) -> {result['path']}")
        return 0
    if a.cmd == "validate":
        result = validate(deck_key_or_selector=a.deck)
        print(json.dumps(result, indent=2) if a.json else
              f"{len(result['errors'])} error(s), {len(result['warnings'])} warning(s)")
        return 1 if result["errors"] else 0
    if a.cmd == "export":
        print(export(a.deck, a.out))
        return 0
    if a.cmd == "import":
        result = import_archive(a.archive, attach=not a.no_attach, url=a.url)
        print(f"dossier {result['key']} -> {result['path']}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
