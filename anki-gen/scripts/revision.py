#!/usr/bin/env python3
"""Attach, audit, and revise an already-imported Anki deck.

The user interface is plaintext intent, never note IDs. This script reads the
deck dossier plus a live AnkiConnect snapshot, resolves cards by topic, front
text, tags, review score, leech state, or card family, writes a human and a
machine plan, and waits for approval before destructive work.

Live operations use AnkiConnect only. A new `.apkg` still builds offline; this
module never falls back to SQLite, the `anki` library, or MCP.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deck_context as dc  # noqa: E402
import render  # noqa: E402
from anki_connect import AnkiConnect, AnkiConnectError  # noqa: E402
from cardid import card_hash  # noqa: E402

PLAN_SCHEMA = 1
SCHEDULE_KEYS = ("cardId", "due", "interval", "ivl", "factor", "reps",
                 "lapses", "queue", "type", "left")
LAYER_RANK = {"Procedure": 4, "L3": 3, "L2": 2, "L1": 1}


class PlanError(ValueError):
    pass


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _client(url: str | None) -> AnkiConnect:
    ac = AnkiConnect(url=url)
    ac.ensure_available()
    return ac


def _deck_query(name: str) -> str:
    return f'deck:"{str(name).replace(chr(34), "")}"'


def _fields(note: dict) -> dict[str, str]:
    out = {}
    for name, value in (note.get("fields") or {}).items():
        out[name] = str(value.get("value", "") if isinstance(value, dict) else value)
    return out


def _model(note: dict) -> str:
    return str(note.get("modelName") or "")


def _is_cloze(model: str, row: dict | None = None) -> bool:
    return "cloze" in str(model).lower() or bool((row or {}).get("cloze"))


def _front_back(note: dict) -> tuple[str, str]:
    f = _fields(note)
    if _is_cloze(_model(note)):
        return f.get("Text", ""), f.get("Extra", "")
    return f.get("Front", ""), f.get("Back", "")


def _note_key(note: dict) -> tuple[str, str]:
    front, back = _front_back(note)
    return dc.plain_text(front), dc.plain_text(back)


def _row_fields(row: dict, model: str = "") -> dict[str, str]:
    if _is_cloze(model, row):
        return {"Text": str(row.get("front", "")), "Extra": str(row.get("back", ""))}
    return {"Front": str(row.get("front", "")), "Back": str(row.get("back", ""))}


def _note_ids(note: dict) -> list[int]:
    return [int(i) for i in (note.get("cards") or [])]


def _strip_footer(value: str) -> str:
    return re.sub(r'<div[^>]*class="src"[^>]*>.*?</div>', "", str(value or ""),
                  flags=re.S | re.I).strip()


def _footer(value: str) -> str:
    m = re.search(r'<div[^>]*class="src"[^>]*>.*?</div>', str(value or ""),
                  flags=re.S | re.I)
    return m.group(0) if m else ""


def _field_html(value: str, current: str = "", *, back: bool = False,
                source: str = "", source_url: str = "") -> str:
    """Render authoring text once; keep an existing source footer intact."""
    text = str(value or "")
    html_value = text if re.search(r"<[a-zA-Z][^>]*>", text) else render.to_html(text)
    if not back:
        return html_value
    footer = _footer(current)
    if footer:
        return html_value + footer
    return render.with_source(html_value, source, source_url)


def _fp_for_note(note: dict, card_map: dict, reviews: dict) -> dict:
    cards = [card_map[c] for c in _note_ids(note) if c in card_map]
    return {
        "cards": [{k: c.get(k) for k in SCHEDULE_KEYS if k in c} for c in cards],
        "revlog_count": sum(
            len((reviews or {}).get(str(c.get("cardId")))
                or (reviews or {}).get(c.get("cardId")) or [])
            for c in cards),
    }


def _label(row: dict, limit: int = 74) -> str:
    front = re.sub(r"\s+", " ", str(row.get("front") or ""))
    front = re.sub(r"<[^>]+>", "", front)
    if len(front) > limit:
        front = front[:limit - 1] + "…"
    return f'{row.get("layer") or "?"} · {row.get("topic") or "?"} · "{front}"'


def _row_by_note(rows: list[dict]) -> dict[int, dict]:
    out = {}
    for row in rows:
        try:
            out[int(row["anki_note_id"])] = row
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _snapshot(ac: AnkiConnect, deck_name: str) -> list[dict]:
    ids = ac.find_notes(_deck_query(deck_name))
    notes = [n for n in ac.notes_info(ids) if isinstance(n, dict) and n.get("noteId")]
    return notes


def _all_card_ids(notes: list[dict]) -> list[int]:
    return [cid for n in notes for cid in _note_ids(n)]


def _schedule(ac: AnkiConnect, notes: list[dict]) -> tuple[dict, dict, dict]:
    card_ids = _all_card_ids(notes)
    cards = [c for c in ac.cards_info(card_ids)
             if isinstance(c, dict) and c.get("cardId") is not None]
    card_map = {int(c["cardId"]): c for c in cards}
    reviews = ac.get_reviews_of_cards(card_ids) if card_ids else {}
    fp = {
        "cards": [{k: c.get(k) for k in SCHEDULE_KEYS if k in c} for c in cards],
        "revlog_count": sum(len(v or []) for v in (reviews or {}).values()),
    }
    return fp, card_map, reviews


def _client_version(ac: AnkiConnect) -> dict:
    return ac.deck_names_and_ids()


def _find_ctx(ac: AnkiConnect, selector: str | None) -> dict | None:
    key = dc.resolve(selector)
    if key:
        return dc.load(key)
    if not selector:
        return None
    try:
        deck_id = _client_version(ac).get(selector)
    except AnkiConnectError:
        deck_id = None
    if deck_id is not None:
        key = dc.find_by_deck_id(str(deck_id))
        if key:
            return dc.load(key)
    return None


def _live_deck_name(ac: AnkiConnect, ctx: dict | None,
                    selector: str | None = None) -> str:
    """Prefer the live name when a deck was renamed but its ID is unchanged."""
    try:
        decks = ac.deck_names_and_ids()
    except AnkiConnectError:
        decks = {}
    if selector in decks:
        return str(selector)
    manifest = (ctx or {}).get("manifest", {}).get("anki", {})
    deck_id = str(manifest.get("deck_id") or "")
    if deck_id:
        for name, value in decks.items():
            if str(value) == deck_id:
                return str(name)
    return str(manifest.get("deck_name") or selector or "")


def _identity(ac: AnkiConnect, deck_name: str) -> dict:
    try:
        deck_id = _client_version(ac).get(deck_name, "")
    except AnkiConnectError:
        deck_id = ""
    return {"deck_name": deck_name, "deck_id": str(deck_id), "profile": ""}


def _reconstructed_rows(ac: AnkiConnect, notes: list[dict],
                        deck_name: str) -> list[dict]:
    rows = []
    for note in notes:
        f = _fields(note)
        front, back = _front_back(note)
        model = _model(note)
        tags = list(note.get("tags") or [])
        topic = (tags[0].replace("_", " ") if tags else "Imported")
        layer = f.get("Layer", "")
        source = ""
        m = re.search(r'<div[^>]*class="src"[^>]*>(.*?)</div>', back, re.S | re.I)
        if m:
            source = re.sub(r"<[^>]+>", " ", m.group(1))
            source = re.sub(r"\s+", " ", source).strip()
        row = {
            "rev_id": str(uuid.uuid4()),
            "anki_note_id": int(note["noteId"]),
            "guid": "",
            "front": _strip_footer(front),
            "back": _strip_footer(back),
            "layer": layer, "topic": topic, "deck": deck_name,
            "objects": tags[1:], "tier_zero": False,
            "cloze": _is_cloze(model), "stratum": "",
            "retrieval_target": "", "why": "",
            "source": source, "source_url": "", "media": [],
            "content_hash": card_hash({"front": _strip_footer(front),
                                       "back": _strip_footer(back)}),
            "scheduling_fingerprint": None, "state": "live",
            "confidence": "reconstructed",
        }
        rows.append(row)
    return rows


def _write_attach_log(key: str, stamp: str, payload: dict) -> Path:
    path = dc.revision_dir(key, stamp) / "attach.json"
    dc.write_json(path, payload)
    return path


def _attach(ac: AnkiConnect, ctx: dict, deck_name: str, *,
            maps: dict[str, int] | None = None) -> dict:
    notes = _snapshot(ac, deck_name)
    rows = ctx["cards"]
    note_by_id = {int(n["noteId"]): n for n in notes}
    by_key: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for note in notes:
        by_key[_note_key(note)].append(note)

    assigned: dict[int, int] = {}       # row index -> note id
    claimed: set[int] = set()

    # Explicit internal mappings first.
    for rev, nid in (maps or {}).items():
        idx = next((i for i, r in enumerate(rows) if r.get("rev_id") == rev), None)
        if idx is None:
            raise PlanError(f"--map refers to an unknown rev_id: {rev}")
        if int(nid) not in note_by_id:
            raise PlanError(f"--map note id is not in this deck: {nid}")
        if int(nid) in claimed:
            raise PlanError(f"--map note id is already assigned: {nid}")
        assigned[idx] = int(nid)
        claimed.add(int(nid))

    # Existing note IDs are the strongest identity after attach.
    for idx, row in enumerate(rows):
        if idx in assigned or row.get("state") in ("deleted", "stale"):
            continue
        try:
            nid = int(row.get("anki_note_id"))
        except (TypeError, ValueError):
            continue
        if nid in note_by_id:
            assigned[idx] = nid
            claimed.add(nid)

    ambiguous, matched = [], []
    for key, indices in _group_rows(rows, assigned).items():
        candidates = [n for n in by_key.get(key, [])
                      if int(n["noteId"]) not in claimed]
        if len(indices) == 1 and len(candidates) == 1:
            idx, row = indices[0]
            assigned[idx] = int(candidates[0]["noteId"])
            claimed.add(int(candidates[0]["noteId"]))
            matched.append(row)
        elif not candidates:
            continue
        elif len(indices) > 1 or len(candidates) > 1:
            ambiguous.append({
                "rev_ids": [r.get("rev_id") for _, r in indices],
                "cards": [_label(r) for _, r in indices],
                "notes": [{"note_id": int(n["noteId"]),
                           "front": _label({"front": _front_back(n)[0],
                                            "topic": _current_topic(n),
                                            "layer": _fields(n).get("Layer", "")})}
                          for n in candidates],
            })

    if ambiguous:
        return {"status": "ambiguous", "ambiguous": ambiguous,
                "matched": len(assigned), "notes": len(notes)}

    fp, card_map, reviews = _schedule(ac, notes)
    drift = []
    for idx, nid in assigned.items():
        row = rows[idx]
        note = note_by_id[nid]
        live_key = _note_key(note)
        if live_key != dc.card_key(row):
            drift.append({"rev_id": row.get("rev_id"), "note_id": nid,
                          "base": _label(row),
                          "live_front": _front_back(note)[0][:120]})
        row["anki_note_id"] = nid
        row["state"] = "live"
        my_cards = [card_map[c] for c in _note_ids(note) if c in card_map]
        row["scheduling_fingerprint"] = {
            "cards": [{k: c.get(k) for k in SCHEDULE_KEYS if k in c}
                      for c in my_cards],
            "revlog_count": sum(len((reviews or {}).get(str(c.get("cardId")), [])
                                   or (reviews or {}).get(c.get("cardId"), []))
                                for c in my_cards),
        }
    unassigned_rows = [r for i, r in enumerate(rows)
                       if i not in assigned and r.get("state") not in
                       ("deleted", "stale")]
    unmatched_notes = [n for n in notes if int(n["noteId"]) not in claimed]
    registry = _identity(ac, deck_name)
    registry["notetypes"] = sorted({_model(n) for n in notes if _model(n)}) or None
    dc.write_cards(ctx["key"], rows)
    dc.update_manifest(ctx["key"], last_attach=dc.now(),
                       anki={"deck_name": deck_name,
                             "deck_id": registry["deck_id"],
                             "notetypes": registry["notetypes"] or []})
    dc.register(dc.identity({"deck_name": deck_name,
                             "deck_id": registry["deck_id"],
                             "profile": registry["profile"],
                             "notetypes": registry["notetypes"] or
                             ["3-Layer STEM", "3-Layer STEM Cloze"]}),
                ctx["key"])
    stamp = _stamp()
    _write_attach_log(ctx["key"], stamp, {
        "schema": 1, "attached_at": dc.now(), "deck": deck_name,
        "matched": len(assigned), "live_notes": len(notes),
        "unmatched_rows": [r.get("rev_id") for r in unassigned_rows],
        "unmatched_notes": [int(n["noteId"]) for n in unmatched_notes],
        "field_drift": drift,
    })
    return {"status": "ok", "key": ctx["key"], "matched": len(assigned),
            "live_notes": len(notes), "unmatched_rows": len(unassigned_rows),
            "unmatched_notes": len(unmatched_notes), "field_drift": drift,
            "notes": len(notes)}


def _group_rows(rows: list[dict], assigned: dict[int, int]):
    out: dict[tuple[str, str], list[tuple[int, dict]]] = defaultdict(list)
    for idx, row in enumerate(rows):
        if idx in assigned or row.get("state") in ("deleted", "stale"):
            continue
        out[dc.card_key(row)].append((idx, row))
    return out


def _current_topic(note: dict) -> str:
    tags = note.get("tags") or []
    return tags[0].replace("_", " ") if tags else "Imported"


def attach_key(key: str, url: str | None = None,
               maps: dict[str, int] | None = None) -> dict:
    ac = _client(url)
    ctx = dc.load(key)
    deck_name = ctx["manifest"].get("anki", {}).get("deck_name")
    if not deck_name:
        raise PlanError("dossier has no deck name; run attach with --deck")
    return _attach(ac, ctx, deck_name, maps=maps)


def cmd_attach(args) -> int:
    ac = _client(args.url)
    if not args.deck:
        print("revision.py: pass --deck <name-or-key>", file=sys.stderr)
        return 2
    ctx = _find_ctx(ac, args.deck)
    notes = _snapshot(ac, args.deck) if ctx is None else None
    if ctx is None:
        if not args.reconstruct:
            print("revision.py: no dossier for this deck. Re-run with "
                  "--reconstruct to build a read-only record from Anki fields/tags.",
                  file=sys.stderr)
            return 2
        deck_name = args.deck
        ident = _identity(ac, deck_name)
        notes = notes if notes is not None else _snapshot(ac, deck_name)
        rows = _reconstructed_rows(ac, notes, deck_name)
        saved = dc.save(ident, rows, sources=[], media=[],
                        confidence="reconstructed",
                        artifacts={
                            "intake.md": "# Intake\n\n- Reconstructed from AnkiConnect; "
                                         "the original intake is unavailable.\n",
                            "scope_gate.md": "# Scope gate\n\n- Reconstructed; no "
                                           "authored scope gate is available.\n",
                            "authoring_ledger.md": "# Authoring ledger\n\n- "
                                                 "Reconstructed; no authored ledger is available.\n"})
        ctx = dc.load(saved["key"])
    maps = {}
    for item in args.map or []:
        if "=" not in item:
            print("revision.py: --map wants REV_ID=NOTE_ID", file=sys.stderr)
            return 2
        rev, nid = item.split("=", 1)
        maps[rev.strip()] = int(nid)
    deck_name = _live_deck_name(ac, ctx, args.deck)
    try:
        result = _attach(ac, ctx, deck_name, maps=maps)
    except PlanError as e:
        print(f"revision.py: {e}", file=sys.stderr)
        return 2
    if result["status"] == "ambiguous":
        print("revision.py: attach is ambiguous; nothing was written.", file=sys.stderr)
        for item in result["ambiguous"]:
            print(f"  dossier: {', '.join(item['cards'])}", file=sys.stderr)
            print(f"  notes:   {', '.join(n['front'] for n in item['notes'])}",
                  file=sys.stderr)
        print("  resolve with --map <rev_id>=<note_id>", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"attached   {result['matched']} note(s) to dossier {result['key']}")
        if result["unmatched_rows"] or result["unmatched_notes"]:
            print(f"           {result['unmatched_rows']} dossier card(s) and "
                  f"{result['unmatched_notes']} live note(s) remain unmatched")
        if result["field_drift"]:
            print(f"           {len(result['field_drift'])} note(s) differ from the "
                  "dossier (manual Anki edits are preserved)")
    return 0


def cmd_audit(args) -> int:
    ac = _client(args.url)
    if not args.deck:
        print("revision.py: pass --deck <name-or-key>", file=sys.stderr)
        return 2
    ctx = _find_ctx(ac, args.deck)
    deck_name = _live_deck_name(ac, ctx, args.deck)
    notes = _snapshot(ac, deck_name)
    rows = ctx["cards"] if ctx else _reconstructed_rows(ac, notes, deck_name)
    if ctx is None:
        print("audit      no dossier found; reconstructed read-only view "
              "(confidence: reconstructed)", file=sys.stderr)
    by_id = _row_by_note(rows)
    live_ids = {int(n["noteId"]) for n in notes}
    matched = [r for r in rows if int(r.get("anki_note_id") or 0) in live_ids]
    missing = [r for r in rows if r.get("state", "live") == "live"
               and int(r.get("anki_note_id") or 0) not in live_ids]
    matched_ids = {int(r["anki_note_id"]) for r in matched}
    unmatched = [n for n in notes if int(n["noteId"]) not in matched_ids]
    drift = []
    for note in notes:
        row = by_id.get(int(note["noteId"]))
        if row and _note_key(note) != dc.card_key(row):
            drift.append({"rev_id": row.get("rev_id"), "note_id": int(note["noteId"]),
                          "topic": row.get("topic"), "front": _label(row)})
    topics: dict[str, int] = defaultdict(int)
    for row in matched:
        topics[str(row.get("topic") or "?")] += 1
    fp, card_map, _ = _schedule(ac, notes)
    warnings = dc.validate(deck_key_or_selector=ctx["key"])["warnings"] if ctx else []
    report = {
        "schema": 1, "audit_at": dc.now(), "deck": deck_name,
        "dossier": ctx["key"] if ctx else None,
        "confidence": (ctx["manifest"].get("confidence") if ctx else "reconstructed"),
        "live_notes": len(notes), "live_cards": len(card_map),
        "dossier_cards": len(rows), "matched": len(matched),
        "missing_live": [r.get("rev_id") for r in missing],
        "unmatched_live": [int(n["noteId"]) for n in unmatched],
        "field_drift": drift, "topics": dict(sorted(topics.items())),
        "scheduling": fp, "context_warnings": len(warnings),
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"audit      {report['live_notes']} live note(s), "
              f"{report['matched']}/{report['dossier_cards']} dossier card(s) matched")
        print(f"           {len(missing)} missing live · {len(unmatched)} live "
              f"not in dossier · {len(drift)} manual edit(s)")
        print(f"           {report['live_cards']} card(s), "
              f"{fp['revlog_count']} review row(s), confidence "
              f"{report['confidence']}")
    return 0


# ------------------------------------------------------------------ planning

def _parse_update(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise PlanError("--update-front/--update-back want OLD=NEW")
    old, new = value.split("=", 1)
    if not old:
        raise PlanError("--update-* needs a non-empty old value")
    return old, new


def _find_one(rows: list[dict], text: str, field: str = "front") -> dict:
    needle = text.casefold()
    matches = [r for r in rows
               if r.get("state", "live") == "live"
               and needle in str(r.get(field) or "").casefold()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise PlanError(f"no live card has {field} containing {text!r}")
    raise PlanError(f"{len(matches)} live cards contain {text!r}; use a longer "
                    f"phrase: " + "; ".join(_label(r, 50) for r in matches[:5]))


def _select(rows: list[dict], args, intent: dict, note_by_id: dict,
            card_map: dict) -> list[dict]:
    out = []
    for row in rows:
        if row.get("state", "live") != "live":
            continue
        if args.topic and str(row.get("topic")) not in args.topic:
            continue
        if args.front and args.front.casefold() not in str(row.get("front", "")).casefold():
            continue
        if args.tag:
            tags = {str(row.get("topic", "")).casefold()} | {
                str(o).casefold() for o in row.get("objects") or []}
            if not any(t.casefold() in tags for t in args.tag):
                continue
        if args.layer and str(row.get("layer")) not in args.layer:
            continue
        if args.stratum and str(row.get("stratum")) not in args.stratum:
            continue
        score = args.score if args.score is not None else intent.get("score")
        if score is not None and row.get("review_score") != score:
            continue
        if args.leech or intent.get("leech"):
            nid = int(row.get("anki_note_id") or 0)
            note = note_by_id.get(nid)
            lapses = max((card_map.get(c, {}).get("lapses", 0)
                          for c in _note_ids(note or {})), default=0)
            if lapses < 4:
                continue
        out.append(row)
    return out


def _base_conflicts(note: dict, base: dict) -> list[dict]:
    current = _fields(note)
    out = []
    for field, value in base.items():
        if dc.plain_text(current.get(field, "")) != dc.plain_text(value):
            out.append({"field": field, "base": value,
                        "current": current.get(field, "")})
    return out


def _proposed_conflicts(note: dict, base: dict,
                        proposed: dict) -> list[dict]:
    current = _fields(note)
    out = []
    for field, value in proposed.items():
        if dc.plain_text(current.get(field, "")) != dc.plain_text(base.get(field, "")):
            out.append({"field": field, "base": base.get(field, ""),
                        "current": current.get(field, ""), "proposed": value})
    return out


def _merge_group(rows: list[dict], victims: list[dict], topic: str,
                 n: int) -> tuple[dict, list[dict]]:
    pool = [r for r in rows if r.get("topic") == topic
            and r.get("state", "live") == "live"
            and r.get("rev_id") not in {v.get("rev_id") for v in victims}]
    if not pool:
        return {}, []
    survivor = max(pool, key=lambda r: (LAYER_RANK.get(str(r.get("layer")), 0),
                                        len(str(r.get("back") or ""))))
    gid = f"merge-{n}"
    actions = []
    for victim in victims:
        actions.append({
            "kind": "merge", "note_id": survivor.get("anki_note_id"),
            "rev_id": survivor.get("rev_id"),
            "victim_note_id": victim.get("anki_note_id"),
            "victim_rev_id": victim.get("rev_id"),
            "before": _row_fields(victim, "Cloze" if victim.get("cloze") else ""),
            "after": {}, "group": gid, "risk": "high",
            "reason": f"fold into the {survivor.get('layer')} card on {topic}",
            "topic": victim.get("topic"), "layer": victim.get("layer"),
            "front": victim.get("front"), "survivor_label": _label(survivor),
        })
    group = {"id": gid, "kind": "merge", "reason": f"merge the easiest {topic} cards",
             "choices": ["delete", "suspend", "keep"],
             "note_ids": [v.get("anki_note_id") for v in victims],
             "cards": [{"rev_id": v.get("rev_id"), "label": _label(v)}
                       for v in victims],
             "survivor": {"rev_id": survivor.get("rev_id"),
                          "label": _label(survivor)}}
    return group, actions


def _candidate_blob(row: dict) -> set[str]:
    text = " ".join(str(row.get(k) or "") for k in ("topic", "front", "source"))
    return {w for w in re.findall(r"[a-z0-9]{3,}", text.casefold())
            if w not in {"the", "and", "for", "with", "what", "why", "how"}}


def _media_actions(rows: list[dict], media: list[dict], note_by_id: dict) -> list[dict]:
    unused = [m for m in media if not m.get("used")]
    actions, taken = [], set()
    for row in rows:
        if row.get("state", "live") != "live" or row.get("media"):
            continue
        nid = int(row.get("anki_note_id") or 0)
        note = note_by_id.get(nid)
        if not note:
            continue
        words = _candidate_blob(row)
        ranked = []
        for cand in unused:
            if cand.get("file") in taken:
                continue
            cwords = _candidate_blob(cand)
            score = len(words & cwords) * 2
            if cand.get("source") and cand["source"] in str(row.get("source", "")):
                score += 6
            if cand.get("quality") == "high":
                score += 2
            if score:
                ranked.append((score, cand))
        if not ranked:
            continue
        ranked.sort(key=lambda t: t[0], reverse=True)
        cand = ranked[0][1]
        taken.add(cand.get("file"))
        field = "Extra" if row.get("cloze") else "Back"
        filename = f"anki-gen-{str(cand.get('sha256') or hashlib.sha1(str(cand['file']).encode()).hexdigest())[:12]}" \
                   f"{Path(cand.get('preview') or cand.get('file') or 'image.png').suffix or '.png'}"
        snippet = f'<img src="{filename}">'
        actions.append({
            "kind": "attach_media", "note_id": nid, "rev_id": row.get("rev_id"),
            "before": _row_fields(row, _model(note)), "after": {},
            "snippet": snippet, "field": field, "media_filename": filename,
            "candidate": cand, "low_res": not cand.get("original_path"),
            "risk": "low", "front": row.get("front"),
            "topic": row.get("topic"), "layer": row.get("layer"),
            "reason": f"use unused {cand.get('kind')} from {cand.get('source') or 'source'}",
        })
    return actions


def _plan_doc(deck_key: str, deck_name: str, intent_text: str,
              actions: list[dict], groups: list[dict], conflicts: list[dict]) -> dict:
    return {
        "schema": PLAN_SCHEMA, "deck_key": deck_key, "deck_name": deck_name,
        "intent": intent_text, "created_at": dc.now(), "conflicts": conflicts,
        "actions": actions, "destructive_groups": groups,
        "counts": {
            "updated": sum(1 for a in actions if a["kind"] in
                           ("update_fields", "attach_media") or
                           (a["kind"] == "merge" and a.get("after"))),
            "added": sum(len(a.get("new") or []) for a in actions
                         if a["kind"] == "split"),
            "destructive": sum(len(g.get("note_ids") or []) for g in groups),
        },
    }


def _render_plan(plan: dict) -> str:
    lines = [f"# Revision plan — {plan['deck_name']}", "",
             f"Intent: {plan['intent']}", f"Created: {plan['created_at']}", "",
             "Cards are named by layer, topic, and front text. Note IDs are never "
             "part of the user interface.", ""]
    if not plan["actions"] and not plan["destructive_groups"]:
        lines += ["No changes proposed.", ""]
    if plan["actions"]:
        lines += ["## Proposed", ""]
        for n, a in enumerate(plan["actions"], 1):
            label = _label({"front": a.get("front") or
                            (a.get("before") or {}).get("Front") or
                            (a.get("before") or {}).get("Text", ""),
                            "topic": a.get("topic", ""),
                            "layer": a.get("layer", "")})
            if a["kind"] == "split":
                lines.append(f"{n}. **Split** {label} into "
                             f"{len(a.get('new') or [])} new card(s)")
                for new in a.get("new") or []:
                    lines.append(f"   - {new.get('front', '')[:100]}")
            elif a["kind"] == "merge":
                lines.append(f"{n}. **Merge** {label} into "
                             f"{a.get('survivor_label') or 'the survivor'} "
                             f"— group `{a.get('group')}`")
            elif a["kind"] == "attach_media":
                cand = a.get("candidate") or {}
                lines.append(f"{n}. **Attach media** to {label} — "
                             f"{cand.get('file')} — {a.get('reason', '')}")
                if a.get("low_res"):
                    lines.append("   - source file is gone; only a low-res preview "
                                 "exists (needs --allow-low-res)")
            else:
                lines.append(f"{n}. {label} — {a.get('reason', a['kind'])}")
                for field, value in (a.get("after") or {}).items():
                    old = str((a.get("before") or {}).get(field, ""))[:80]
                    new = str(value)[:80]
                    lines.append(f"   - {field}: {old!r} -> {new!r}")
            lines.append("")
    if plan["destructive_groups"]:
        lines += ["## Destructive groups — choose for each", ""]
        for g in plan["destructive_groups"]:
            lines += [f"### `{g['id']}` — {g.get('reason', g['kind'])}", ""]
            if g.get("survivor"):
                lines.append(f"Survivor: {g['survivor']['label']}")
            for card in g.get("cards", []):
                lines.append(f"- {card['label']}")
            lines += ["", "Choice: **Delete permanently / Suspend / Keep** "
                      "(no default; deletion removes review history).", ""]
    if plan["conflicts"]:
        lines += ["## Conflicts — manual Anki edits win by default", ""]
        for c in plan["conflicts"]:
            lines.append(f"- {c.get('label') or c.get('rev_id')}: "
                         f"{c.get('field') or 'card'} differs in Anki")
        lines.append("")
    if plan["destructive_groups"] or plan["actions"]:
        choices = " ".join(f"--choice {g['id']}=<delete|suspend|keep>"
                           for g in plan["destructive_groups"])
        lines += ["## Apply", "",
                  f"`python3 revision.py apply --plan <this plan> {choices}`".strip(),
                  ""]
    return "\n".join(lines)


def cmd_plan(args) -> int:
    ac = _client(args.url)
    if not args.deck or not args.intent:
        print("revision.py: plan needs --deck and --intent", file=sys.stderr)
        return 2
    ctx = _find_ctx(ac, args.deck)
    if ctx is None:
        print("revision.py: no dossier for this deck. Run "
              "`revision.py attach --deck \"NAME\" --reconstruct` first; "
              "revision cannot invent a ledger or why where none exists.",
              file=sys.stderr)
        return 2
    deck_name = _live_deck_name(ac, ctx, args.deck)
    notes = _snapshot(ac, deck_name)
    note_by_id = {int(n["noteId"]): n for n in notes}
    _, card_map, reviews = _schedule(ac, notes)
    rows = ctx["cards"]
    rows_by_id = _row_by_note(rows)
    intent_text = args.intent
    low = intent_text.casefold()
    scores = [int(x) for x in re.findall(r"\bscore\s+([1-5])\b", low)]
    intent = {
        "cull": any(w in low for w in ("cull", "trim", "easiest", "drop",
                                       "reduce")),
        "merge": any(w in low for w in ("merge", "fold")),
        "leech": "leech" in low,
        "visual": any(w in low for w in ("visual", "image", "diagram", "figure")),
        "preferred": ("suspend" if "suspend" in low else
                      "delete" if "delete" in low else ""),
        "score": scores[0] if scores else None,
    }
    selected = _select(rows, args, intent, note_by_id, card_map)
    if intent["cull"] and intent.get("score") is None and not (
            args.score is not None or args.topic or args.front or args.tag):
        selected = [r for r in selected if r.get("review_score") == 1]
    if args.allow_anchors is False:
        selected = [r for r in selected if not r.get("tier_zero")]

    selected = [r for r in selected if int(r.get("anki_note_id") or 0) in note_by_id]
    if (intent["cull"] or intent["merge"]) and not selected:
        print("revision.py: no live cards matched the intent; attach the deck, "
              "or name a topic/front/score.", file=sys.stderr)
        return 2

    actions: list[dict] = []
    groups: list[dict] = []
    conflicts: list[dict] = []
    group_n = 0

    # Explicit field updates: OLD=NEW, resolved by unique front/back substring.
    for value in args.update_front or []:
        old, new = _parse_update(value)
        row = _find_one(rows, old, "front")
        nid = int(row.get("anki_note_id") or 0)
        note = note_by_id.get(nid)
        if not note:
            print(f"revision.py: {_label(row)} is not attached; run attach first",
                  file=sys.stderr)
            return 2
        base = _row_fields(row, _model(note))
        after = {"Front" if "Front" in base else "Text":
                 str(row.get("front", "")).replace(old, new, 1)}
        for c in _proposed_conflicts(note, base, after):
            conflicts.append({"rev_id": row.get("rev_id"), "label": _label(row), **c})
        actions.append({"kind": "update_fields", "note_id": nid,
                        "rev_id": row.get("rev_id"), "before": base,
                        "after": after, "risk": "low",
                        "reason": "requested front rewrite",
                        "front": row.get("front"), "topic": row.get("topic"),
                        "layer": row.get("layer")})
    for value in args.update_back or []:
        old, new = _parse_update(value)
        row = _find_one(rows, old, "back")
        nid = int(row.get("anki_note_id") or 0)
        note = note_by_id.get(nid)
        if not note:
            print(f"revision.py: {_label(row)} is not attached; run attach first",
                  file=sys.stderr)
            return 2
        base = _row_fields(row, _model(note))
        after = {"Back" if "Back" in base else "Extra":
                 str(row.get("back", "")).replace(old, new, 1)}
        for c in _proposed_conflicts(note, base, after):
            conflicts.append({"rev_id": row.get("rev_id"), "label": _label(row), **c})
        actions.append({"kind": "update_fields", "note_id": nid,
                        "rev_id": row.get("rev_id"), "before": base,
                        "after": after, "risk": "low",
                        "reason": "requested back rewrite",
                        "front": row.get("front"), "topic": row.get("topic"),
                        "layer": row.get("layer")})

    # Explicit merge, then the bulk cull/fold path.
    if args.merge_match and args.into:
        victim = _find_one(rows, args.merge_match)
        survivor = _find_one(rows, args.into)
        group_n += 1
        gid = f"merge-{group_n}"
        group = {"id": gid, "kind": "merge", "reason": "merge requested",
                 "choices": ["delete", "suspend", "keep"],
                 "note_ids": [victim.get("anki_note_id")],
                 "cards": [{"rev_id": victim.get("rev_id"),
                            "label": _label(victim)}],
                 "survivor": {"rev_id": survivor.get("rev_id"),
                              "label": _label(survivor)}}
        groups.append(group)
        actions.append({
            "kind": "merge", "note_id": survivor.get("anki_note_id"),
            "rev_id": survivor.get("rev_id"),
            "victim_note_id": victim.get("anki_note_id"),
            "victim_rev_id": victim.get("rev_id"),
            "before": _row_fields(victim, "Cloze" if victim.get("cloze") else ""),
            "after": {}, "group": gid, "risk": "high",
            "reason": "merge requested", "topic": victim.get("topic"),
            "layer": victim.get("layer"), "survivor_label": _label(survivor),
            "front": victim.get("front"),
        })
        victim_note = note_by_id.get(int(victim.get("anki_note_id") or 0))
        if victim_note:
            for c in _base_conflicts(victim_note, actions[-1]["before"]):
                conflicts.append({"rev_id": victim.get("rev_id"),
                                  "label": _label(victim), **c})
    elif selected and (intent["cull"] or intent["merge"]):
        by_topic = defaultdict(list)
        for row in selected:
            by_topic[str(row.get("topic") or "?")].append(row)
        for topic, victims in by_topic.items():
            group_n += 1
            if intent["merge"]:
                group, new_actions = _merge_group(rows, victims, topic, group_n)
                if group:
                    groups.append(group)
                    actions.extend(new_actions)
                    for a in new_actions:
                        note = note_by_id.get(int(a["victim_note_id"] or 0))
                        if note:
                            for c in _base_conflicts(note, a["before"]):
                                conflicts.append({"rev_id": a["victim_rev_id"],
                                                  "label": _label(next(
                                                      r for r in victims
                                                      if r.get("rev_id") == a["victim_rev_id"])),
                                                  **c})
                    continue
            gid = f"cull-{group_n}"
            groups.append({"id": gid, "kind": "cull",
                           "reason": "easiest / known cards",
                           "preferred": intent.get("preferred") or "",
                           "choices": ["delete", "suspend", "keep"],
                           "note_ids": [v.get("anki_note_id") for v in victims],
                           "cards": [{"rev_id": v.get("rev_id"),
                                      "label": _label(v)} for v in victims]})
            for victim in victims:
                base = _row_fields(victim, "Cloze" if victim.get("cloze") else "")
                actions.append({
                    "kind": "cull", "note_id": victim.get("anki_note_id"),
                    "rev_id": victim.get("rev_id"), "before": base, "after": {},
                    "group": gid, "risk": "high",
                    "reason": "score 1: known / too easy",
                    "front": victim.get("front"), "topic": victim.get("topic"),
                    "layer": victim.get("layer"),
                })
                note = note_by_id.get(int(victim.get("anki_note_id") or 0))
                if note:
                    for c in _base_conflicts(note, base):
                        conflicts.append({"rev_id": victim.get("rev_id"),
                                          "label": _label(victim), **c})

    # Splits: existing card keeps its history; new cards start new.
    if args.split_match:
        row = _find_one(rows, args.split_match)
        nid = int(row.get("anki_note_id") or 0)
        if nid not in note_by_id:
            print("revision.py: split target is not attached; run attach first",
                  file=sys.stderr)
            return 2
        fronts, backs = args.split_front or [], args.split_back or []
        if not fronts or len(fronts) != len(backs):
            print("revision.py: split needs equal --split-front/--split-back lists",
                  file=sys.stderr)
            return 2
        actions.append({
            "kind": "split", "note_id": nid, "rev_id": row.get("rev_id"),
            "before": _row_fields(row, _model(note_by_id[nid])),
            "new": [{"front": f, "back": b, "layer": row.get("layer"),
                     "topic": row.get("topic"), "source": row.get("source"),
                     "source_url": row.get("source_url"),
                     "objects": row.get("objects") or [],
                     "cloze": bool(row.get("cloze"))} for f, b in zip(fronts, backs)],
            "risk": "low", "reason": "split requested",
            "front": row.get("front"), "topic": row.get("topic"),
            "layer": row.get("layer"), "match": row.get("front"),
        })

    if args.attach_media or intent["visual"]:
        actions.extend(_media_actions(rows, dc.load(ctx["key"])["media_candidates"]
                                      if ctx else [], note_by_id))
        for a in actions:
            if a["kind"] == "attach_media" and a.get("low_res"):
                conflicts.append({"rev_id": a["rev_id"], "label": _label(
                    rows_by_id.get(int(a["note_id"]), {})),
                    "field": "media", "base": "",
                    "current": "source missing; preview is low-res"})

    if not actions:
        print("revision.py: no actions were produced; nothing to apply.",
              file=sys.stderr)
        return 2

    plan = _plan_doc(ctx["key"] if ctx else dc.resolve(deck_name) or "",
                     deck_name, intent_text, actions, groups, conflicts)
    if not plan["deck_key"]:
        print("revision.py: no dossier for this deck; run attach --reconstruct "
              "first.", file=sys.stderr)
        return 2
    out = dc.revision_dir(plan["deck_key"]) / "revision_plan"
    dc.write_json(out.with_suffix(".json"), plan)
    out.with_suffix(".md").write_text(_render_plan(plan))
    if args.json:
        print(json.dumps({"plan": str(out.with_suffix(".json")),
                          "counts": plan["counts"],
                          "groups": [g["id"] for g in groups],
                          "conflicts": len(conflicts)}, indent=2))
    else:
        print(f"plan       {out.with_suffix('.md')}")
        print(f"           {plan['counts']['updated']} update(s), "
              f"{plan['counts']['added']} new card(s), "
              f"{plan['counts']['destructive']} removal candidate(s), "
              f"{len(conflicts)} conflict(s)")
        if groups:
            print("           destructive groups: " +
                  ", ".join(g["id"] for g in groups) +
                  " — choose delete / suspend / keep before applying")
    return 0


# -------------------------------------------------------------------- apply

def _parse_choices(values: list[str] | None) -> dict[str, str]:
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


def _schedule_unchanged(before: dict, after: dict) -> bool:
    a = {int(c["cardId"]): c for c in before.get("cards", []) if "cardId" in c}
    b = {int(c["cardId"]): c for c in after.get("cards", []) if "cardId" in c}
    if set(a) != set(b):
        return False
    for cid, old in a.items():
        for key in SCHEDULE_KEYS:
            if key in old and old.get(key) != b[cid].get(key):
                return False
    return True


def _row_from_fields(row: dict, note: dict, fields: dict) -> None:
    if _is_cloze(_model(note), row):
        row["front"] = _strip_footer(fields.get("Text", row.get("front", "")))
        row["back"] = _strip_footer(fields.get("Extra", row.get("back", "")))
        row["cloze"] = True
    else:
        row["front"] = _strip_footer(fields.get("Front", row.get("front", "")))
        row["back"] = _strip_footer(fields.get("Back", row.get("back", "")))
    row["content_hash"] = card_hash({"front": row.get("front", ""),
                                     "back": row.get("back", "")})
    row["state"] = "live"


def cmd_apply(args) -> int:
    ac = _client(args.url)
    plan_path = Path(args.plan).expanduser()
    try:
        plan = json.loads(plan_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"revision.py: cannot read plan: {e}", file=sys.stderr)
        return 2
    if plan.get("schema") != PLAN_SCHEMA or not plan.get("deck_key"):
        print("revision.py: unsupported plan schema", file=sys.stderr)
        return 2
    ctx = dc.load(plan["deck_key"])
    rows = ctx["cards"]
    rows_by_id = _row_by_note(rows)
    groups = plan.get("destructive_groups") or []
    try:
        choices = _parse_choices(args.choice)
    except PlanError as e:
        print(f"revision.py: {e}", file=sys.stderr)
        return 2
    missing = [g["id"] for g in groups if g["id"] not in choices]
    if missing:
        print("revision.py: destructive choices are required; nothing was written.",
              file=sys.stderr)
        for gid in missing:
            print(f"  --choice {gid}=<delete|suspend|keep>", file=sys.stderr)
        return 2
    extra = set(choices) - {g["id"] for g in groups}
    if extra:
        print(f"revision.py: unknown group(s): {', '.join(sorted(extra))}",
              file=sys.stderr)
        return 2

    fields_needed = any(a["kind"] in ("update_fields", "attach_media") or
                        (a["kind"] == "merge" and a.get("after"))
                        for a in plan.get("actions", []))
    if fields_needed and not args.browser_closed:
        print("revision.py: close Anki's Browser window before field updates "
              "(updateNoteFields can silently fail while a note is open), then "
              "pass --browser-closed.", file=sys.stderr)
        return 2
    low_res = [a for a in plan.get("actions", [])
               if a["kind"] == "attach_media" and a.get("low_res")]
    if low_res and not args.allow_low_res:
        print("revision.py: the source file for this media is gone; only a "
              "low-res preview exists. Pass --allow-low-res to use it, or "
              "re-extract the original first.", file=sys.stderr)
        return 2
    if not args.allow_card_shape_change:
        for a in plan.get("actions", []):
            if a["kind"] != "update_fields" or not a.get("after"):
                continue
            note = next((n for n in ac.notes_info([int(a["note_id"])])
                         if isinstance(n, dict) and n.get("noteId")), None)
            if not note or not _is_cloze(_model(note)):
                continue
            field = "Text" if "Text" in a["after"] else ""
            if not field:
                continue
            old = set(re.findall(r"\{\{c(\d+)::", _fields(note).get(field, "")))
            new = set(re.findall(r"\{\{c(\d+)::", a["after"][field]))
            if old != new:
                print("revision.py: this update changes cloze ordinals; unchanged "
                      "ordinals keep history but new/removed cards start or lose "
                      "theirs. Pass --allow-card-shape-change only after reviewing "
                      "that consequence.", file=sys.stderr)
                return 2

    note_ids = sorted({int(a["note_id"]) for a in plan.get("actions", [])
                       if a.get("note_id")} |
                      {int(a["victim_note_id"]) for a in plan.get("actions", [])
                       if a.get("victim_note_id")} |
                      {int(n) for g in groups for n in g.get("note_ids", [])
                       if n})
    notes = [n for n in ac.notes_info(note_ids)
             if isinstance(n, dict) and n.get("noteId")]
    note_by_id = {int(n["noteId"]): n for n in notes}
    missing_notes = [nid for nid in note_ids if nid not in note_by_id]
    if missing_notes:
        print(f"revision.py: {len(missing_notes)} planned note(s) are gone; "
              "re-run attach/plan.", file=sys.stderr)
        return 2
    before_fp, card_map, reviews = _schedule(ac, notes)

    # Recheck manual edits at apply time; they win unless explicitly overridden.
    conflicts = list(plan.get("conflicts") or [])
    conflict_ids: set[int] = set()
    for a in plan.get("actions", []):
        note = note_by_id.get(int(a.get("note_id") or 0))
        if not note:
            continue
        if a["kind"] in ("update_fields", "attach_media"):
            proposed = a.get("after") or {}
            base = a.get("before") or {}
            if a["kind"] == "attach_media":
                field = a.get("field") or "Back"
                current = _fields(note)
                if dc.plain_text(current.get(field, "")) != dc.plain_text(
                        base.get(field, "")):
                    conflicts.append({"rev_id": a.get("rev_id"),
                                      "label": _label(rows_by_id.get(int(a["note_id"]), {})),
                                      "field": field, "base": base.get(field, ""),
                                      "current": current.get(field, ""),
                                      "proposed": "append media"})
                    conflict_ids.add(int(a["note_id"]))
            for c in _proposed_conflicts(note, base, proposed):
                conflicts.append({"rev_id": a.get("rev_id"),
                                  "label": _label(rows_by_id.get(int(a["note_id"]), {})),
                                  **c})
                conflict_ids.add(int(a["note_id"]))
        elif a["kind"] in ("cull", "merge"):
            victim_id = (int(a.get("victim_note_id") or 0)
                         if a["kind"] == "merge" else int(a.get("note_id") or 0))
            victim = note_by_id.get(victim_id)
            if victim:
                for c in _base_conflicts(victim, a.get("before") or {}):
                    conflicts.append({"rev_id": a.get("victim_rev_id") or a.get("rev_id"),
                                      "label": _label(rows_by_id.get(victim_id, {})),
                                      **c})
                    conflict_ids.add(victim_id)
        if a["kind"] == "merge" and a.get("after"):
            survivor = note_by_id.get(int(a["note_id"]))
            if survivor:
                for c in _proposed_conflicts(survivor, a.get("before") or {},
                                             a["after"]):
                    conflicts.append({"rev_id": a.get("rev_id"),
                                      "label": _label(rows_by_id.get(int(a["note_id"]), {})),
                                      **c})
                    conflict_ids.add(int(a["note_id"]))
    if conflict_ids and not args.overwrite_conflicts:
        print(f"revision.py: {len(conflict_ids)} card(s) have manual Anki edits; "
              "they will be skipped (user edits win). Pass "
              "--overwrite-conflicts only after reviewing the plan.", file=sys.stderr)

    stamp = _stamp()
    revdir = dc.revision_dir(ctx["key"], stamp)
    dc.write_json(revdir / "conflicts.json", {"conflicts": conflicts})

    # Validate every destructive group before any write, then back up.
    destructive: list[tuple[dict, str, list[int]]] = []
    for group in groups:
        choice = choices[group["id"]]
        ids = [int(n) for n in group.get("note_ids") or [] if n]
        ids = [n for n in ids if n not in conflict_ids or args.overwrite_conflicts]
        destructive.append((group, choice, ids))
    if any(choice in ("delete", "suspend") and ids
           for _, choice, ids in destructive):
        backup = {
            "schema": 1, "created_at": dc.now(), "deck_key": ctx["key"],
            "plan": str(plan_path), "notes": notes,
            "cards": [c for c in card_map.values()],
            "reviews": reviews,
            "dossier_cards": rows,
        }
        dc.write_json(revdir / "backup.json", backup)

    updated, added, suspended, deleted, kept, failures = [], [], [], [], [], []
    before_notes = {int(n["noteId"]): n for n in notes}
    verification: list[dict] = []

    def update_note(action: dict) -> None:
        nid = int(action["note_id"])
        note = note_by_id[nid]
        row = rows_by_id.get(nid, {})
        current = _fields(note)
        proposed = dict(action.get("after") or {})
        if action["kind"] == "attach_media":
            cand = action.get("candidate") or {}
            original = Path(str(cand.get("original_path") or ""))
            preview = (Path(ctx["path"]) / str(cand.get("preview") or "")
                       if cand.get("preview") else None)
            source = original if original.is_file() else preview
            if not source or not source.is_file():
                failures.append({"note_id": nid,
                                 "reason": "media source and preview are missing"})
                return
            if not original.is_file():
                print(f"revision.py: warning: using a low-res preview for "
                      f"{cand.get('file')}", file=sys.stderr)
            ac.store_media_file(action["media_filename"], path=source)
            proposed = {action["field"]:
                        current.get(action["field"], "") + action.get("snippet", "")}
        else:
            for field, value in list(proposed.items()):
                back = field in ("Back", "Extra")
                proposed[field] = _field_html(
                    value, current.get(field, ""), back=back,
                    source=str(row.get("source") or ""),
                    source_url=str(row.get("source_url") or ""))
        if nid in conflict_ids and not args.overwrite_conflicts:
            return
        if _is_cloze(_model(note), row) and "Text" in proposed:
            old_ord = set(re.findall(r"\{\{c(\d+)::", current.get("Text", "")))
            new_ord = set(re.findall(r"\{\{c(\d+)::", proposed["Text"]))
            if old_ord != new_ord and not args.allow_card_shape_change:
                failures.append({"note_id": nid,
                                 "reason": "cloze ordinals change; pass "
                                           "--allow-card-shape-change"})
                return
        ac.update_note_fields(nid, proposed)
        updated.append({"note_id": nid, "rev_id": action.get("rev_id"),
                        "fields": list(proposed), "wanted": proposed})

    # Field updates and media first, then new cards, then destructive choices.
    for action in plan.get("actions", []):
        if action["kind"] in ("update_fields", "attach_media"):
            update_note(action)
        elif action["kind"] == "merge" and action.get("after"):
            update_note(action)

    for action in plan.get("actions", []):
        if action["kind"] != "split":
            continue
        note = note_by_id[int(action["note_id"])]
        model = _model(note)
        new_notes = []
        for new in action.get("new") or []:
            front = _field_html(new.get("front", ""))
            back = _field_html(new.get("back", ""), back=True,
                               source=str(new.get("source") or ""),
                               source_url=str(new.get("source_url") or ""))
            if "Cloze" in model:
                fields = {"Text": front, "Extra": back}
            else:
                fields = {"Front": front, "Back": back}
            fields.update({"Layer": new.get("layer") or "",
                           "Topic": new.get("topic") or "", "Media": ""})
            new_notes.append({
                "deckName": plan["deck_name"], "modelName": model,
                "fields": fields, "tags": list(note.get("tags") or []),
                "options": {"allowDuplicate": False},
            })
        ids = ac.add_notes(new_notes)
        for new, nid in zip(action.get("new") or [], ids):
            if not nid:
                failures.append({"split": action.get("rev_id"),
                                 "reason": "addNotes returned no id"})
                continue
            row = {
                "rev_id": str(uuid.uuid4()), "anki_note_id": int(nid), "guid": "",
                "front": new["front"], "back": new["back"],
                "layer": new.get("layer") or "", "topic": new.get("topic") or "",
                "deck": plan["deck_name"], "objects": new.get("objects") or [],
                "tier_zero": False, "cloze": bool(new.get("cloze")),
                "stratum": "", "retrieval_target": "", "why": "",
                "source": new.get("source") or "", "source_url": new.get("source_url") or "",
                "media": [], "content_hash": card_hash(new),
                "scheduling_fingerprint": None, "state": "live",
                "confidence": "authored",
            }
            rows.append(row)
            added.append({"note_id": int(nid), "rev_id": row["rev_id"]})

    for group, choice, ids in destructive:
        if not ids:
            continue
        if choice == "keep":
            kept.extend(ids)
            continue
        if choice == "delete":
            ac.delete_notes(ids)
            deleted.extend(ids)
            for nid in ids:
                row = rows_by_id.get(nid)
                if row:
                    row["state"] = "deleted"
        else:
            card_ids = [cid for nid in ids for cid in _note_ids(before_notes[nid])]
            ac.suspend(card_ids)
            suspended.extend(ids)
            for nid in ids:
                row = rows_by_id.get(nid)
                if row:
                    row["state"] = "suspended"

    # Verify every affected note/card after the writes.
    affected = {int(a["note_id"]) for a in plan.get("actions", [])
                if a.get("note_id")} | {int(n) for n in deleted} | {int(n) for n in suspended}
    after_notes = {}
    if affected:
        for n in ac.notes_info(sorted(affected)):
            if isinstance(n, dict) and n.get("noteId"):
                after_notes[int(n["noteId"])] = n
        after_fp, after_cards, after_reviews = _schedule(
            ac, list(after_notes.values()))
    else:
        after_fp, after_cards, after_reviews = {"cards": [], "revlog_count": 0}, {}, {}
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
        field_ok = all(_fields(after_note).get(field) == value
                       for field, value in (item.get("wanted") or {}).items())
        bfp = _fp_for_note(before_note, card_map, reviews) if before_note else {
            "cards": [], "revlog_count": 0}
        afp = _fp_for_note(after_note, after_cards, after_reviews)
        sched_ok = _schedule_unchanged(bfp, afp)
        rev_ok = bfp.get("revlog_count") == afp.get("revlog_count")
        verification.append({"note_id": nid, "fields_ok": field_ok,
                             "scheduling_ok": sched_ok, "revlog_ok": rev_ok,
                             "ok": field_ok and sched_ok and rev_ok})
        ok = ok and field_ok and sched_ok and rev_ok
    for action in plan.get("actions", []):
        if action["kind"] != "split":
            continue
        nid = int(action["note_id"])
        after_note = after_notes.get(nid)
        before_note = before_notes.get(nid)
        good = bool(after_note and before_note)
        if good:
            bfp = _fp_for_note(before_note, card_map, reviews)
            afp = _fp_for_note(after_note, after_cards, after_reviews)
            good = (_schedule_unchanged(bfp, afp)
                    and bfp.get("revlog_count") == afp.get("revlog_count"))
        verification.append({"note_id": nid, "ok": good,
                             "reason": "split keeps the existing card's history"})
        ok = ok and good
    for action in plan.get("actions", []):
        if action["kind"] != "merge":
            continue
        nid = int(action["note_id"])
        before_note = before_notes.get(nid)
        after_note = after_notes.get(nid)
        good = bool(before_note and after_note)
        if good:
            bfp = _fp_for_note(before_note, card_map, reviews)
            afp = _fp_for_note(after_note, after_cards, after_reviews)
            good = (_schedule_unchanged(bfp, afp)
                    and bfp.get("revlog_count") == afp.get("revlog_count"))
        verification.append({"note_id": nid, "ok": good,
                             "reason": "merge keeps the survivor's history"})
        ok = ok and good
    for nid in deleted:
        verification.append({"note_id": nid, "ok": nid not in after_notes,
                             "reason": "deleted"})
        ok = ok and nid not in after_notes
    for nid in suspended:
        after = after_notes.get(nid)
        good = bool(after) and all(
            (after_cards.get(cid, {}).get("queue") == -1)
            for cid in _note_ids(after))
        verification.append({"note_id": nid, "ok": good, "reason": "suspended"})
        ok = ok and good
    for item in added:
        nid = item["note_id"]
        exists = [n for n in ac.notes_info([nid])
                  if isinstance(n, dict) and n.get("noteId") and n.get("cards")]
        verification.append({"note_id": nid, "ok": bool(exists),
                             "reason": "new card added"})
        ok = ok and bool(exists)

    # Update dossier rows only after verification; scheduling history belongs to Anki.
    for item in updated:
        nid = item["note_id"]
        row = rows_by_id.get(nid)
        note = after_notes.get(nid)
        if row and note:
            _row_from_fields(row, note, _fields(note))
            fp_one, _, _ = _schedule(ac, [note])
            row["scheduling_fingerprint"] = fp_one
    for nid in suspended:
        row = rows_by_id.get(nid)
        if row:
            row["state"] = "suspended"
    for nid in deleted:
        row = rows_by_id.get(nid)
        if row:
            row["state"] = "deleted"
    dc.write_cards(ctx["key"], rows)
    dc.update_manifest(ctx["key"], last_update=dc.now())

    sync_ok = None
    if args.sync and ok:
        try:
            ac.sync()
            sync_ok = True
        except AnkiConnectError as e:
            sync_ok = False
            failures.append({"sync": str(e)})
            ok = False
    log = {
        "schema": 1, "plan": str(plan_path), "applied_at": dc.now(),
        "deck_key": ctx["key"], "updated": updated, "added": added,
        "suspended": suspended, "deleted": deleted, "kept": kept,
        "conflicts": conflicts, "failures": failures,
        "verification": verification, "verified": ok, "sync": sync_ok,
    }
    ok = ok and not failures
    log["verified"] = ok
    dc.write_json(revdir / "apply_log.json", log)
    dc.write_json(revdir / "verification.json",
                  {"verified": ok, "checks": verification,
                   "scheduling_unchanged": all(
                       v.get("scheduling_ok", True) for v in verification)})
    print(f"applied    {len(updated)} update(s), {len(added)} new card(s), "
          f"{len(suspended)} suspended, {len(deleted)} deleted, "
          f"{len(kept)} kept; {len(conflicts)} conflict(s)")
    print(f"           verification {'ok' if ok else 'FAILED'} -> {revdir}")
    if args.json:
        print(json.dumps(log, indent=2))
    return 0 if ok else 1


# ------------------------------------------------------------------ context

def cmd_context(args) -> int:
    if args.context_cmd == "pack":
        result = dc.pack(args.work, {"deck_name": args.deck,
                                     "deck_id": args.deck_id,
                                     "profile": args.profile,
                                     "notetypes": args.notetypes})
        print(json.dumps(result, indent=2) if args.json else
              f"dossier {result['key']}: {result['cards']} card(s) -> {result['path']}")
        return 0
    if args.context_cmd == "export":
        path = dc.export(args.deck, args.out)
        print(path)
        return 0
    if args.context_cmd == "import":
        result = dc.import_archive(args.archive, attach=not args.no_attach,
                                   url=args.url)
        print(f"dossier {result['key']} -> {result['path']}")
        return 0
    if args.context_cmd == "validate":
        result = dc.validate(deck_key_or_selector=args.deck)
        print(json.dumps(result, indent=2) if args.json else
              f"{len(result['errors'])} error(s), {len(result['warnings'])} warning(s)")
        return 1 if result["errors"] else 0
    return 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="revision.py")
    ap.add_argument("--url", default=None,
                    help="AnkiConnect URL (default 127.0.0.1:8765)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("attach", help="map live note IDs to dossier cards (read-only)")
    a.add_argument("--deck", required=True)
    a.add_argument("--reconstruct", action="store_true")
    a.add_argument("--map", action="append", default=[],
                   metavar="REV_ID=NOTE_ID")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_attach)

    au = sub.add_parser("audit", help="read-only deck/context report")
    au.add_argument("--deck", required=True)
    au.add_argument("--json", action="store_true")
    au.set_defaults(func=cmd_audit)

    p = sub.add_parser("plan", help="intent -> revision_plan.md/.json (no writes)")
    p.add_argument("--deck", required=True)
    p.add_argument("--intent", required=True)
    p.add_argument("--topic", action="append", default=[])
    p.add_argument("--front", default=None)
    p.add_argument("--tag", action="append", default=[])
    p.add_argument("--layer", action="append", default=[])
    p.add_argument("--stratum", action="append", default=[])
    p.add_argument("--score", type=int, choices=range(1, 6))
    p.add_argument("--leech", action="store_true")
    p.add_argument("--allow-anchors", dest="allow_anchors", action="store_true",
                   default=False, help="allow tier-zero anchor cards as victims")
    p.add_argument("--update-front", action="append", default=[], metavar="OLD=NEW")
    p.add_argument("--update-back", action="append", default=[], metavar="OLD=NEW")
    p.add_argument("--merge-match", default=None)
    p.add_argument("--into", default=None)
    p.add_argument("--split-match", default=None)
    p.add_argument("--split-front", action="append", default=[])
    p.add_argument("--split-back", action="append", default=[])
    p.add_argument("--attach-media", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_plan)

    ap_ = sub.add_parser("apply", help="apply an approved plan")
    ap_.add_argument("--plan", required=True)
    ap_.add_argument("--choice", action="append", default=[],
                     metavar="GROUP=delete|suspend|keep")
    ap_.add_argument("--browser-closed", action="store_true")
    ap_.add_argument("--overwrite-conflicts", action="store_true")
    ap_.add_argument("--allow-card-shape-change", action="store_true")
    ap_.add_argument("--allow-low-res", action="store_true")
    ap_.add_argument("--sync", action="store_true")
    ap_.add_argument("--json", action="store_true")
    ap_.set_defaults(func=cmd_apply)

    c = sub.add_parser("context", help="pack/export/import/validate deck dossiers")
    cs = c.add_subparsers(dest="context_cmd", required=True)
    cp = cs.add_parser("pack")
    cp.add_argument("--work", required=True)
    cp.add_argument("--deck", required=True)
    cp.add_argument("--deck-id", default="")
    cp.add_argument("--profile", default="")
    cp.add_argument("--notetypes", nargs="*", default=None)
    cp.add_argument("--json", action="store_true")
    ce = cs.add_parser("export")
    ce.add_argument("--deck", required=True)
    ce.add_argument("--out", required=True)
    ci = cs.add_parser("import")
    ci.add_argument("archive")
    ci.add_argument("--no-attach", action="store_true")
    cv = cs.add_parser("validate")
    cv.add_argument("--deck", required=True)
    cv.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_context)

    args = ap.parse_args(argv)
    if not hasattr(args, "url"):
        args.url = None
    try:
        return args.func(args)
    except AnkiConnectError as e:
        print(str(e), file=sys.stderr)
        return 2
    except (PlanError, ValueError, FileNotFoundError, OSError) as e:
        print(f"revision.py: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
