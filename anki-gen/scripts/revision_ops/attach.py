"""Attach live Anki note IDs to dossier cards (read-only in Anki)."""
from __future__ import annotations

import re
import uuid

import deck_context as dc
from dossier import index as idx
from cardid import card_hash
from dossier.model import (card_key, new_uuid, now, state_from_existing,
                           state_index)
from anki_connect import AnkiConnect

from .common import (PlanError, fields, group_rows, label, live_deck_name,
                     model, note_ids, note_key, schedule, set_base,
                     snapshot_notes)


def _reconstruct(ac: AnkiConnect, notes: list[dict], deck_name: str):
    cards, states = [], []
    for note in notes:
        f = fields(note)
        front, back = (f.get("Text", ""), f.get("Extra", "")) if "cloze" in model(note).lower() else (
            f.get("Front", ""), f.get("Back", ""))
        tags = list(note.get("tags") or [])
        topic = tags[0].replace("_", " ") if tags else "Imported"
        source = ""
        m = re.search(r'<div[^>]*class="src"[^>]*>(.*?)</div>', back, re.S | re.I)
        if m:
            source = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()
        clean_front = re.sub(r'<div[^>]*class="src"[^>]*>.*?</div>', "", front,
                             flags=re.S | re.I).strip()
        clean_back = re.sub(r'<div[^>]*class="src"[^>]*>.*?</div>', "", back,
                            flags=re.S | re.I).strip()
        card = {
            "rev_id": new_uuid(), "guid": "", "guid_alg": "md5",
            "front": clean_front, "back": clean_back,
            "content_format": "anki-html",
            "content_hash": card_hash({"front": clean_front, "back": clean_back}),
            "content_hash_alg": "md5", "layer": f.get("Layer", ""),
            "topic": topic, "deck": deck_name, "objects": tags[1:],
            "tier_zero": False, "cloze": "cloze" in model(note).lower(),
            "stratum": "", "kc": "", "retrieval_target": "", "why": "",
            "source": source, "source_url": "", "media": [],
            "review_score": None, "extra": {},
        }
        state = state_from_existing({"rev_id": card["rev_id"],
                                     "anki_note_id": int(note["noteId"]),
                                     "state": "live"})
        set_base(state, note)
        cards.append(card)
        states.append(state)
    return cards, states


def _attach(ac: AnkiConnect, context: dict, deck_name: str,
            maps: dict[str, int] | None = None) -> dict:
    notes = snapshot_notes(ac, deck_name)
    cards = context["cards"]
    states = [state_from_existing(s) for s in context.get("state", [])]
    smap = state_index(states)
    note_by_id = {int(n["noteId"]): n for n in notes}
    by_key = {}
    for note in notes:
        by_key.setdefault(note_key(note), []).append(note)

    assigned: dict[int, int] = {}
    claimed = set()
    for rev, nid in (maps or {}).items():
        index = next((i for i, c in enumerate(cards) if c.get("rev_id") == rev), None)
        if index is None:
            raise PlanError(f"--map refers to an unknown rev_id: {rev}")
        if int(nid) not in note_by_id:
            raise PlanError(f"--map note id is not in this deck: {nid}")
        if int(nid) in claimed:
            raise PlanError(f"--map note id is already assigned: {nid}")
        assigned[index] = int(nid)
        claimed.add(int(nid))

    for index, card in enumerate(cards):
        if index in assigned:
            continue
        state = smap.get(str(card.get("rev_id"))) or {}
        if state.get("state") in ("deleted", "stale"):
            continue
        try:
            nid = int(state.get("anki_note_id"))
        except (TypeError, ValueError):
            continue
        if nid in note_by_id and nid not in claimed:
            assigned[index] = nid
            claimed.add(nid)

    ambiguous = []
    for key, entries in group_rows(cards, assigned).items():
        candidates = [n for n in by_key.get(key, []) if int(n["noteId"]) not in claimed]
        if len(entries) == 1 and len(candidates) == 1:
            index, _ = entries[0]
            assigned[index] = int(candidates[0]["noteId"])
            claimed.add(int(candidates[0]["noteId"]))
        elif candidates and (len(entries) > 1 or len(candidates) > 1):
            ambiguous.append({
                "rev_ids": [c.get("rev_id") for _, c in entries],
                "cards": [label(c) for _, c in entries],
                "notes": [{"note_id": int(n["noteId"]), "front": label({
                    "front": (fields(n).get("Front") or fields(n).get("Text", "")),
                    "topic": (n.get("tags") or ["Imported"])[0].replace("_", " "),
                    "layer": fields(n).get("Layer", "")})} for n in candidates],
            })
    if ambiguous:
        return {"status": "ambiguous", "ambiguous": ambiguous,
                "matched": len(assigned), "live_notes": len(notes)}

    fp, card_map, reviews = schedule(ac, notes)
    drift = []
    for index, nid in assigned.items():
        card = cards[index]
        note = note_by_id[nid]
        state = smap.get(str(card.get("rev_id")))
        if state is None:
            state = state_from_existing({"rev_id": card.get("rev_id")})
            states.append(state)
            smap[str(card.get("rev_id"))] = state
        if note_key(note) != card_key(card):
            drift.append({"rev_id": card.get("rev_id"), "note_id": nid,
                          "base": label(card),
                          "live_front": (fields(note).get("Front")
                                         or fields(note).get("Text", ""))[:120]})
        state["anki_note_id"] = nid
        state["state"] = "live"
        set_base(state, note)
        cards_for_note = [card_map[c] for c in note_ids(note) if c in card_map]
        state["scheduling"] = {
            "cards": [{k: c.get(k) for k in
                       ("cardId", "due", "interval", "ivl", "factor", "reps",
                        "lapses", "queue", "type", "left") if k in c}
                      for c in cards_for_note]}
        state["revlog_count"] = sum(
            len((reviews or {}).get(str(c.get("cardId")))
                or (reviews or {}).get(c.get("cardId")) or [])
            for c in cards_for_note)
        state["last_verified"] = now()
    assigned_ids = set(assigned.values())
    unmatched_rows = [c.get("rev_id") for c in cards
                      if int((smap.get(str(c.get("rev_id"))) or {}).get(
                          "anki_note_id") or 0) not in note_by_id
                      and (smap.get(str(c.get("rev_id"))) or {}).get("state") not in
                      ("deleted", "stale")]
    unmatched_notes = [int(n["noteId"]) for n in notes
                       if int(n["noteId"]) not in claimed]
    registry = {"deck_name": deck_name,
                "deck_id": str(ac.deck_names_and_ids().get(deck_name, "")),
                "profile": "",
                "notetypes": sorted({model(n) for n in notes if model(n)})}
    dc.update_cards(context["uuid"], cards, states, last_attach=now())
    idx.register(context["uuid"], registry)
    stamp = dc.now().replace(":", "").replace("-", "").replace("+", "")
    log = dc.revision_dir(context["uuid"], stamp) / "attach.json"
    dc.write_json(log, {
        "schema": 1, "attached_at": dc.now(), "deck": deck_name,
        "matched": len(assigned), "live_notes": len(notes),
        "unmatched_rows": unmatched_rows,
        "unmatched_notes": unmatched_notes, "field_drift": drift,
    })
    return {"status": "ok", "key": context["uuid"], "matched": len(assigned),
            "live_notes": len(notes), "unmatched_rows": len(unmatched_rows),
            "unmatched_notes": len(unmatched_notes), "field_drift": drift}


def attach(ac: AnkiConnect, selector: str, *, reconstruct: bool = False,
           maps: dict[str, int] | None = None) -> dict:
    context = common_find(ac, selector)
    if context is None:
        if not reconstruct:
            raise PlanError("no dossier for this deck; pass --reconstruct")
        deck_name = selector
        notes = snapshot_notes(ac, deck_name)
        cards, states = _reconstruct(ac, notes, deck_name)
        saved = dc.save({"deck_name": deck_name,
                         "deck_id": str(ac.deck_names_and_ids().get(deck_name, ""))},
                        cards, states, sources=[], media=[],
                        confidence="reconstructed",
                        artifacts={
                            "intake.md": "# Intake\n\n- Reconstructed from AnkiConnect; "
                                         "the original intake is unavailable.",
                            "scope_gate.md": "# Scope gate\n\n- Reconstructed; no "
                                           "authored scope gate is available.",
                            "authoring_ledger.md": "# Authoring ledger\n\n- "
                                                 "Reconstructed; no authored ledger is available.",
                        })
        context = dc.load(saved["key"])
    name = live_deck_name(ac, context, selector)
    return _attach(ac, context, name, maps)


def common_find(ac: AnkiConnect, selector: str):
    from .common import find_ctx
    return find_ctx(ac, selector)


def attach_key(uuid: str, url: str | None = None,
               maps: dict[str, int] | None = None) -> dict:
    ac = AnkiConnect(url=url)
    ac.ensure_available()
    context = dc.load(uuid)
    return _attach(ac, context, live_deck_name(ac, context, None), maps)
