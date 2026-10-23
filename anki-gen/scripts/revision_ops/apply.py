"""Apply an approved revision plan with conflicts, backups, and verification."""
from __future__ import annotations

import json
import re
from pathlib import Path

import deck_context as dc
from anki_connect import AnkiConnect, AnkiConnectError
from cardid import card_hash
from dossier.model import (new_uuid, now, plain_text, state_from_existing,
                           state_index)
from dossier.store import write_json

from . import snapshot
from .common import (PlanError, base_conflicts, field_html, fields,
                     fp_for_note, is_cloze, label, model, note_ids,
                     proposed_conflicts, schedule, schedule_unchanged,
                     set_base, strip_footer)


def parse_choices(values: list[str] | None) -> dict[str, str]:
    out = {}
    for value in values or []:
        if "=" not in value:
            raise PlanError("--choice wants GROUP=delete|suspend|keep")
        gid, choice = value.split("=", 1)
        choice = choice.strip().lower()
        if choice not in ("delete", "suspend", "keep"):
            raise PlanError(f"bad choice {choice!r}; use delete, suspend, or keep")
        out[gid.strip()] = choice
    return out


def _row_from_fields(card: dict, note: dict, data: dict) -> None:
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


def _old_note(note: dict, rev_id: str = "") -> dict:
    return {"note_id": int(note["noteId"]), "rev_id": rev_id,
            "model": model(note), "fields": fields(note),
            "tags": list(note.get("tags") or []), "cards": note_ids(note)}


def _load(plan_path) -> tuple[dict, dict]:
    path = Path(plan_path).expanduser()
    try:
        plan = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise PlanError(f"cannot read plan: {e}") from e
    if plan.get("schema") != 1 or not plan.get("deck_key"):
        raise PlanError("unsupported plan schema")
    context = dc.load(plan["deck_key"])
    if not context:
        raise PlanError("plan targets a dossier that no longer exists")
    return plan, context


def apply(ac: AnkiConnect, plan_path, *, choice: list[str] | None = None,
          browser_closed: bool = False, overwrite_conflicts: bool = False,
          allow_card_shape_change: bool = False, allow_low_res: bool = False,
          sync: bool = False) -> dict:
    plan, context = _load(plan_path)
    cards = context["cards"]
    states = [state_from_existing(s) for s in context.get("state", [])]
    state_map = state_index(states)
    card_by_rev = {str(c.get("rev_id")): c for c in cards}
    groups = plan.get("destructive_groups") or []
    choices = parse_choices(choice)
    missing = [g["id"] for g in groups if g["id"] not in choices]
    if missing:
        raise PlanError("destructive choices are required; nothing was written: "
                        + ", ".join(f"--choice {g}=<delete|suspend|keep>"
                                    for g in missing))
    extra = set(choices) - {g["id"] for g in groups}
    if extra:
        raise PlanError(f"unknown group(s): {', '.join(sorted(extra))}")
    fields_needed = any(a["kind"] in ("update_fields", "attach_media") or
                        (a["kind"] == "merge" and a.get("after"))
                        for a in plan.get("actions", []))
    if fields_needed and not browser_closed:
        raise PlanError("close Anki's Browser window before field updates, then "
                        "pass --browser-closed")
    low_res = [a for a in plan.get("actions", [])
               if a["kind"] == "attach_media" and a.get("low_res")]
    if low_res and not allow_low_res:
        raise PlanError("the media source is gone and only a low-res preview "
                        "exists; pass --allow-low-res or re-extract the original")

    note_ids_planned = sorted({
        int(a["note_id"]) for a in plan.get("actions", []) if a.get("note_id")} |
        {int(a["victim_note_id"]) for a in plan.get("actions", [])
         if a.get("victim_note_id")} |
        {int(n) for g in groups for n in g.get("note_ids", []) if n})
    notes = [n for n in ac.notes_info(note_ids_planned)
             if isinstance(n, dict) and n.get("noteId")]
    note_by_id = {int(n["noteId"]): n for n in notes}
    missing_notes = [nid for nid in note_ids_planned if nid not in note_by_id]
    if missing_notes:
        raise PlanError(f"{len(missing_notes)} planned note(s) are gone; "
                        "re-run attach and plan")
    _, card_map, reviews = schedule(ac, notes)

    if not allow_card_shape_change:
        for action in plan.get("actions", []):
            if action["kind"] != "update_fields" or not action.get("after"):
                continue
            note = note_by_id.get(int(action["note_id"]))
            if not note or not is_cloze(model(note)):
                continue
            field = "Text" if "Text" in action["after"] else ""
            if not field:
                continue
            old = set(re.findall(r"\{\{c(\d+)::", fields(note).get(field, "")))
            new = set(re.findall(r"\{\{c(\d+)::", action["after"][field]))
            if old != new:
                raise PlanError("this update changes cloze ordinals; pass "
                                "--allow-card-shape-change after reviewing that "
                                "history consequence")

    conflicts = list(plan.get("conflicts") or [])
    conflict_ids = set()
    for action in plan.get("actions", []):
        note = note_by_id.get(int(action.get("note_id") or 0))
        if not note:
            continue
        if action["kind"] in ("update_fields", "attach_media"):
            base = action.get("before") or {}
            if action["kind"] == "attach_media":
                field = action.get("field") or "Back"
                current = fields(note)
                if plain_text(current.get(field, "")) != plain_text(
                        base.get(field, "")):
                    conflicts.append({"rev_id": action.get("rev_id"),
                                      "label": label(card_by_rev.get(
                                          str(action.get("rev_id")), {})),
                                      "field": field, "base": base.get(field, ""),
                                      "current": current.get(field, ""),
                                      "proposed": "append media"})
                    conflict_ids.add(int(action["note_id"]))
            for conflict in proposed_conflicts(note, base,
                                               action.get("after") or {}):
                conflicts.append({"rev_id": action.get("rev_id"),
                                  "label": label(card_by_rev.get(
                                      str(action.get("rev_id")), {})),
                                  **conflict})
                conflict_ids.add(int(action["note_id"]))
        elif action["kind"] in ("cull", "merge"):
            victim_id = (int(action.get("victim_note_id") or 0)
                         if action["kind"] == "merge" else int(action.get("note_id") or 0))
            victim = note_by_id.get(victim_id)
            if victim:
                for conflict in base_conflicts(victim, action.get("before") or {}):
                    conflicts.append({"rev_id": action.get("victim_rev_id")
                                      or action.get("rev_id"),
                                      "label": label(card_by_rev.get(
                                          str(action.get("rev_id")), {})),
                                      **conflict})
                    conflict_ids.add(victim_id)

    destructive = []
    for group in groups:
        chosen = choices[group["id"]]
        ids = [int(n) for n in group.get("note_ids") or [] if n]
        ids = [n for n in ids if n not in conflict_ids or overwrite_conflicts]
        destructive.append((group, chosen, ids))

    stamp = dc.now().replace(":", "").replace("-", "").replace("+", "")
    revdir = dc.revision_dir(context["uuid"], stamp)
    snap = snapshot.create(ac, context, plan["deck_name"], "before apply")

    update_actions = [
        action for action in plan.get("actions", []) if action.get("note_id")
        and (action["kind"] in ("update_fields", "attach_media")
             or (action["kind"] == "merge" and action.get("after")))]
    updated_ids = {int(action["note_id"]) for action in update_actions}
    affected_revs = {str(action["rev_id"]) for action in update_actions
                     if action.get("rev_id")}
    planned_deleted = sorted({nid for _, chosen, ids in destructive
                              if chosen == "delete" for nid in ids})
    planned_suspended = sorted({nid for _, chosen, ids in destructive
                                if chosen == "suspend" for nid in ids})
    rev_by_note = {int(state["anki_note_id"]): str(state.get("rev_id") or "")
                   for state in states if state.get("anki_note_id") is not None}
    for nid in planned_deleted + planned_suspended:
        if rev_by_note.get(int(nid)):
            affected_revs.add(rev_by_note[int(nid)])
    affected_revs.discard("")
    old_note = {int(n["noteId"]): n for n in notes}
    suspended_cards = [
        {"note_id": nid, "card_id": card_id,
         "queue": (card_map.get(card_id) or {}).get("queue"),
         "type": (card_map.get(card_id) or {}).get("type")}
        for nid in planned_suspended
        for card_id in note_ids(old_note.get(nid) or {})]
    backup = {
        "schema": 1, "created_at": dc.now(), "deck_key": context["uuid"],
        "plan": str(plan_path), "snapshot_id": snap["snapshot_id"],
        "updated_notes": [_old_note(old_note[nid], rev_by_note.get(nid, ""))
                          for nid in sorted(updated_ids) if nid in old_note],
        "deleted_notes": [_old_note(old_note[nid], rev_by_note.get(nid, ""))
                          for nid in planned_deleted if nid in old_note],
        "suspended_notes": [_old_note(old_note[nid], rev_by_note.get(nid, ""))
                            for nid in planned_suspended if nid in old_note],
        "suspended_cards": suspended_cards,
        "cards": [row for row in cards
                  if str(row.get("rev_id")) in affected_revs],
        "state": [row for row in states
                  if str(row.get("rev_id")) in affected_revs],
    }
    write_json(revdir / "backup.json", backup)
    write_json(revdir / "conflicts.json", {"conflicts": conflicts})

    updated, added, suspended, deleted, kept, failures = [], [], [], [], [], []
    before_notes = {int(n["noteId"]): n for n in notes}
    verification = []

    def update_note(action: dict) -> None:
        nid = int(action["note_id"])
        note = note_by_id[nid]
        card = card_by_rev.get(str(action.get("rev_id")), {})
        state = state_map.get(str(action.get("rev_id"))) or state_from_existing(
            {"rev_id": action.get("rev_id")})
        current = fields(note)
        proposed = dict(action.get("after") or {})
        if action["kind"] == "attach_media":
            cand = action.get("candidate") or {}
            original = Path(str(cand.get("original_path") or ""))
            preview = (Path(context["path"]) / str(cand.get("preview") or "")
                       if cand.get("preview") else None)
            source = original if original.is_file() else preview
            if not source or not source.is_file():
                failures.append({"note_id": nid,
                                 "reason": "media source and preview are missing"})
                return
            if not original.is_file():
                print(f"revision.py: warning: using a low-res preview for "
                      f"{cand.get('file')}", file=__import__("sys").stderr)
            ac.store_media_file(action["media_filename"], path=source)
            proposed = {action["field"]:
                        current.get(action["field"], "") + action.get("snippet", "")}
        else:
            for name, value in list(proposed.items()):
                proposed[name] = field_html(
                    value, current.get(name, ""), back=name in ("Back", "Extra"),
                    source=str(card.get("source") or ""),
                    source_url=str(card.get("source_url") or ""))
        if nid in conflict_ids and not overwrite_conflicts:
            return
        if is_cloze(model(note), card) and "Text" in proposed:
            old = set(re.findall(r"\{\{c(\d+)::", current.get("Text", "")))
            new = set(re.findall(r"\{\{c(\d+)::", proposed["Text"]))
            if old != new and not allow_card_shape_change:
                failures.append({"note_id": nid,
                                 "reason": "cloze ordinals change"})
                return
        ac.update_note_fields(nid, proposed)
        updated.append({"note_id": nid, "rev_id": action.get("rev_id"),
                        "fields": list(proposed), "wanted": proposed})

    for action in plan.get("actions", []):
        if action["kind"] in ("update_fields", "attach_media") or (
                action["kind"] == "merge" and action.get("after")):
            update_note(action)

    for action in plan.get("actions", []):
        if action["kind"] != "split":
            continue
        note = note_by_id[int(action["note_id"])]
        model_name = model(note)
        new_notes = []
        for new in action.get("new") or []:
            front = field_html(new.get("front", ""))
            back = field_html(new.get("back", ""), back=True,
                              source=str(new.get("source") or ""),
                              source_url=str(new.get("source_url") or ""))
            data = ({"Text": front, "Extra": back} if "Cloze" in model_name
                    else {"Front": front, "Back": back})
            data.update({"Layer": new.get("layer") or "",
                         "Topic": new.get("topic") or "", "Media": ""})
            new_notes.append({"deckName": plan["deck_name"], "modelName": model_name,
                              "fields": data, "tags": list(note.get("tags") or []),
                              "options": {"allowDuplicate": False}})
        ids = ac.add_notes(new_notes)
        for new, nid in zip(action.get("new") or [], ids):
            if not nid:
                failures.append({"split": action.get("rev_id"),
                                 "reason": "addNotes returned no id"})
                continue
            rev = new_uuid()
            card = {
                "rev_id": rev, "guid": "", "guid_alg": "md5",
                "front": new["front"], "back": new["back"],
                "content_format": "authoring",
                "content_hash": card_hash(new), "content_hash_alg": "md5",
                "layer": new.get("layer") or "", "topic": new.get("topic") or "",
                "deck": plan["deck_name"], "objects": new.get("objects") or [],
                "tier_zero": False, "cloze": bool(new.get("cloze")),
                "stratum": "", "retrieval_target": "", "why": "",
                "source": new.get("source") or "",
                "source_url": new.get("source_url") or "", "media": [],
                "review_score": None, "extra": {},
            }
            state = state_from_existing({"rev_id": rev, "anki_note_id": int(nid),
                                         "state": "live"})
            cards.append(card)
            state_map[rev] = state
            states.append(state)
            added.append({"note_id": int(nid), "rev_id": rev})

    for group, chosen, ids in destructive:
        if not ids:
            continue
        if chosen == "keep":
            kept.extend(ids)
            continue
        if chosen == "delete":
            ac.delete_notes(ids)
            deleted.extend(ids)
            for nid in ids:
                state = next((s for s in states if s.get("anki_note_id") == nid), None)
                if state:
                    state["state"] = "deleted"
        else:
            card_ids = [cid for nid in ids for cid in note_ids(before_notes[nid])]
            ac.suspend(card_ids)
            suspended.extend(ids)
            for nid in ids:
                state = next((s for s in states if s.get("anki_note_id") == nid), None)
                if state:
                    state["state"] = "suspended"

    affected = {int(a["note_id"]) for a in plan.get("actions", [])
                if a.get("note_id")} | set(deleted) | set(suspended)
    after_notes = {}
    if affected:
        for note in ac.notes_info(sorted(affected)):
            if isinstance(note, dict) and note.get("noteId"):
                after_notes[int(note["noteId"])] = note
        _, after_cards, after_reviews = schedule(ac, list(after_notes.values()))
    else:
        after_cards, after_reviews = {}, {}
    ok = True
    for item in updated:
        nid = item["note_id"]
        before_note = before_notes.get(nid)
        after_note = after_notes.get(nid)
        if not after_note:
            verification.append({"note_id": nid, "ok": False,
                                 "reason": "note disappeared"})
            ok = False
            continue
        field_ok = all(fields(after_note).get(k) == v
                       for k, v in (item.get("wanted") or {}).items())
        bfp = fp_for_note(before_note, card_map, reviews) if before_note else {
            "cards": [], "revlog_count": 0}
        afp = fp_for_note(after_note, after_cards, after_reviews)
        sched_ok = schedule_unchanged(bfp, afp)
        rev_ok = bfp.get("revlog_count") == afp.get("revlog_count")
        verification.append({"note_id": nid, "fields_ok": field_ok,
                             "scheduling_ok": sched_ok, "revlog_ok": rev_ok,
                             "ok": field_ok and sched_ok and rev_ok})
        ok = ok and field_ok and sched_ok and rev_ok
    for action in plan.get("actions", []):
        if action["kind"] not in ("split", "merge"):
            continue
        nid = int(action["note_id"])
        before_note = before_notes.get(nid)
        after_note = after_notes.get(nid)
        good = bool(before_note and after_note)
        if good:
            bfp = fp_for_note(before_note, card_map, reviews)
            afp = fp_for_note(after_note, after_cards, after_reviews)
            good = (schedule_unchanged(bfp, afp)
                    and bfp.get("revlog_count") == afp.get("revlog_count"))
        verification.append({"note_id": nid, "ok": good,
                             "reason": f"{action['kind']} keeps existing history"})
        ok = ok and good
    for nid in deleted:
        good = nid not in after_notes
        verification.append({"note_id": nid, "ok": good, "reason": "deleted"})
        ok = ok and good
    for nid in suspended:
        after = after_notes.get(nid)
        good = bool(after) and all(after_cards.get(cid, {}).get("queue") == -1
                                   for cid in note_ids(after))
        verification.append({"note_id": nid, "ok": good, "reason": "suspended"})
        ok = ok and good
    for item in added:
        exists = [n for n in ac.notes_info([item["note_id"]])
                  if isinstance(n, dict) and n.get("noteId") and n.get("cards")]
        verification.append({"note_id": item["note_id"], "ok": bool(exists),
                             "reason": "new card added"})
        ok = ok and bool(exists)

    for item in updated:
        nid = item["note_id"]
        rev = str(item.get("rev_id"))
        card = card_by_rev.get(rev)
        state = state_map.get(rev)
        note = after_notes.get(nid)
        if card and state and note:
            _row_from_fields(card, note, fields(note))
            set_base(state, note)
            fp, _, _ = schedule(ac, [note])
            state["scheduling"] = fp
            state["state"] = "live"
    for nid in suspended:
        state = next((s for s in states if s.get("anki_note_id") == nid), None)
        if state:
            state["state"] = "suspended"
    for nid in deleted:
        state = next((s for s in states if s.get("anki_note_id") == nid), None)
        if state:
            state["state"] = "deleted"

    dc.update_cards(context["uuid"], cards, states, last_update=now())

    sync_ok = None
    if sync and ok:
        try:
            ac.sync()
            sync_ok = True
        except AnkiConnectError as e:
            failures.append({"sync": str(e)})
            sync_ok = False
    ok = ok and not failures
    log = {"schema": 1, "plan": str(plan_path), "snapshot_id": snap["snapshot_id"],
           "applied_at": dc.now(), "deck_key": context["uuid"],
           "updated": updated, "added": added, "suspended": suspended,
           "deleted": deleted, "kept": kept, "conflicts": conflicts,
           "failures": failures, "verification": verification,
           "verified": ok, "sync": sync_ok}
    write_json(revdir / "apply_log.json", log)
    write_json(revdir / "verification.json",
               {"verified": ok, "checks": verification})
    snap_data = snapshot.load(context, snap["snapshot_id"])
    snapshot.mark_apply(snap_data, str(revdir / "apply_log.json"))
    return {"dir": str(revdir), "snapshot_id": snap["snapshot_id"],
            "updated": len(updated), "added": len(added),
            "suspended": len(suspended), "deleted": len(deleted),
            "kept": len(kept), "conflicts": len(conflicts), "verified": ok}
