"""Deterministic packing of deck artifacts into a persistent dossier."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from cardid import card_hash, last_row_per_card, load_cards

from . import index as idx
from .manifest import build as build_manifest
from .manifest import file_table, sha256_file
from .model import (FILE_SCHEMAS, MEDIA_KEYS, SOURCE_KEYS,
                    TOPIC_KEYS, card_from_source, card_key, new_uuid, now,
                    plain_text, preserve_extra, state_from_existing,
                    state_index)
from .previews import make as make_preview
from .store import DossierStore, write_json, write_jsonl, write_text




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
    return {"deck_name": name, "profile": str(deck.get("profile") or ""),
            "deck_id": str(deck.get("deck_id") or ""),
            "aliases": list(deck.get("aliases") or []),
            "notetypes": list(notetypes)}


def find_uuid(ident: dict) -> str | None:
    found = idx.resolve(ident["deck_name"])
    if found:
        return found
    if ident.get("deck_id"):
        return idx.find_by_deck_id(ident["deck_id"])
    return None


def _cards_path(workdir: Path) -> Path | None:
    for name in ("cards.jsonl", "cards.json"):
        path = workdir / name
        if path.is_file():
            return path
    return None


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _read_jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _read_text(path: Path) -> str:
    try:
        return path.read_text()
    except OSError:
        return ""


def _hash_file(path: Path) -> str:
    try:
        return sha256_file(path)
    except OSError:
        return ""


def review_scores(workdir: Path) -> dict[str, int]:
    scores = {}
    for name in ("review_feedback.jsonl", "review_recall.jsonl"):
        path = workdir / name
        if not path.is_file():
            continue
        for key, row in last_row_per_card(_read_jsonl(path)).items():
            if row.get("score") is not None:
                scores[str(key)] = int(row["score"])
    return scores


def sources(workdir: Path) -> list[dict]:
    rows = []
    manifest = _read_json(workdir / "manifest.json", {}) or {}
    for src in manifest.get("sources", []) or []:
        path = str(src.get("source_path") or "")
        rows.append({
            "type": src.get("source_type") or "",
            "path": "" if path.startswith(("http://", "https://")) else path,
            "url": path if path.startswith(("http://", "https://")) else "",
            "title": Path(path).name if path else "",
            "locator": src.get("md") or "",
            "hash": _hash_file(Path(path)) if path and Path(path).is_file() else "",
            "fetched_at": manifest.get("generated_at") or "",
            "error": src.get("error") or "",
        })
    for video in _read_jsonl(workdir / "videos.jsonl"):
        local = str(video.get("local_path") or "")
        rows.append({
            "type": video.get("source_type") or "video",
            "path": local,
            "url": video.get("source_url") or video.get("url") or "",
            "title": video.get("title") or "",
            "locator": video.get("source_label") or "",
            "hash": _hash_file(Path(local)) if local and Path(local).is_file() else "",
            "fetched_at": "",
            "captions": video.get("transcript_source") or "",
        })
    seen, out = set(), []
    for row in rows:
        key = (row.get("type"), row.get("path") or row.get("url"),
               row.get("title"), row.get("locator"))
        if key in seen:
            continue
        seen.add(key)
        preserve_extra(row, row, SOURCE_KEYS)
        out.append(row)
    return out


def _vision_map(workdir: Path) -> dict[str, dict]:
    out = {}
    for path in sorted(workdir.rglob("vision*.jsonl")):
        for row in _read_jsonl(path):
            result = row.get("result")
            if isinstance(result, dict) and row.get("file"):
                out[Path(row["file"]).name] = result
    return out


def media_candidates(workdir: Path, cards: list[dict], dossier: Path) -> list[dict]:
    used = set()
    for card in cards:
        for m in card.get("media") or []:
            name = m if isinstance(m, str) else (m or {}).get("file")
            if name:
                used.add(Path(str(name)).name)
    vision = _vision_map(workdir)
    raw = []
    for path in sorted(workdir.rglob("figures.json")):
        for fig in _read_json(path, []) or []:
            if not isinstance(fig, dict) or not fig.get("file"):
                continue
            prefix = path.parent.relative_to(workdir).as_posix()
            rel = f"{prefix}/{fig['file']}" if prefix != "." else fig["file"]
            raw.append({
                "file": rel, "kind": fig.get("kind") or "figure",
                "quality": fig.get("quality") or "unknown",
                "source": fig.get("source") or "",
                "source_url": fig.get("source_url") or "",
                "locator": (f"p.{fig['page']}" if fig.get("page") else
                            f"slide {fig.get('slide')}" if fig.get("slide") else ""),
                "sha256": fig.get("sha256") or "",
                "why": fig.get("flags") or [],
            })
    for path in sorted(workdir.rglob("frames.jsonl")):
        for row in _read_jsonl(path):
            if not row.get("best") or row.get("attach") not in ("direct", "confirm"):
                continue
            raw.append({
                "file": row.get("file") or "", "kind": "frame",
                "quality": row.get("quality") or "unknown",
                "source": row.get("source") or "",
                "source_url": row.get("source_url") or "",
                "locator": row.get("timecode") or "",
                "sha256": "", "why": [row.get("reason") or ""],
            })
    out, seen = [], set()
    for row in raw:
        if row["quality"] not in ("high", "medium"):
            continue
        key = (row["file"], row["source"])
        if key in seen:
            continue
        seen.add(key)
        src = workdir / row["file"]
        vis = vision.get(Path(row["file"]).name, {})
        labels = list(vis.get("labels") or [])
        item = {
            "file": row["file"],
            "original_path": str(src.resolve()) if src.is_file() else "",
            "sha256": row.get("sha256") or (_hash_file(src) if src.is_file() else ""),
            "source": row["source"], "source_url": row["source_url"],
            "locator": row["locator"], "kind": vis.get("kind") or row["kind"],
            "quality": row["quality"],
            "vision": {"kind": vis.get("kind", ""),
                       "shows": vis.get("shows", ""), "labels": labels},
            "used": Path(row["file"]).name in used,
            "why_unused": "", "preview": "",
        }
        if not item["used"]:
            item["why_unused"] = ", ".join(x for x in row.get("why") or [] if x) \
                or "not selected by the author"
            if src.is_file():
                digest = item["sha256"] or hashlib.sha256(row["file"].encode()).hexdigest()
                rel, meta = make_preview(src, dossier / "thumbnails", digest,
                                         item["kind"], labels)
                if rel:
                    item["preview"] = rel
                    item["preview_meta"] = meta
        preserve_extra(row, item, MEDIA_KEYS)
        out.append(item)
    return out


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
        c = cur.get(topic, {}) if isinstance(cur, dict) else {}
        c = c or {}
        srcs = []
        for row in group:
            source = row.get("source") or row.get("source_url")
            if source and source not in srcs:
                srcs.append(source)
        item = {
            "topic": topic,
            "takeaways": list(prev.get("takeaways") or c.get("takeaways") or []),
            "notation": list(prev.get("notation") or c.get("notation") or []),
            "sources": srcs,
            "target_cards": prev.get("target_cards", c.get("target_cards")),
            "actual_cards": len(group),
            "anchors": list(prev.get("anchors") or c.get("anchors") or
                            [r.get("front", "") for r in group if r.get("tier_zero")]),
            "gaps": list(prev.get("gaps") or c.get("gaps") or []),
            "decisions": list(prev.get("decisions") or c.get("decisions") or []),
            "coverage": prev.get("coverage") or c.get("coverage") or "",
        }
        preserve_extra(prev, item, TOPIC_KEYS)
        out.append(item)
    return out


def _bullets(value, empty="- (not recorded)") -> str:
    if isinstance(value, str):
        return value.strip() or empty
    items = [str(v).strip() for v in (value or []) if str(v).strip()]
    return "\n".join(f"- {v}" for v in items) if items else empty


def _context_md(ident: dict, topics: list[dict], style: str, learner: str,
                decisions: str, future: str) -> str:
    lines = [f"# Deck dossier — {ident['deck_name']}", "",
             "Distilled context only. Cards, state, and revision history live "
             "beside this file; no full source or media is stored.", "", "## Topics"]
    for topic in topics:
        lines.append(f"### {topic['topic']} ({topic['actual_cards']} cards)")
        lines += [f"- {x}" for x in topic.get("takeaways") or []] or [
            "- (no takeaways recorded yet)"]
        if topic.get("gaps"):
            lines.append("Gaps: " + "; ".join(topic["gaps"]))
        lines.append("")
    lines += ["## Style", "", _bullets(style), "",
              "## Learner", "", _bullets(learner), "",
              "## Decisions", "", _bullets(decisions), "",
              "## Future work", "", _bullets(future), ""]
    return "\n".join(lines)


def _artifacts(workdir: Path) -> dict[str, str]:
    out = {}
    for name in ("intake.md", "scope_gate.md", "authoring_ledger.md"):
        path = workdir / name
        if path.is_file():
            out[name] = path.read_text()
    return out


def _created_at(stage: Path) -> str:
    manifest = _read_json(stage / "manifest.json", {}) or {}
    return manifest.get("created_at") or now()


def _extensions(stage: Path) -> dict:
    manifest = _read_json(stage / "manifest.json", {}) or {}
    return dict(manifest.get("extensions") or {})


def _migrations(stage: Path) -> list:
    manifest = _read_json(stage / "manifest.json", {}) or {}
    return list(manifest.get("migrations") or [])


def _write_context(stage: Path, ident: dict, uuid: str, rows: list[dict],
                   state: list[dict], topics: list[dict], srcs: list[dict],
                   media: list[dict], resources: list[dict] | None = None, *,
                   curated: dict | None = None,
                   artifacts: dict[str, str] | None = None,
                   confidence: str = "authored") -> dict:
    curated = curated or {}
    write_jsonl(stage / "cards.jsonl", rows)
    write_jsonl(stage / "anki_state.jsonl", state)
    write_jsonl(stage / "topics.jsonl", topics)
    write_jsonl(stage / "sources.jsonl", srcs)
    if not (stage / "source_excerpts.jsonl").exists():
        write_jsonl(stage / "source_excerpts.jsonl", [])
    write_jsonl(stage / "media_candidates.jsonl", media)
    if not (stage / "resources.jsonl").exists():
        write_jsonl(stage / "resources.jsonl", resources or [])
    (stage / "resources").mkdir(parents=True, exist_ok=True)

    sections = {"style.md": "style", "learner.md": "learner",
                "decisions.md": "decisions", "future_work.md": "future_work"}
    defaults = {"style.md": "# Course style", "learner.md": "# Learner",
                "decisions.md": "# Deck-shape decisions",
                "future_work.md": "# Future work"}
    for name, key in sections.items():
        path = stage / name
        if path.is_file() and path.read_text().strip():
            continue
        value = curated.get(key)
        write_text(path, (value if isinstance(value, str) else _bullets(value))
                   if value else defaults[name] + "\n\n- (not recorded)")
    if not (stage / "preferences.json").is_file() or not _read_json(
            stage / "preferences.json", {}):
        write_json(stage / "preferences.json", curated.get("preferences") or {})
    if not (stage / "notation.json").is_file() or not _read_json(
            stage / "notation.json", {}):
        write_json(stage / "notation.json", curated.get("notation") or {})

    evidence = stage / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    artifacts = artifacts or {}
    for name in ("intake.md", "scope_gate.md", "authoring_ledger.md"):
        path = evidence / name
        if name in artifacts:
            write_text(path, artifacts[name])
        elif not path.is_file():
            if confidence == "reconstructed":
                write_text(path, f"# {name[:-3]}\n\n- Reconstructed from "
                                 "AnkiConnect; no authored record is available.")
            else:
                write_text(path, f"# {name[:-3]}\n\n- (not recorded)")

    write_text(stage / "deck_context.md",
               _context_md(ident, topics, _read_text(stage / "style.md"),
                           _read_text(stage / "learner.md"),
                           _read_text(stage / "decisions.md"),
                           _read_text(stage / "future_work.md")))

    files = file_table(stage, FILE_SCHEMAS)
    summary = {
        "cards": len(rows), "topics": len(topics), "sources": len(srcs),
        "media_candidates": len(media),
        "resources": len(_read_jsonl(stage / "resources.jsonl")),
    }
    manifest = build_manifest(uuid, ident, files, summary,
                              created_at=_created_at(stage),
                              confidence=confidence,
                              migrations=_migrations(stage),
                              extensions=_extensions(stage))
    previous = _read_json(stage / "manifest.json", {}) or {}
    for key in ("last_attach", "last_update"):
        if previous.get(key):
            manifest[key] = previous[key]
    write_json(stage / "manifest.json", manifest)
    return manifest


def _match(card: dict, old_rows: list[dict], used: set[int]):
    key = (plain_text(card.get("front")), plain_text(card.get("back")))
    for i, row in enumerate(old_rows):
        if i not in used and card_key(row) == key:
            return i, row
    digest = card_hash(card)
    for i, row in enumerate(old_rows):
        if i not in used and row.get("content_hash") == digest:
            return i, row
    return None


def pack(workdir, deck, curated: dict | None = None,
         cards_path=None) -> dict:
    workdir = Path(workdir).resolve()
    ident = identity(deck)
    uuid = find_uuid(ident) or new_uuid()
    ident["aliases"] = list((idx.read_or_rebuild_index().get("decks", {})
                             .get(uuid, {}) or {}).get("aliases") or [])
    ident["aliases"] = sorted(set(ident["aliases"]) | set(identity(deck).get("aliases") or []))
    store = DossierStore(uuid)
    existing = store.read() if store.exists() else {
        "cards": [], "state": [], "topics": [], "sources": [],
        "media_candidates": [], "manifest": {},
    }
    path = Path(cards_path) if cards_path else _cards_path(workdir)
    if path is None or not path.is_file():
        raise ValueError(f"no cards.jsonl/cards.json in {workdir}")
    cards = load_cards(path)
    scores = review_scores(workdir)
    old_rows = existing.get("cards", [])
    old_state = state_index(existing.get("state", []))
    used, rows, state = set(), [], []
    for card in cards:
        match = _match(card, old_rows, used)
        old = None
        if match:
            i, old = match
            used.add(i)
        row = card_from_source(card, old, scores.get(card_hash(card)))
        rows.append(row)
        state.append(state_from_existing(old_state.get(row["rev_id"], {
            "rev_id": row["rev_id"]})))
    curated = curated if curated is not None else (
        _read_json(workdir / "curated.json", {}) or {})
    topics = _topics(rows, existing.get("topics", []), curated)

    with store.transaction() as stage:
        srcs = sources(workdir)
        media = media_candidates(workdir, cards, stage)
        manifest = _write_context(stage, ident, uuid, rows, state, topics,
                                  srcs, media,
                                  existing.get("resources") or [],
                                  curated=curated,
                                  artifacts=_artifacts(workdir))
    idx.register(uuid, ident, ident.get("aliases"))
    return {"key": uuid, "path": str(store.path), "manifest": manifest,
            "cards": len(rows), "topics": len(topics),
            "sources": len(srcs), "media_candidates": len(media)}


def save(ident, rows: list[dict], state: list[dict], *, sources: list[dict],
         media: list[dict], confidence: str = "authored",
         curated: dict | None = None,
         artifacts: dict[str, str] | None = None) -> dict:
    ident = identity(ident)
    uuid = find_uuid(ident) or new_uuid()
    store = DossierStore(uuid)
    topics = _topics(rows, [], curated or {})
    with store.transaction() as stage:
        manifest = _write_context(stage, ident, uuid, rows, state, topics,
                                  sources, media, [], curated=curated,
                                  artifacts=artifacts, confidence=confidence)
    idx.register(uuid, ident)
    return {"key": uuid, "path": str(store.path), "manifest": manifest}


def update(store: DossierStore, cards: list[dict], state: list[dict], *,
           last_attach: str = "", last_update: str = "") -> dict:
    ctx = store.read()
    old_manifest = ctx["manifest"]
    ident = {
        "deck_name": old_manifest["deck"]["name"],
        "aliases": old_manifest["deck"].get("aliases") or [],
        "profile": old_manifest["deck"].get("profile") or "",
        "deck_id": old_manifest["deck"].get("anki_deck_id") or "",
        "notetypes": old_manifest["deck"].get("notetypes") or [],
    }
    topics = _topics(cards, ctx["topics"], {})
    with store.transaction() as stage:
        manifest = _write_context(
            stage, ident, store.uuid, cards, state, topics,
            ctx["sources"], ctx["media_candidates"],
            confidence=old_manifest.get("confidence") or "authored")
        if last_attach:
            manifest["last_attach"] = last_attach
        if last_update:
            manifest["last_update"] = last_update
        write_json(stage / "manifest.json", manifest)
    idx.register(store.uuid, ident)
    return manifest


def load(selector: str | None = None) -> dict | None:
    uuid = idx.resolve(selector)
    if not uuid:
        return None
    store = DossierStore(uuid)
    if not store.exists():
        return None
    return store.read()


def update_cards(selector: str, cards: list[dict], state: list[dict], **kw) -> dict:
    uuid = idx.resolve(selector)
    if not uuid:
        raise FileNotFoundError(f"no dossier for {selector!r}")
    return update(DossierStore(uuid), cards, state, **kw)


def revision_dir(selector: str, stamp: str | None = None) -> Path:
    uuid = idx.resolve(selector)
    if not uuid:
        raise FileNotFoundError(f"no dossier for {selector!r}")
    stamp = stamp or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = idx.deck_dir(uuid) / "revisions" / stamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def snapshots_dir(selector: str) -> Path:
    uuid = idx.resolve(selector)
    if not uuid:
        raise FileNotFoundError(f"no dossier for {selector!r}")
    path = idx.deck_dir(uuid) / "snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path
