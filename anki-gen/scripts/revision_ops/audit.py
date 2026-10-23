"""Read-only deck/context audit."""
from __future__ import annotations

from collections import defaultdict

import deck_context as dc
from anki_connect import AnkiConnect
from dossier.model import card_key

from .common import (find_ctx, label, live_deck_name, note_key, schedule,
                     snapshot_notes, states_by_rev)


def audit(ac: AnkiConnect, selector: str, *, as_json: bool = False) -> dict:
    context = find_ctx(ac, selector)
    deck_name = live_deck_name(ac, context, selector)
    notes = snapshot_notes(ac, deck_name)
    if context is None:
        from .attach import _reconstruct
        cards, states = _reconstruct(ac, notes, deck_name)
    else:
        cards, states = context["cards"], context.get("state", [])
    smap = states_by_rev({"state": states})
    live_ids = {int(n["noteId"]) for n in notes}
    matched, missing, drift = [], [], []
    for card in cards:
        state = smap.get(str(card.get("rev_id"))) or {}
        nid = state.get("anki_note_id")
        if nid is not None and int(nid) in live_ids:
            matched.append(card)
        elif state.get("state", "live") == "live" and state.get("anki_note_id"):
            missing.append(card)
        note = next((n for n in notes if int(n["noteId"]) == int(nid or 0)), None)
        if note and note_key(note) != card_key(card):
            drift.append({"rev_id": card.get("rev_id"), "note_id": int(nid),
                          "topic": card.get("topic"), "front": label(card)})
    matched_ids = {int((smap.get(str(c.get("rev_id"))) or {}).get("anki_note_id"))
                   for c in matched}
    unmatched = [int(n["noteId"]) for n in notes
                 if int(n["noteId"]) not in matched_ids]
    topics = defaultdict(int)
    for card in matched:
        topics[str(card.get("topic") or "?")] += 1
    fp, card_map, _ = schedule(ac, notes)
    warnings = dc.validate(deck_key_or_selector=context["uuid"])["warnings"] if context else []
    report = {
        "schema": 1, "audit_at": dc.now(), "deck": deck_name,
        "dossier": context["uuid"] if context else None,
        "confidence": (context["manifest"].get("confidence")
                       if context else "reconstructed"),
        "live_notes": len(notes), "live_cards": len(card_map),
        "dossier_cards": len(cards), "matched": len(matched),
        "missing_live": [c.get("rev_id") for c in missing],
        "unmatched_live": unmatched, "field_drift": drift,
        "topics": dict(sorted(topics.items())), "scheduling": fp,
        "context_warnings": len(warnings),
    }
    if not as_json:
        print(f"audit      {report['live_notes']} live note(s), "
              f"{report['matched']}/{report['dossier_cards']} dossier card(s) matched")
        print(f"           {len(missing)} missing live · {len(unmatched)} live "
              f"not in dossier · {len(drift)} manual edit(s)")
        print(f"           {report['live_cards']} card(s), {fp['revlog_count']} "
              f"review row(s), confidence {report['confidence']}")
    return report
