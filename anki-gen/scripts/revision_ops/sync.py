"""Plan a sync of an authored card set into an attached live deck.

The plan is read-only. `revision.py apply` takes the snapshot and writes the
changes. Matching is deterministic: rev_id, content hash, then exact normalized
front/back. Ambiguity is reported, never guessed.
"""
from __future__ import annotations

import deck_context as dc
from cardid import card_hash, load_cards
from dossier.model import now, state_index
from dossier.store import write_json

from .common import (PlanError, base_fields, card_key, field_html, fields,
                     live_deck_name, model, row_fields, snapshot_notes)


def parse_maps(values: list[str] | None) -> dict[int, str]:
    """--map REV_ID=INDEX, where INDEX is the 1-based line in cards.jsonl."""
    out = {}
    for value in values or []:
        if "=" not in value:
            raise PlanError("--map wants REV_ID=INDEX")
        rev, index = value.split("=", 1)
        try:
            n = int(index)
        except ValueError as e:
            raise PlanError(f"bad card index in --map {value!r}") from e
        if n < 1:
            raise PlanError("card index in --map is 1-based")
        out[n] = rev.strip()
    return out


def _notetype(context: dict, cloze: bool) -> str:
    names = list((context.get("manifest") or {}).get("deck", {}).get("notetypes")
                 or [])
    for name in names:
        if ("cloze" in str(name).lower()) == bool(cloze):
            return str(name)
    return "3-Layer STEM Cloze" if cloze else "3-Layer STEM"


def _rendered(card: dict, current: dict | None, model_name: str) -> dict:
    current = current or {}
    raw = row_fields(card, model_name)
    raw.update({"Layer": str(card.get("layer") or ""),
                "Topic": str(card.get("topic") or ""), "Media": ""})
    out = {}
    for name, value in raw.items():
        out[name] = field_html(
            value, current.get(name, ""), back=name in ("Back", "Extra"),
            source=str(card.get("source") or ""),
            source_url=str(card.get("source_url") or ""))
    return out


def _tag(value) -> str:
    return str(value).strip().lower().replace(" ", "_").replace("&", "and")


def _tags(card: dict) -> list[str]:
    objects = card.get("objects") or []
    if isinstance(objects, str):
        objects = [objects]
    return list(dict.fromkeys(tag for tag in
                              (_tag(v) for v in [card.get("topic"), *objects])
                              if tag))


def plan(ac, deck: str, cards_path, maps: list[str] | None = None) -> dict:
    context = dc.load(deck)
    if not context:
        raise PlanError("no dossier for this deck; run attach --reconstruct first")
    deck_name = live_deck_name(ac, context, deck)
    notes = snapshot_notes(ac, deck_name)
    note_by_id = {int(n["noteId"]): n for n in notes}

    states = [s for s in (context.get("state") or []) if s.get("anki_note_id")]
    state_by_rev = state_index(states)
    rev_by_note = {int(s["anki_note_id"]): str(s.get("rev_id") or "")
                   for s in states}
    cards_by_rev = {str(c.get("rev_id")): c
                    for c in (context.get("cards") or []) if c.get("rev_id")}

    by_hash: dict[str, list[str]] = {}
    by_key: dict[tuple[str, str], list[str]] = {}
    for rev, card in cards_by_rev.items():
        digest = str(card.get("content_hash") or "")
        if digest:
            by_hash.setdefault(digest, []).append(rev)
        by_key.setdefault(card_key(card), []).append(rev)

    new_cards = load_cards(cards_path)
    if not isinstance(new_cards, list) or not new_cards:
        raise PlanError("cards file must contain a non-empty list")
    if not all(isinstance(card, dict) for card in new_cards):
        raise PlanError("every card in the file must be an object")
    mapped = parse_maps(maps)
    for index in mapped:
        if index > len(new_cards):
            raise PlanError(f"--map index {index} is outside cards file")
        if mapped[index] not in cards_by_rev:
            raise PlanError(f"--map rev {mapped[index]!r} is not in the dossier")

    actions, matched_notes = [], set()
    counts = {"update": 0, "add": 0, "keep": 0}
    for index, card in enumerate(new_cards, 1):
        rev = str(card.get("rev_id") or "").strip()
        if index in mapped:
            rev = mapped[index]
        elif rev and rev not in cards_by_rev:
            raise PlanError(f"unknown rev_id {rev!r} on card {index}; omit it "
                            "for a new card")
        if not rev:
            digest = card_hash(card)
            candidates = by_hash.get(digest) or []
            if len(candidates) > 1:
                raise PlanError(f"card {index} matches several dossier cards: "
                                + ", ".join(candidates) + "; use --map")
            if candidates:
                rev = candidates[0]
            else:
                key = card_key(card)
                candidates = by_key.get(key) or []
                if len(candidates) > 1:
                    raise PlanError(f"card {index} matches several dossier cards: "
                                    + ", ".join(candidates) + "; use --map")
                if candidates:
                    rev = candidates[0]

        if rev:
            state = state_by_rev.get(rev) or {}
            nid = state.get("anki_note_id")
            note = note_by_id.get(int(nid)) if nid is not None else None
            if not note:
                raise PlanError(f"card {index} maps to {rev}, but its live note "
                                "is gone; re-attach or use --map")
            if int(nid) in matched_notes:
                raise PlanError(f"two new cards map to the same live note {nid}")
            matched_notes.add(int(nid))
            current = fields(note)
            after = _rendered(card, current, model(note))
            if any(current.get(k, "") != v for k, v in after.items()):
                actions.append({
                    "kind": "update_fields", "note_id": int(nid), "rev_id": rev,
                    "before": base_fields(card, state, note), "after": after,
                })
                counts["update"] += 1
            else:
                counts["keep"] += 1
            continue

        model_name = _notetype(context, bool(card.get("cloze")))
        after = _rendered(card, {}, model_name)
        actions.append({
            "kind": "add", "model": model_name, "fields": after,
            "tags": _tags(card), "card": card,
        })
        counts["add"] += 1

    unmatched = [nid for nid, rev in rev_by_note.items()
                 if nid in note_by_id and nid not in matched_notes]
    groups = []
    if unmatched:
        groups.append({"id": "retire-1", "note_ids": sorted(unmatched),
                       "reason": "live notes absent from the new card set"})

    stamp = now().replace(":", "").replace("-", "").replace("+", "")
    path = dc.revision_dir(context["uuid"], stamp) / "sync_plan.json"
    data = {
        "schema": 1, "kind": "sync", "cards_json": str(cards_path),
        "deck_key": context["uuid"], "deck_name": deck_name,
        "generated_at": now(), "actions": actions,
        "destructive_groups": groups, "conflicts": [],
        "counts": counts,
    }
    write_json(path, data)
    return {"plan": str(path), "counts": counts, "actions": len(actions),
            "retire": len(unmatched), "deck": deck_name}
