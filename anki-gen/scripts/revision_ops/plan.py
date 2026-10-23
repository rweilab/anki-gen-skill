"""Turn plaintext intent into a human and machine revision plan (no writes)."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from pathlib import Path

import deck_context as dc
from anki_connect import AnkiConnect

from .common import (LAYER_RANK, PlanError, base_conflicts, base_fields,
                     find_ctx, label, live_deck_name, note_ids,
                     proposed_conflicts, row_fields, schedule,
                     snapshot_notes, states_by_rev)


def parse_update(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise PlanError("--update-front/--update-back want OLD=NEW")
    old, new = value.split("=", 1)
    if not old:
        raise PlanError("--update-* needs a non-empty old value")
    return old, new


def find_one(cards: list[dict], state_map: dict, text: str,
             field: str = "front") -> tuple[dict, dict]:
    needle = text.casefold()
    matches = []
    for card in cards:
        state = state_map.get(str(card.get("rev_id"))) or {}
        if state.get("state", "live") != "live":
            continue
        if needle in str(card.get(field) or "").casefold():
            matches.append(card)
    if len(matches) == 1:
        card = matches[0]
        return card, state_map[str(card["rev_id"])]
    if not matches:
        raise PlanError(f"no live card has {field} containing {text!r}")
    raise PlanError(f"{len(matches)} live cards contain {text!r}; use a longer "
                    f"phrase: " + "; ".join(label(c, 50) for c in matches[:5]))


def select(cards, state_map, args, intent, note_by_id, card_map):
    out = []
    for card in cards:
        state = state_map.get(str(card.get("rev_id"))) or {}
        if state.get("state", "live") != "live":
            continue
        if not state.get("anki_note_id"):
            continue
        if args.topic and str(card.get("topic")) not in args.topic:
            continue
        if args.front and args.front.casefold() not in str(card.get("front", "")).casefold():
            continue
        if args.tag:
            tags = {str(card.get("topic", "")).casefold()} | {
                str(o).casefold() for o in card.get("objects") or []}
            if not any(t.casefold() in tags for t in args.tag):
                continue
        if args.layer and str(card.get("layer")) not in args.layer:
            continue
        if args.stratum and str(card.get("stratum")) not in args.stratum:
            continue
        score = args.score if args.score is not None else intent.get("score")
        if score is not None and card.get("review_score") != score:
            continue
        if args.leech or intent.get("leech"):
            note = note_by_id.get(int(state.get("anki_note_id") or 0))
            lapses = max((card_map.get(c, {}).get("lapses", 0)
                          for c in note_ids(note or {})), default=0)
            if lapses < 4:
                continue
        out.append(card)
    return out


def candidate_blob(row: dict) -> set[str]:
    text = " ".join(str(row.get(k) or "") for k in ("topic", "front", "source"))
    return {w for w in re.findall(r"[a-z0-9]{3,}", text.casefold())
            if w not in {"the", "and", "for", "with", "what", "why", "how"}}


def media_actions(cards, state_map, media, note_by_id):
    unused = [m for m in media if not m.get("used")]
    actions, taken = [], set()
    for card in cards:
        state = state_map.get(str(card.get("rev_id"))) or {}
        if state.get("state", "live") != "live" or card.get("media"):
            continue
        nid = int(state.get("anki_note_id") or 0)
        note = note_by_id.get(nid)
        if not note:
            continue
        words = candidate_blob(card)
        ranked = []
        for cand in unused:
            if cand.get("file") in taken:
                continue
            score = len(words & candidate_blob(cand)) * 2
            if cand.get("source") and cand["source"] in str(card.get("source", "")):
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
        field = "Extra" if card.get("cloze") else "Back"
        filename = (f"anki-gen-{str(cand.get('sha256') or '')[:12]}"
                    f"{Path(cand.get('preview') or cand.get('file') or 'image.png').suffix or '.png'}")
        actions.append({
            "kind": "attach_media", "note_id": nid, "rev_id": card.get("rev_id"),
            "before": row_fields(card), "after": {}, "field": field,
            "snippet": f'<img src="{filename}">', "media_filename": filename,
            "candidate": cand, "low_res": not cand.get("original_path"),
            "risk": "low", "front": card.get("front"),
            "topic": card.get("topic"), "layer": card.get("layer"),
            "reason": f"use unused {cand.get('kind')} from {cand.get('source') or 'source'}",
        })
    return actions


def merge_group(cards, state_map, victims, topic, n, note_by_id):
    victim_revs = {v.get("rev_id") for v in victims}
    pool = [c for c in cards if c.get("topic") == topic
            and state_map.get(str(c.get("rev_id")), {}).get("state", "live") == "live"
            and c.get("rev_id") not in victim_revs
            and state_map.get(str(c.get("rev_id")), {}).get("anki_note_id")]
    if not pool:
        return {}, []
    survivor = max(pool, key=lambda c: (LAYER_RANK.get(str(c.get("layer")), 0),
                                        len(str(c.get("back") or ""))))
    gid = f"merge-{n}"
    actions = []
    for victim in victims:
        actions.append({
            "kind": "merge",
            "note_id": state_map[str(survivor["rev_id"])].get("anki_note_id"),
            "rev_id": survivor.get("rev_id"),
            "victim_note_id": state_map[str(victim["rev_id"])].get("anki_note_id"),
            "victim_rev_id": victim.get("rev_id"),
            "before": base_fields(victim, state_map[str(victim["rev_id"])],
                                  note_by_id.get(int(state_map[str(victim["rev_id"])]
                                                     .get("anki_note_id") or 0))),
            "after": {}, "group": gid,
            "risk": "high", "topic": victim.get("topic"),
            "layer": victim.get("layer"), "front": victim.get("front"),
            "survivor_label": label(survivor),
            "reason": f"fold into the {survivor.get('layer')} card on {topic}",
        })
    group = {"id": gid, "kind": "merge",
             "reason": f"merge the easiest {topic} cards",
             "choices": ["delete", "suspend", "keep"],
             "note_ids": [state_map[str(v["rev_id"])].get("anki_note_id")
                          for v in victims],
             "cards": [{"rev_id": v.get("rev_id"), "label": label(v)}
                       for v in victims],
             "survivor": {"rev_id": survivor.get("rev_id"),
                          "label": label(survivor)}}
    return group, actions


def plan_doc(uuid, deck_name, intent_text, actions, groups, conflicts):
    return {
        "schema": 1, "plan_id": hashlib.sha256(
            f"{dc.now()}|{uuid}|{intent_text}".encode()).hexdigest()[:16],
        "deck_key": uuid, "deck_name": deck_name, "intent": intent_text,
        "created_at": dc.now(), "conflicts": conflicts, "actions": actions,
        "destructive_groups": groups,
        "counts": {
            "updated": sum(1 for a in actions if a["kind"] in
                           ("update_fields", "attach_media") or
                           (a["kind"] == "merge" and a.get("after"))),
            "added": sum(len(a.get("new") or []) for a in actions
                         if a["kind"] == "split"),
            "destructive": sum(len(g.get("note_ids") or []) for g in groups),
        },
    }


def render(plan: dict) -> str:
    lines = [f"# Revision plan — {plan['deck_name']}", "",
             f"Intent: {plan['intent']}", f"Created: {plan['created_at']}", "",
             "Cards are named by layer, topic, and front text. Note IDs are never "
             "part of the user interface.", ""]
    if not plan["actions"] and not plan["destructive_groups"]:
        lines += ["No changes proposed.", ""]
    if plan["actions"]:
        lines += ["## Proposed", ""]
        for n, action in enumerate(plan["actions"], 1):
            front = action.get("front") or (action.get("before") or {}).get(
                "Front") or (action.get("before") or {}).get("Text", "")
            lab = label({"front": front, "topic": action.get("topic", ""),
                         "layer": action.get("layer", "")})
            if action["kind"] == "split":
                lines.append(f"{n}. **Split** {lab} into "
                             f"{len(action.get('new') or [])} new card(s)")
                for new in action.get("new") or []:
                    lines.append(f"   - {new.get('front', '')[:100]}")
            elif action["kind"] == "merge":
                lines.append(f"{n}. **Merge** {lab} into "
                             f"{action.get('survivor_label') or 'the survivor'} "
                             f"— group `{action.get('group')}`")
            elif action["kind"] == "attach_media":
                cand = action.get("candidate") or {}
                lines.append(f"{n}. **Attach media** to {lab} — "
                             f"{cand.get('file')} — {action.get('reason', '')}")
                if action.get("low_res"):
                    lines.append("   - source file is gone; only a low-res preview "
                                 "exists (needs --allow-low-res)")
            else:
                lines.append(f"{n}. {lab} — {action.get('reason', action['kind'])}")
                for name, value in (action.get("after") or {}).items():
                    old = str((action.get("before") or {}).get(name, ""))[:80]
                    lines.append(f"   - {name}: {old!r} -> {str(value)[:80]!r}")
            lines.append("")
    if plan["destructive_groups"]:
        lines += ["## Destructive groups — choose for each", ""]
        for group in plan["destructive_groups"]:
            lines += [f"### `{group['id']}` — {group.get('reason', group['kind'])}", ""]
            if group.get("survivor"):
                lines.append(f"Survivor: {group['survivor']['label']}")
            for card in group.get("cards", []):
                lines.append(f"- {card['label']}")
            lines += ["", "Choice: **Delete permanently / Suspend / Keep** "
                      "(no default; deletion removes review history).", ""]
    if plan["conflicts"]:
        lines += ["## Conflicts — manual Anki edits win by default", ""]
        for conflict in plan["conflicts"]:
            lines.append(f"- {conflict.get('label') or conflict.get('rev_id')}: "
                         f"{conflict.get('field') or 'card'} differs in Anki")
        lines.append("")
    if plan["destructive_groups"] or plan["actions"]:
        choices = " ".join(f"--choice {g['id']}=<delete|suspend|keep>"
                           for g in plan["destructive_groups"])
        lines += ["## Apply", "",
                  f"`python3 revision.py apply --plan <this plan> {choices}`".strip(),
                  ""]
    return "\n".join(lines)


def plan(ac: AnkiConnect, args) -> dict:
    context = find_ctx(ac, args.deck)
    if context is None:
        raise PlanError("no dossier for this deck; run attach --reconstruct first")
    deck_name = live_deck_name(ac, context, args.deck)
    notes = snapshot_notes(ac, deck_name)
    note_by_id = {int(n["noteId"]): n for n in notes}
    _, card_map, _ = schedule(ac, notes)
    cards = context["cards"]
    state_map = states_by_rev(context)
    low = args.intent.casefold()
    scores = [int(x) for x in re.findall(r"\bscore\s+([1-5])\b", low)]
    intent = {
        "cull": any(w in low for w in ("cull", "trim", "easiest", "drop", "reduce")),
        "merge": any(w in low for w in ("merge", "fold")),
        "leech": "leech" in low,
        "visual": any(w in low for w in ("visual", "image", "diagram", "figure")),
        "preferred": ("suspend" if "suspend" in low else
                      "delete" if "delete" in low else ""),
        "score": scores[0] if scores else None,
    }
    selected = select(cards, state_map, args, intent, note_by_id, card_map)
    if intent["cull"] and intent.get("score") is None and not (
            args.score is not None or args.topic or args.front or args.tag):
        selected = [c for c in selected if c.get("review_score") == 1]
    if not args.allow_anchors:
        selected = [c for c in selected if not c.get("tier_zero")]
    selected = [c for c in selected
                if int((state_map.get(str(c.get("rev_id"))) or {}).get(
                    "anki_note_id") or 0) in note_by_id]
    if (intent["cull"] or intent["merge"]) and not selected and not args.merge_match \
            and not args.split_match and not args.update_front and not args.update_back:
        raise PlanError("no live cards matched the intent; attach the deck, or "
                        "name a topic/front/score")

    actions, groups, conflicts = [], [], []
    group_n = 0

    for value in args.update_front or []:
        old, new = parse_update(value)
        card, state = find_one(cards, state_map, old, "front")
        nid = int(state.get("anki_note_id") or 0)
        note = note_by_id.get(nid)
        if not note:
            raise PlanError(f"{label(card)} is not attached; run attach first")
        base = base_fields(card, state, note)
        field = "Front" if "Front" in base else "Text"
        after = {field: str(card.get("front", "")).replace(old, new, 1)}
        for c in proposed_conflicts(note, base, after):
            conflicts.append({"rev_id": card.get("rev_id"), "label": label(card), **c})
        actions.append({"kind": "update_fields", "note_id": nid,
                        "rev_id": card.get("rev_id"), "before": base,
                        "after": after, "risk": "low",
                        "reason": "requested front rewrite",
                        "front": card.get("front"), "topic": card.get("topic"),
                        "layer": card.get("layer")})
    for value in args.update_back or []:
        old, new = parse_update(value)
        card, state = find_one(cards, state_map, old, "back")
        nid = int(state.get("anki_note_id") or 0)
        note = note_by_id.get(nid)
        if not note:
            raise PlanError(f"{label(card)} is not attached; run attach first")
        base = base_fields(card, state, note)
        field = "Back" if "Back" in base else "Extra"
        after = {field: str(card.get("back", "")).replace(old, new, 1)}
        for c in proposed_conflicts(note, base, after):
            conflicts.append({"rev_id": card.get("rev_id"), "label": label(card), **c})
        actions.append({"kind": "update_fields", "note_id": nid,
                        "rev_id": card.get("rev_id"), "before": base,
                        "after": after, "risk": "low",
                        "reason": "requested back rewrite",
                        "front": card.get("front"), "topic": card.get("topic"),
                        "layer": card.get("layer")})

    if args.merge_match and args.into:
        victim, vstate = find_one(cards, state_map, args.merge_match)
        survivor, sstate = find_one(cards, state_map, args.into)
        group_n += 1
        gid = f"merge-{group_n}"
        groups.append({"id": gid, "kind": "merge", "reason": "merge requested",
                       "choices": ["delete", "suspend", "keep"],
                       "note_ids": [vstate.get("anki_note_id")],
                       "cards": [{"rev_id": victim.get("rev_id"),
                                  "label": label(victim)}],
                       "survivor": {"rev_id": survivor.get("rev_id"),
                                    "label": label(survivor)}})
        vnote = note_by_id.get(int(vstate.get("anki_note_id") or 0))
        action = {"kind": "merge", "note_id": sstate.get("anki_note_id"),
                  "rev_id": survivor.get("rev_id"),
                  "victim_note_id": vstate.get("anki_note_id"),
                  "victim_rev_id": victim.get("rev_id"),
                  "before": base_fields(victim, vstate, vnote), "after": {},
                  "group": gid, "risk": "high", "reason": "merge requested",
                  "topic": victim.get("topic"), "layer": victim.get("layer"),
                  "survivor_label": label(survivor), "front": victim.get("front")}
        actions.append(action)
        if vnote:
            for conflict in base_conflicts(vnote, action["before"]):
                conflicts.append({"rev_id": victim.get("rev_id"),
                                  "label": label(victim), **conflict})
    elif selected and (intent["cull"] or intent["merge"]):
        by_topic = defaultdict(list)
        for card in selected:
            by_topic[str(card.get("topic") or "?")].append(card)
        for topic, victims in by_topic.items():
            group_n += 1
            if intent["merge"]:
                group, new_actions = merge_group(cards, state_map, victims, topic, group_n, note_by_id)
                if group:
                    groups.append(group)
                    actions.extend(new_actions)
                    for action in new_actions:
                        note = note_by_id.get(int(action["victim_note_id"] or 0))
                        if note:
                            for conflict in base_conflicts(note, action["before"]):
                                conflicts.append({
                                    "rev_id": action["victim_rev_id"],
                                    "label": label(next(v for v in victims
                                                        if v.get("rev_id") ==
                                                        action["victim_rev_id"])),
                                    **conflict})
                    continue
            gid = f"cull-{group_n}"
            groups.append({"id": gid, "kind": "cull",
                           "reason": "easiest / known cards",
                           "preferred": intent.get("preferred") or "",
                           "choices": ["delete", "suspend", "keep"],
                           "note_ids": [state_map[str(v["rev_id"])].get("anki_note_id")
                                        for v in victims],
                           "cards": [{"rev_id": v.get("rev_id"),
                                      "label": label(v)} for v in victims]})
            for victim in victims:
                state = state_map[str(victim["rev_id"])]
                vnote = note_by_id.get(int(state.get("anki_note_id") or 0))
                base = base_fields(victim, state, vnote)
                actions.append({"kind": "cull", "note_id": state.get("anki_note_id"),
                                "rev_id": victim.get("rev_id"), "before": base,
                                "after": {}, "group": gid, "risk": "high",
                                "reason": "score 1: known / too easy",
                                "front": victim.get("front"),
                                "topic": victim.get("topic"),
                                "layer": victim.get("layer")})
                if vnote:
                    for conflict in base_conflicts(vnote, base):
                        conflicts.append({"rev_id": victim.get("rev_id"),
                                          "label": label(victim), **conflict})

    if args.split_match:
        card, state = find_one(cards, state_map, args.split_match)
        nid = int(state.get("anki_note_id") or 0)
        if nid not in note_by_id:
            raise PlanError("split target is not attached; run attach first")
        fronts, backs = args.split_front or [], args.split_back or []
        if not fronts or len(fronts) != len(backs):
            raise PlanError("split needs equal --split-front/--split-back lists")
        actions.append({
            "kind": "split", "note_id": nid, "rev_id": card.get("rev_id"),
            "before": base_fields(card, state, note_by_id[nid]),
            "new": [{"front": f, "back": b, "layer": card.get("layer"),
                     "topic": card.get("topic"), "source": card.get("source"),
                     "source_url": card.get("source_url"),
                     "objects": card.get("objects") or [],
                     "cloze": bool(card.get("cloze"))}
                    for f, b in zip(fronts, backs)],
            "risk": "low", "reason": "split requested",
            "front": card.get("front"), "topic": card.get("topic"),
            "layer": card.get("layer"), "match": card.get("front"),
        })

    if args.attach_media or intent["visual"]:
        actions.extend(media_actions(cards, state_map,
                                     context.get("media_candidates") or [],
                                     note_by_id))

    if not actions:
        raise PlanError("no actions were produced; nothing to apply")
    doc = plan_doc(context["uuid"], deck_name, args.intent, actions, groups, conflicts)
    out = dc.revision_dir(context["uuid"]) / "revision_plan"
    dc.write_json(out.with_suffix(".json"), doc)
    out.with_suffix(".md").write_text(render(doc) + "\n")
    return {"plan": str(out.with_suffix(".json")), "counts": doc["counts"],
            "groups": [g["id"] for g in groups], "conflicts": len(conflicts)}
