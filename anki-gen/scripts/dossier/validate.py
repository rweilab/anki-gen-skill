"""Dossier validation with stable codes (not prose matching)."""
from __future__ import annotations

from pathlib import Path

import hashlib
from .model import SCHEMA, content_hash


def _finding(code: str, message: str, *, warning: bool = False,
             path: str = "") -> dict:
    return {"code": code, "message": message, "warning": warning,
            "path": path}


def validate(context: dict | None = None, selector: str | None = None) -> dict:
    if context is None:
        from . import packer
        context = packer.load(selector)
    if not context:
        return {"errors": [_finding("E_DOSSIER_MISSING", "no dossier")],
                "warnings": []}
    errors, warnings = [], []
    manifest = context.get("manifest") or {}
    if manifest.get("schema") != SCHEMA:
        errors.append(_finding("E_SCHEMA", f"manifest schema must be {SCHEMA}"))
    cards = context.get("cards") or []
    states = context.get("state") or []
    state_by_rev = {}
    seen_rev, seen_note = set(), set()
    for i, card in enumerate(cards, 1):
        rev = str(card.get("rev_id") or "")
        if not rev:
            errors.append(_finding("E_REV_ID", f"card {i}: missing rev_id",
                                   path=f"cards.jsonl:{i}"))
        elif rev in seen_rev:
            errors.append(_finding("E_REV_ID_DUP", f"card {i}: duplicate rev_id",
                                   path=f"cards.jsonl:{i}"))
        seen_rev.add(rev)
        for field in ("front", "back", "topic", "source"):
            if not str(card.get(field) or "").strip():
                errors.append(_finding("E_CARD_FIELD",
                                       f"card {i}: missing {field}",
                                       path=f"cards.jsonl:{i}"))
        if not card.get("why") and not card.get("retrieval_target"):
            warnings.append(_finding("W_WHY",
                                     f"card {i}: no why/retrieval target recorded",
                                     warning=True, path=f"cards.jsonl:{i}"))
        if card.get("content_hash") and card["content_hash"] != content_hash(
                str(card.get("front", "")), str(card.get("back", ""))):
            warnings.append(_finding(
                "W_HASH", f"card {i}: content_hash is stale (fingerprint only)",
                warning=True, path=f"cards.jsonl:{i}"))
    for i, state in enumerate(states, 1):
        rev = str(state.get("rev_id") or "")
        if not rev:
            errors.append(_finding("E_STATE_REV", f"state {i}: missing rev_id",
                                   path=f"anki_state.jsonl:{i}"))
            continue
        if rev in state_by_rev:
            errors.append(_finding("E_STATE_DUP", f"state {i}: duplicate rev_id",
                                   path=f"anki_state.jsonl:{i}"))
        state_by_rev[rev] = state
        note_id = state.get("anki_note_id")
        if note_id is not None:
            if int(note_id) in seen_note:
                errors.append(_finding("E_NOTE_ID_DUP",
                                       f"state {i}: duplicate anki_note_id",
                                       path=f"anki_state.jsonl:{i}"))
            seen_note.add(int(note_id))
        if rev not in seen_rev:
            errors.append(_finding("E_STATE_ORPHAN",
                                   f"state {i}: rev_id is not in cards.jsonl",
                                   path=f"anki_state.jsonl:{i}"))
    for rev in seen_rev:
        state = state_by_rev.get(rev)
        if not state:
            warnings.append(_finding("W_STATE_MISSING",
                                     f"{rev}: no anki state row", warning=True))
        elif state.get("state") == "live" and not state.get("anki_note_id"):
            warnings.append(_finding("W_UNATTACHED",
                                     f"{rev}: live card has no anki_note_id",
                                     warning=True))
    for topic in context.get("topics") or []:
        name = topic.get("topic")
        if not topic.get("takeaways"):
            warnings.append(_finding("W_TOPIC_TAKEAWAY",
                                     f"topic {name!r}: no takeaways", warning=True))
        if not topic.get("sources"):
            warnings.append(_finding("W_TOPIC_SOURCE",
                                     f"topic {name!r}: no source anchors",
                                     warning=True))
        if not (topic.get("anchors") or topic.get("coverage")):
            warnings.append(_finding("W_TOPIC_ANCHOR",
                                     f"topic {name!r}: no anchor/coverage note",
                                     warning=True))
    for media in context.get("media_candidates") or []:
        if (media.get("quality") in ("high", "medium") and not media.get("used")
                and not media.get("preview")
                and not (media.get("preview_meta") or {}).get("error")):
            warnings.append(_finding("W_MEDIA_PREVIEW",
                                     f"unused media without preview: {media.get('file')}",
                                     warning=True))
    resources = context.get("resources") or []
    seen_resources, seen_paths = set(), set()
    for i, resource in enumerate(resources, 1):
        rid = str(resource.get("resource_id") or "")
        if not rid:
            errors.append(_finding("E_RESOURCE_ID",
                                   f"resource {i}: missing resource_id",
                                   path=f"resources.jsonl:{i}"))
        elif rid in seen_resources:
            errors.append(_finding("E_RESOURCE_ID_DUP",
                                   f"resource {i}: duplicate resource_id",
                                   path=f"resources.jsonl:{i}"))
        seen_resources.add(rid)
        rel = str(resource.get("path") or "")
        if not rel.startswith("resources/") or ".." in Path(rel).parts:
            errors.append(_finding("E_RESOURCE_PATH",
                                   f"resource {i}: path escapes resources/",
                                   path=f"resources.jsonl:{i}"))
            continue
        if rel in seen_paths:
            errors.append(_finding("E_RESOURCE_PATH_DUP",
                                   f"resource {i}: duplicate path",
                                   path=f"resources.jsonl:{i}"))
        seen_paths.add(rel)
        file_path = Path(context.get("path") or "") / rel
        if not file_path.is_file():
            errors.append(_finding("E_RESOURCE_MISSING",
                                   f"resource {i}: file missing: {rel}",
                                   path=f"resources.jsonl:{i}"))
            continue
        data = file_path.read_bytes()
        if len(data) != int(resource.get("bytes") or 0):
            errors.append(_finding("E_RESOURCE_SIZE",
                                   f"resource {i}: size mismatch: {rel}",
                                   path=f"resources.jsonl:{i}"))
        if hashlib.sha256(data).hexdigest() != resource.get("sha256"):
            errors.append(_finding("E_RESOURCE_HASH",
                                   f"resource {i}: checksum mismatch: {rel}",
                                   path=f"resources.jsonl:{i}"))
    learner = context.get("learner") or ""
    if not learner.strip() or "(not recorded)" in learner:
        warnings.append(_finding("W_LEARNER", "learner preferences are not recorded",
                                 warning=True))
    counts = manifest.get("counts") or {}
    for key, actual in (("cards", len(cards)), ("topics", len(context.get("topics") or [])),
                        ("sources", len(context.get("sources") or [])),
                        ("media_candidates", len(context.get("media_candidates") or [])),
                        ("resources", len(resources))):
        if counts.get(key) != actual:
            warnings.append(_finding("W_COUNTS",
                                     f"manifest counts.{key}={counts.get(key)} != {actual}",
                                     warning=True))
    for name in ("intake.md", "scope_gate.md", "authoring_ledger.md"):
        path = Path(context["path"]) / "evidence" / name
        if not path.is_file():
            warnings.append(_finding("W_EVIDENCE", f"missing evidence/{name}",
                                     warning=True, path=f"evidence/{name}"))
    return {"errors": errors, "warnings": warnings}


def report(result: dict) -> str:
    lines = [f"{len(result['errors'])} error(s), {len(result['warnings'])} warning(s)"]
    for item in result["errors"][:20]:
        lines.append(f"  ERROR {item['code']}: {item['message']}")
    for item in result["warnings"][:20]:
        lines.append(f"  warn  {item['code']}: {item['message']}")
    if len(result["errors"]) > 20:
        lines.append(f"  ... and {len(result['errors']) - 20} more errors")
    if len(result["warnings"]) > 20:
        lines.append(f"  ... and {len(result['warnings']) - 20} more warnings")
    return "\n".join(lines)
