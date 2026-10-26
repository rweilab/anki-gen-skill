"""Shared revision helpers: note shape, snapshots, conflicts, scheduling."""
from __future__ import annotations

import re
from collections import defaultdict

import deck_context as dc
import render
from anki_connect import AnkiConnect, AnkiConnectError
from dossier.model import card_key, plain_text, state_index

PLAN_SCHEMA = 1
SCHEDULE_KEYS = ("cardId", "due", "interval", "ivl", "factor", "reps",
                 "lapses", "queue", "type", "left")
LAYER_RANK = {"Procedure": 4, "L3": 3, "L2": 2, "L1": 1}


class PlanError(ValueError):
    pass


def client(url: str | None) -> AnkiConnect:
    ac = AnkiConnect(url=url)
    ac.ensure_available()
    ac.ensure_compatible()
    return ac


def deck_query(name: str) -> str:
    return f'deck:"{str(name).replace(chr(34), "")}"'


def fields(note: dict) -> dict[str, str]:
    out = {}
    for name, value in (note.get("fields") or {}).items():
        out[name] = str(value.get("value", "") if isinstance(value, dict) else value)
    return out


def model(note: dict) -> str:
    return str(note.get("modelName") or "")


def is_cloze(model_name: str, row: dict | None = None) -> bool:
    return "cloze" in str(model_name).lower() or bool((row or {}).get("cloze"))


def front_back(note: dict) -> tuple[str, str]:
    f = fields(note)
    if is_cloze(model(note)):
        return f.get("Text", ""), f.get("Extra", "")
    return f.get("Front", ""), f.get("Back", "")


def note_key(note: dict) -> tuple[str, str]:
    front, back = front_back(note)
    return plain_text(front), plain_text(back)


def row_fields(row: dict, model_name: str = "") -> dict[str, str]:
    if is_cloze(model_name, row):
        return {"Text": str(row.get("front", "")),
                "Extra": str(row.get("back", ""))}
    return {"Front": str(row.get("front", "")),
            "Back": str(row.get("back", ""))}


def note_ids(note: dict) -> list[int]:
    return [int(i) for i in (note.get("cards") or [])]


def strip_footer(value: str) -> str:
    return re.sub(r'<div[^>]*class="src"[^>]*>.*?</div>', "", str(value or ""),
                  flags=re.S | re.I).strip()


def footer(value: str) -> str:
    m = re.search(r'<div[^>]*class="src"[^>]*>.*?</div>', str(value or ""),
                  flags=re.S | re.I)
    return m.group(0) if m else ""


def field_html(value: str, current: str = "", *, back: bool = False,
               source: str = "", source_url: str = "") -> str:
    text = str(value or "")
    html = text if re.search(r"<[a-zA-Z][^>]*>", text) else render.to_html(text)
    if not back:
        return html
    if footer(html):
        return html
    existing = footer(current)
    if existing:
        return html + existing
    return render.with_source(html, source, source_url)


def label(row: dict, limit: int = 74) -> str:
    front = re.sub(r"\s+", " ", str(row.get("front") or ""))
    front = re.sub(r"<[^>]+>", "", front)
    if len(front) > limit:
        front = front[:limit - 1] + "…"
    return f'{row.get("layer") or "?"} · {row.get("topic") or "?"} · "{front}"'


def states_by_rev(context: dict) -> dict[str, dict]:
    return state_index(context.get("state") or [])


def base_fields(row: dict, state: dict, note: dict | None) -> dict[str, str]:
    base = (state or {}).get("anki_fields_base") or {}
    if base:
        return {k: str(v) for k, v in base.items()}
    if note:
        return fields(note)
    return row_fields(row)


def set_base(state: dict, note: dict) -> None:
    state["anki_fields_base"] = fields(note)
    state["last_seen"] = dc.now()


def schedule(ac: AnkiConnect, notes: list[dict]) -> tuple[dict, dict, dict]:
    card_ids = [cid for n in notes for cid in note_ids(n)]
    cards = [c for c in ac.cards_info(card_ids)
             if isinstance(c, dict) and c.get("cardId") is not None]
    card_map = {int(c["cardId"]): c for c in cards}
    reviews = ac.get_reviews_of_cards(card_ids) if card_ids else {}
    fp = {"cards": [{k: c.get(k) for k in SCHEDULE_KEYS if k in c} for c in cards],
          "revlog_count": sum(len(v or []) for v in (reviews or {}).values())}
    return fp, card_map, reviews


def fp_for_note(note: dict, card_map: dict, reviews: dict) -> dict:
    cards = [card_map[c] for c in note_ids(note) if c in card_map]
    return {
        "cards": [{k: c.get(k) for k in SCHEDULE_KEYS if k in c} for c in cards],
        "revlog_count": sum(
            len((reviews or {}).get(str(c.get("cardId")))
                or (reviews or {}).get(c.get("cardId")) or [])
            for c in cards),
    }


def schedule_unchanged(before: dict, after: dict) -> bool:
    a = {int(c["cardId"]): c for c in before.get("cards", []) if "cardId" in c}
    b = {int(c["cardId"]): c for c in after.get("cards", []) if "cardId" in c}
    if set(a) != set(b):
        return False
    for cid, old in a.items():
        for key in SCHEDULE_KEYS:
            if key in old and old.get(key) != b[cid].get(key):
                return False
    return True


def snapshot_notes(ac: AnkiConnect, deck_name: str) -> list[dict]:
    ids = ac.find_notes(deck_query(deck_name))
    return [n for n in ac.notes_info(ids)
            if isinstance(n, dict) and n.get("noteId")]


def find_ctx(ac: AnkiConnect, selector: str | None) -> dict | None:
    key = dc.resolve(selector)
    if key:
        return dc.load(key)
    if not selector:
        return None
    try:
        deck_id = ac.deck_names_and_ids().get(selector)
    except AnkiConnectError:
        deck_id = None
    if deck_id is not None:
        key = dc.find_by_deck_id(str(deck_id))
        if key:
            return dc.load(key)
    return None


def live_deck_name(ac: AnkiConnect, context: dict | None,
                   selector: str | None = None) -> str:
    try:
        decks = ac.deck_names_and_ids()
    except AnkiConnectError:
        decks = {}
    if selector in decks:
        return str(selector)
    deck = (context or {}).get("manifest", {}).get("deck", {})
    deck_id = str(deck.get("anki_deck_id") or "")
    if deck_id:
        for name, value in decks.items():
            if str(value) == deck_id:
                return str(name)
    return str(deck.get("name") or selector or "")


def base_conflicts(note: dict, base: dict) -> list[dict]:
    current = fields(note)
    out = []
    for name, value in base.items():
        if plain_text(current.get(name, "")) != plain_text(value):
            out.append({"field": name, "base": value,
                        "current": current.get(name, "")})
    return out


def proposed_conflicts(note: dict, base: dict, proposed: dict) -> list[dict]:
    current = fields(note)
    out = []
    for name, value in proposed.items():
        if plain_text(current.get(name, "")) != plain_text(base.get(name, "")):
            out.append({"field": name, "base": base.get(name, ""),
                        "current": current.get(name, ""), "proposed": value})
    return out


def group_rows(rows: list[dict], assigned: dict[int, int]):
    out = defaultdict(list)
    for i, row in enumerate(rows):
        if i in assigned:
            continue
        out[card_key(row)].append((i, row))
    return out
