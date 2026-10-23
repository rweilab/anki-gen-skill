"""Bulk field/tag edits through AnkiConnect, with snapshot and verification."""
from __future__ import annotations

import json
from pathlib import Path

import deck_context as dc
from anki_connect import AnkiConnect
from cardid import card_hash
from dossier.model import plain_text, state_index
from dossier.store import write_json

from . import snapshot
from .common import (PlanError, fields, is_cloze, model, note_ids, schedule,
                     fp_for_note, schedule_unchanged, set_base,
                     snapshot_notes, strip_footer)


def _tag(value) -> str:
    return str(value).strip().lower().replace(" ", "_")


def _tags(values) -> list[str]:
    out = []
    for value in values or []:
        tag = _tag(value)
        if tag and tag not in out:
            out.append(tag)
    return out


def _load_edits(path) -> list[dict]:
    try:
        data = json.loads(Path(path).expanduser().read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise PlanError(f"cannot read edits: {e}") from e
    if data.get("schema") != 1 or not isinstance(data.get("edits"), list):
        raise PlanError("edits file needs schema 1 and an 'edits' list")
    return list(data["edits"])


def _resolve(context: dict, edit: dict) -> tuple[int, str]:
    states = state_index(context.get("state") or [])
    cards = context.get("cards") or []
    if edit.get("rev_id"):
        rev = str(edit["rev_id"])
        state = states.get(rev)
        note_id = int((state or {}).get("anki_note_id") or 0)
        if not note_id:
            raise PlanError(f"edit rev_id {rev!r} is not attached")
        return note_id, rev
    if edit.get("front"):
        key = plain_text(edit["front"])
        matches = [str(c.get("rev_id")) for c in cards
                   if plain_text(c.get("front")) == key]
        if len(matches) != 1:
            raise PlanError(f"edit front {edit['front']!r} matches "
                            f"{len(matches)} cards; use rev_id")
        rev = matches[0]
        note_id = int((states.get(rev) or {}).get("anki_note_id") or 0)
        if not note_id:
            raise PlanError(f"card {rev!r} is not attached")
        return note_id, rev
    raise PlanError("each edit needs rev_id or front")


def _check_item(item: dict) -> None:
    if not item.get("fields") and item.get("tags") is None:
        raise PlanError("each edit needs fields and/or tags")
    if item.get("fields") is not None and not isinstance(item["fields"], dict):
        raise PlanError("edit fields must be an object")
    if item.get("tags") is not None and not isinstance(item["tags"], list):
        raise PlanError("edit tags must be a list")


def _restore_card(card: dict, note: dict) -> None:
    data = fields(note)
    if is_cloze(model(note), card):
        card["front"] = strip_footer(data.get("Text", card.get("front", "")))
        card["back"] = strip_footer(data.get("Extra", card.get("back", "")))
        card["cloze"] = True
    else:
        card["front"] = strip_footer(data.get("Front", card.get("front", "")))
        card["back"] = strip_footer(data.get("Back", card.get("back", "")))
    card["content_format"] = "anki-html"
    card["content_hash"] = card_hash({"front": card.get("front", ""),
                                      "back": card.get("back", "")})


def _apply(ac: AnkiConnect, context: dict, deck_name: str, items: list[dict],
           reason: str, *, dry_run: bool = False) -> dict:
    note_ids_ = sorted({int(item["note_id"]) for item in items})
    notes = [n for n in ac.notes_info(note_ids_)
             if isinstance(n, dict) and n.get("noteId")]
    before = {int(n["noteId"]): n for n in notes}
    missing = [nid for nid in note_ids_ if nid not in before]
    if missing:
        raise PlanError(f"{len(missing)} note(s) are gone; re-run attach")
    for item in items:
        nid = int(item["note_id"])
        unknown = [name for name in (item.get("fields") or {})
                   if name not in before[nid]["fields"]]
        if unknown:
            raise PlanError(f"note {nid} has no field(s): {', '.join(unknown)}")

    _, before_cards, before_reviews = schedule(ac, notes)
    if dry_run:
        return {"dry_run": True, "notes": len(items),
                "fields": sum(1 for item in items if item.get("fields") is not None),
                "tags": sum(1 for item in items if item.get("tags") is not None)}

    stamp = dc.now().replace(":", "").replace("-", "").replace("+", "")
    revdir = dc.revision_dir(context["uuid"], stamp)
    snap = snapshot.create(ac, context, deck_name, reason)
    backup = {
        "schema": 1, "created_at": dc.now(), "snapshot_id": snap["snapshot_id"],
        "deck_key": context["uuid"],
        "notes": [{"note_id": nid, "rev_id": next(
            (item.get("rev_id") for item in items
             if int(item["note_id"]) == nid), ""),
            "model": model(before[nid]), "fields": fields(before[nid]),
            "tags": list(before[nid].get("tags") or []),
            "cards": note_ids(before[nid])} for nid in note_ids_],
    }
    write_json(revdir / "edit_backup.json", backup)

    for item in items:
        nid = int(item["note_id"])
        if item.get("fields") is not None:
            ac.update_note_fields(nid, item["fields"])
        if item.get("tags") is not None:
            old = set(before[nid].get("tags") or [])
            new = set(item["tags"] or [])
            if old - new:
                ac.remove_tags([nid], sorted(old - new))
            if new - old:
                ac.add_tags([nid], sorted(new - old))

    after_notes = [n for n in ac.notes_info(note_ids_)
                   if isinstance(n, dict) and n.get("noteId")]
    after = {int(n["noteId"]): n for n in after_notes}
    _, after_cards, after_reviews = schedule(ac, after_notes)
    failures, verified = [], []
    for item in items:
        nid = int(item["note_id"])
        good = nid in after
        if good and item.get("fields") is not None:
            good = all(fields(after[nid]).get(k) == v
                       for k, v in item["fields"].items())
        if good and item.get("tags") is not None:
            good = set(after[nid].get("tags") or []) == set(item["tags"] or [])
        if good and nid in before:
            bfp = fp_for_note(before[nid], before_cards, before_reviews)
            afp = fp_for_note(after[nid], after_cards, after_reviews)
            good = (schedule_unchanged(bfp, afp)
                    and bfp.get("revlog_count") == afp.get("revlog_count"))
        verified.append({"note_id": nid, "ok": good})
        if not good:
            failures.append({"note_id": nid, "reason": "edit verification failed"})

    cards = context.get("cards") or []
    states = context.get("state") or []
    for item in items:
        nid = int(item["note_id"])
        note = after.get(nid)
        if not note:
            continue
        rev = str(item.get("rev_id") or "")
        card = next((c for c in cards if str(c.get("rev_id")) == rev), None)
        state = next((s for s in states if str(s.get("rev_id")) == rev), None)
        if card:
            _restore_card(card, note)
            if item.get("tags") is not None:
                topic_tag = _tag(card.get("topic", ""))
                card["objects"] = [t for t in (item.get("tags") or [])
                                   if t != topic_tag]
        if state:
            set_base(state, note)
    try:
        dc.update_cards(context["uuid"], cards, states, last_update=dc.now())
    except Exception as e:
        failures.append({"dossier": str(e)})

    ok = not failures
    log = {"schema": 1, "edited_at": dc.now(), "deck_key": context["uuid"],
           "snapshot_id": snap["snapshot_id"], "reason": reason,
           "notes": verified, "failures": failures, "verified": ok}
    write_json(revdir / "edit_log.json", log)
    snap_data = snapshot.load(context, snap["snapshot_id"])
    snapshot.mark_apply(snap_data, str(revdir / "edit_log.json"))
    return {"dir": str(revdir), "snapshot_id": snap["snapshot_id"],
            "notes": len(items), "verified": ok, "failures": failures}


def update(ac: AnkiConnect, selector: str, edits_path, *,
           browser_closed: bool = False, dry_run: bool = False) -> dict:
    context = dc.load(selector)
    if not context:
        raise PlanError("no dossier for this deck")
    deck_name = context["manifest"]["deck"]["name"]
    items, seen = [], set()
    for edit in _load_edits(edits_path):
        note_id, rev = _resolve(context, edit)
        if note_id in seen:
            raise PlanError(f"more than one edit targets note {note_id}")
        seen.add(note_id)
        item = {"note_id": note_id, "rev_id": rev}
        if "fields" in edit:
            item["fields"] = dict(edit.get("fields") or {})
        if "tags" in edit:
            item["tags"] = _tags(edit.get("tags") or [])
        _check_item(item)
        items.append(item)
    if (any(item.get("fields") for item in items) and not browser_closed
            and not dry_run):
        raise PlanError("close Anki's Browser window before field edits, then "
                        "pass --browser-closed")
    return _apply(ac, context, deck_name, items, "bulk edit", dry_run=dry_run)


def lowercase_tags(ac: AnkiConnect, selector: str, *,
                   dry_run: bool = False) -> dict:
    context = dc.load(selector)
    if not context:
        raise PlanError("no dossier for this deck")
    deck_name = context["manifest"]["deck"]["name"]
    states = state_index(context.get("state") or [])
    state_by_note = {int(s["anki_note_id"]): s
                     for s in states.values() if s.get("anki_note_id") is not None}
    items = []
    for note in snapshot_notes(ac, deck_name):
        nid = int(note["noteId"])
        target = _tags(note.get("tags") or [])
        if set(target) == set(note.get("tags") or []):
            continue
        state = state_by_note.get(nid) or {}
        items.append({"note_id": nid, "rev_id": state.get("rev_id", ""),
                      "tags": target})
    if not items:
        return {"notes": 0, "verified": True, "snapshot_id": ""}
    return _apply(ac, context, deck_name, items, "tag normalization",
                  dry_run=dry_run)
