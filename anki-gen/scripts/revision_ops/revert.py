"""Revert one applied revision from an AnkiConnect snapshot."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import deck_context as dc
from anki_connect import AnkiConnect, AnkiConnectError
from cardid import card_hash
from dossier.model import state_from_existing, state_index
from dossier.store import write_json

from . import snapshot
from .common import PlanError, fields, label, note_ids, snapshot_notes, strip_footer


def _latest_log(context: dict) -> tuple[dict, Path]:
    root = Path(context["path"]) / "revisions"
    logs = sorted(root.glob("*/apply_log.json"), key=lambda p: p.stat().st_mtime)
    for path in reversed(logs):
        try:
            log = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if log.get("snapshot_id"):
            return log, path
    raise FileNotFoundError("no applied revision with a snapshot")


def _snapshot_for_log(context: dict, log: dict) -> dict:
    data = snapshot.load(context, log["snapshot_id"])
    return data


def _load_backup(log_path: Path) -> dict:
    path = Path(log_path).parent / "backup.json"
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise PlanError(f"cannot read revision backup: {e}") from e


def _restore_row(smap: dict[str, dict], rev: str,
                 old_row: dict | None) -> dict | None:
    row = smap.get(str(rev))
    if row is not None and old_row:
        row.clear()
        row.update(old_row)
    return row


def _current(ac: AnkiConnect, deck_name: str) -> list[dict]:
    return snapshot_notes(ac, deck_name)


def revert(ac: AnkiConnect, selector: str, *, snapshot_id: str = "last",
           force: bool = False, browser_closed: bool = False,
           sync: bool = False, dry_run: bool = False) -> dict:
    context = dc.load(selector)
    if not context:
        raise PlanError("no dossier for this deck")
    if snapshot_id in ("last", "latest", ""):
        log, log_path = _latest_log(context)
    else:
        snapshot.load(context, snapshot_id)
        log_paths = list((Path(context["path"]) / "revisions").glob(
            "*/apply_log.json"))
        log = next((json.loads(p.read_text()) for p in log_paths
                    if json.loads(p.read_text()).get("snapshot_id") == snapshot_id),
                   None)
        if log is None:
            raise PlanError("no apply log matches that snapshot")
        log_path = next(p for p in log_paths
                        if json.loads(p.read_text()).get("snapshot_id") == snapshot_id)
    snap = _snapshot_for_log(context, log)
    backup = _load_backup(log_path)
    old_notes = {
        int(note["note_id"]): note
        for key in ("updated_notes", "deleted_notes", "suspended_notes")
        for note in backup.get(key) or [] if note.get("note_id") is not None}
    old_cards = {int(card["card_id"]): card
                 for card in backup.get("suspended_cards") or []
                 if card.get("card_id") is not None}
    backup_cards = {str(card.get("rev_id")): card
                    for card in backup.get("cards") or []}
    backup_states = {str(state.get("rev_id")): state
                     for state in backup.get("state") or []}
    old_state_by_note = {int(state["anki_note_id"]): state
                         for state in backup.get("state") or []
                         if state.get("anki_note_id") is not None}
    deck_name = log.get("deck") or context["manifest"]["deck"]["name"]
    if not browser_closed and (log.get("updated") or log.get("deleted")):
        raise PlanError("close Anki's Browser window before reverting field "
                        "updates, then pass --browser-closed")
    actions = {
        "updated": list(log.get("updated") or []),
        "added": list(log.get("added") or []),
        "deleted": list(log.get("deleted") or []),
        "suspended": list(log.get("suspended") or []),
    }
    if dry_run:
        return {"dry_run": True, "snapshot_id": snap["snapshot_id"],
                "counts": {k: len(v) for k, v in actions.items()},
                "log": str(log_path)}

    pre = snapshot.create(ac, context, deck_name, "before revert")
    current = _current(ac, deck_name)
    current_by_id = {int(n["noteId"]): n for n in current}
    snap_notes = old_notes
    snap_cards = old_cards
    conflicts, failures = [], []
    restored = []
    removed = []
    restored_targets: dict[int, dict] = {}

    # 1. Remove notes added by the revision, unless the user has edited them.
    for item in actions["added"]:
        nid = int(item["note_id"])
        note = current_by_id.get(nid)
        if not note:
            continue
        wanted = next((u.get("wanted") or {} for u in actions["updated"]
                       if u.get("note_id") == nid), {})
        if wanted:
            actual = fields(note)
            if any(actual.get(k) != v for k, v in wanted.items()) and not force:
                conflicts.append({"note_id": nid, "label": "added card",
                                  "reason": "user edited it after apply"})
                continue
        ac.delete_notes([nid])
        removed.append(nid)

    # 2. Restore fields updated by the revision by note ID.
    for item in actions["updated"]:
        nid = int(item["note_id"])
        note = current_by_id.get(nid)
        target = snap_notes.get(nid)
        if not note or not target:
            failures.append({"note_id": nid, "reason": "note or backup entry missing"})
            continue
        wanted = item.get("wanted") or {}
        actual = fields(note)
        if wanted and any(actual.get(k) != v for k, v in wanted.items()) and not force:
            conflicts.append({"note_id": nid, "label": label({
                "front": target.get("fields", {}).get("Front")
                or target.get("fields", {}).get("Text", "")}),
                "reason": "user edited it after apply"})
            continue
        target_fields = dict(target.get("fields") or {})
        if target_fields:
            ac.update_note_fields(nid, target_fields)
        restored.append(nid)
        restored_targets[nid] = target_fields

    # 3. Restore notes deleted by the revision. importPackage is the only
    # AnkiConnect route that can carry the old scheduling history back.
    deleted_ids = [int(n) for n in actions["deleted"]]
    restored_map: dict[int, int] = {}
    if deleted_ids:
        _import_snapshot(ac, snap)
        after = _current(ac, deck_name)
        after_by_id = {int(n["noteId"]): n for n in after}
        before_ids = set(current_by_id)
        newly_added = [n for n in after if int(n["noteId"]) not in before_ids]
        deleted_snap_notes = {nid: snap_notes[nid] for nid in deleted_ids
                              if nid in snap_notes}
        used = set()
        for old_id, target in deleted_snap_notes.items():
            key = (dc.plain_text(target.get("fields", {}).get("Front")
                                 or target.get("fields", {}).get("Text", "")),
                   dc.plain_text(target.get("fields", {}).get("Back")
                                 or target.get("fields", {}).get("Extra", "")))
            match = next((n for n in newly_added
                          if int(n["noteId"]) not in used
                          and (dc.plain_text(fields(n).get("Front")
                                             or fields(n).get("Text", "")) == key[0])
                          and (dc.plain_text(fields(n).get("Back")
                                             or fields(n).get("Extra", "")) == key[1])),
                         None)
            if not match:
                failures.append({"note_id": old_id,
                                 "reason": "importPackage did not restore the note"})
                continue
            used.add(int(match["noteId"]))
            target_fields = dict(target.get("fields") or {})
            if target_fields and fields(match) != target_fields:
                ac.update_note_fields(int(match["noteId"]), target_fields)
            restored.append(int(match["noteId"]))
            restored_targets[int(match["noteId"])] = target_fields
            restored_map[old_id] = int(match["noteId"])
        # importPackage can also restore notes the user deleted outside this
        # revision; keep those deletions.
        for note in newly_added:
            nid = int(note["noteId"])
            if nid not in used:
                ac.delete_notes([nid])
                removed.append(nid)

    # 4. Restore suspension state.
    unsuspended = []
    for nid in actions["suspended"]:
        note = current_by_id.get(int(nid))
        if not note:
            continue
        card_ids = [cid for cid in note_ids(note)
                    if (snap_cards.get(cid) or {}).get("queue", -1) != -1]
        if card_ids:
            ac.unsuspend(card_ids)
            unsuspended.append(int(nid))

    # 5. Update affected dossier rows from the pre-apply backup.
    cards = context["cards"]
    states = [state_from_existing(s) for s in context.get("state", [])]
    smap = state_index(states)

    def restore_rows(rev, target: dict | None = None) -> dict | None:
        rev = str(rev or "")
        state = _restore_row(smap, rev, backup_states.get(rev))
        card = next((c for c in cards if str(c.get("rev_id")) == rev), None)
        if card is not None:
            old_card = backup_cards.get(rev)
            if old_card:
                card.clear()
                card.update(old_card)
            elif target:
                _restore_card(card, target)
        return state

    for item in actions["updated"]:
        nid = int(item["note_id"])
        if nid not in restored:
            continue
        target = snap_notes.get(nid)
        state = restore_rows(item.get("rev_id"), target)
        if target and state:
            state["anki_fields_base"] = dict(target.get("fields") or {})
            state["state"] = "live"
            state["last_verified"] = dc.now()
    for old_id, new_id in restored_map.items():
        old_state = old_state_by_note.get(old_id) or _state_for_note(context, old_id) or {}
        target = snap_notes.get(old_id) or {}
        state = restore_rows(old_state.get("rev_id"), target)
        if state:
            state["anki_note_id"] = new_id
            state["state"] = "live"
            state["anki_fields_base"] = dict(target.get("fields") or {})
            state["last_verified"] = dc.now()
    for nid in actions["suspended"]:
        old_state = old_state_by_note.get(int(nid)) or {}
        if not old_state:
            continue
        state = restore_rows(old_state.get("rev_id"))
        if state and int(nid) in unsuspended:
            state["state"] = "live"
            state["last_verified"] = dc.now()
    for nid in removed:
        state = next((s for s in states if s.get("anki_note_id") == nid), None)
        if state:
            state["state"] = "deleted"
            state["anki_note_id"] = None
    removed_revs = {u.get("rev_id") for u in actions["added"]
                    if int(u.get("note_id") or 0) in removed}
    cards = [c for c in cards if c.get("rev_id") not in removed_revs]
    states = [s for s in states if s.get("rev_id") not in removed_revs]

    # Verify field restores and removals.
    try:
        after = _current(ac, deck_name)
        after_by_id = {int(n["noteId"]): n for n in after}
        for nid, target in restored_targets.items():
            note = after_by_id.get(nid)
            if not note or any(fields(note).get(k) != v for k, v in target.items()):
                failures.append({"note_id": nid, "reason": "restored fields do not match"})
        for nid in removed:
            if nid in after_by_id:
                failures.append({"note_id": nid, "reason": "note was not removed"})
    except Exception as e:
        failures.append({"verification": str(e)})
    ok = not failures
    try:
        dc.update_cards(context["uuid"], cards, states, last_update=dc.now())
    except Exception as e:
        failures.append({"dossier": str(e)})
        ok = False
    sync_ok = None
    if sync and ok:
        try:
            ac.sync()
            sync_ok = True
        except AnkiConnectError as e:
            failures.append({"sync": str(e)})
            sync_ok = False
    stamp = dc.now().replace(":", "").replace("-", "").replace("+", "")
    revdir = dc.revision_dir(context["uuid"], stamp)
    log_out = {
        "schema": 1, "reverted_at": dc.now(), "deck_key": context["uuid"],
        "source_apply_log": str(log_path), "snapshot_id": snap["snapshot_id"],
        "pre_revert_snapshot": pre["snapshot_id"], "restored": restored,
        "removed": removed, "unsuspended": unsuspended,
        "conflicts": conflicts, "failures": failures, "verified": ok,
        "sync": sync_ok,
    }
    write_json(revdir / "revert_log.json", log_out)
    snap_file = Path(snap["_dir"]) / "snapshot.json"
    data = json.loads(snap_file.read_text())
    data["reverted_by"] = pre["snapshot_id"]
    write_json(snap_file, data)
    return {"dir": str(revdir), "snapshot_id": snap["snapshot_id"],
            "pre_revert_snapshot": pre["snapshot_id"], "restored": len(restored),
            "removed": len(removed), "unsuspended": len(unsuspended),
            "conflicts": len(conflicts), "verified": ok}


def _restore_card(card: dict, target: dict) -> None:
    data = dict(target.get("fields") or {})
    if "cloze" in str(target.get("model") or "").lower():
        card["front"] = strip_footer(data.get("Text", card.get("front", "")))
        card["back"] = strip_footer(data.get("Extra", card.get("back", "")))
        card["cloze"] = True
    else:
        card["front"] = strip_footer(data.get("Front", card.get("front", "")))
        card["back"] = strip_footer(data.get("Back", card.get("back", "")))
    card["content_format"] = "anki-html"
    card["content_hash"] = card_hash({"front": card.get("front", ""),
                                      "back": card.get("back", "")})


def _state_for_note(context: dict, note_id: int) -> dict | None:
    for state in context.get("state") or []:
        if int(state.get("anki_note_id") or 0) == int(note_id):
            return state
    return None


def _import_snapshot(ac: AnkiConnect, snap: dict) -> None:
    """Import via the collection media dir when AnkiConnect expects a relative path."""
    source = Path(snap["_dir"]) / snap["apkg"]
    name = f"anki-gen-revert-{snap['snapshot_id']}.apkg"
    try:
        media = Path(ac.get_media_dir_path())
        dest = media / name
        shutil.copy2(source, dest)
        try:
            ac.import_package(name)
        finally:
            dest.unlink(missing_ok=True)
    except Exception:
        ac.import_package(source)
