#!/usr/bin/env python3
"""Native Anki build path.

genanki writes a hand-rolled collection.anki2 that older Anki tolerated and
Anki 26 rejects outright:

    DbError { info: "InvalidColumnType(6, \\"type\\", Integer)" }

It also has a cloze bug -- genanki/card.py hardcodes cards.type = 0, while Anki
decides a card is a cloze card from that column (it must be the 1-based ordinal).
Patching the generated DB fixes one and provokes the other.

So build through Anki's own library instead: the collection creates notetypes and
cards itself, and export writes a schema it will always accept. No genanki, no
post-processing of hand-written SQLite.
"""
from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from pathlib import Path

from anki.collection import Collection
import re

# render.py owns the card CSS and the HTML conversion. This module used to carry
# its own copy of the CSS and the two drifted apart, so the review preview could
# render a card differently from the deck it was previewing. Import, do not copy.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import CSS, to_html, with_source  # noqa: E402
import media  # noqa: E402


def check_cloze_braces(front: str) -> None:
    """Reject braces inside a cloze deletion.

    Anki's own parser terminates a deletion at the FIRST '}}'. LaTeX braces
    inside one therefore close the blank early and the remainder leaks onto the
    front as broken math -- e.g. {{c4::$a = \\frac{4R}{\\sqrt{3}} \\approx
    2.31R$}} renders with a dangling '}} \\approx 2.31R'. Depth counting is
    not enough, because a well-formed-looking deletion is still corrupt.
    """
    for m in re.finditer(r"\{\{c(\d+)::", front):
        j, depth = m.end(), 2
        while j < len(front) and depth > 0:
            if front[j] == "{":
                depth += 1
            elif front[j] == "}":
                depth -= 1
            j += 1
        if depth > 0:
            raise ValueError(
                f"cloze deletion c{m.group(1)} is not closed with '}}'; Anki "
                "would render the rest of the card as literal text")
        body = front[m.end():j - 2]
        if "{" in body or "}" in body:
            raise ValueError(
                f"cloze deletion c{m.group(1)} contains a brace: {body!r}\n"
                "  Anki closes a deletion at the first '}}', so braces inside one\n"
                "  corrupt the front -- the blank ends early and the rest leaks out\n"
                "  as broken math.\n"
                "  Fix: put the math OUTSIDE the deletion (show the formula, blank\n"
                "       a word), or delete the plain-text meaning instead of the\n"
                "       symbol (blank 'a single, specific direction', not '{hkl}').\n"
                "       Unicode '√' renders with no braces at all."
            )

BASIC_ID = 1607392319
CLOZE_ID = 1607392320

META ='<div class="meta">{{Topic}}</div>'

# The card face leads with the topic, never with the layer code. A reader sees
# "Unit Cells", a chapter they could look up, instead of "L2", which is internal
# vocabulary and answers nothing. The layer still ships as a field and a tag so
# triage/roi and filtering by kind keep working; it just stops being the label.
#
def _tag(t):
    """Canonical Anki tag form: lowercase, no spaces, & spelled out.

    The Topic field keeps its display capitalisation; only the tag is folded.
    Anki itself is case-insensitive, so lowercasing prevents mixed-case
    variants from accumulating in the sidebar.
    """
    return str(t).lower().replace(" ", "_").replace("&", "and")


def _retype(base: dict, *, name: str, field_names, qfmt, afmt) -> dict:
    """Clone a built-in notetype dict with our name, fields and templates.

    id must be 0: Anki's legacy notetype adder asserts on any caller-supplied id
    and assigns its own. Look the real ids up by name afterwards.

    The template dict is cloned rather than constructed. A template needs keys the
    browser reads -- bqfmt/bafmt (browser-side question/answer), id, did -- and a
    hand-rolled dict leaves them unset. The reviewer uses qfmt/afmt and looks
    fine; the BROWSER falls back to bqfmt/bafmt and renders the raw field, which
    looks exactly like broken cloze (`{{c1::4}}` visible, cards labelled
    "Card 1 2"). Cloning and overriding only the formatting keys avoids that.
    """
    nt = json.loads(json.dumps(base))          # deep copy
    nt["id"] = 0
    nt["name"] = name
    nt["css"] = CSS
    nt["mod"] = 0
    nt["flds"] = [{"name": n, "ord": i, "sticky": False, "rtl": False,
                   "font": "Arial", "size": 20, "media": []}
                  for i, n in enumerate(field_names)]

    # Keep id/did/bqfmt/bafmt. A hand-rolled template dict leaves the browser-side
    # templates unset; the REVIEWER then looks fine while the BROWSER falls back to
    # showing raw field text -- which reads exactly like broken cloze.
    tmpl = json.loads(json.dumps(nt["tmpls"][0]))
    tmpl["name"] = "Card 1"
    tmpl["ord"] = 0
    tmpl["qfmt"] = qfmt
    tmpl["afmt"] = afmt
    tmpl["bqfmt"] = qfmt                        # browser preview must match
    tmpl["bafmt"] = afmt
    nt["tmpls"] = [tmpl]

    nt["conf"] = dict(nt.get("conf", {}))
    return nt


def build_with_anki(cards: list[dict], out_path: str, deck_name: str,
                    existing_apkg: str | None = None,
                    media_root: str | None = None,
                    enable_media: bool = False) -> dict:
    import build_apkg                           # noqa: E402

    # New cards are read in add order, so this is the deck's default study order.
    cards = build_apkg.study_order(cards)
    cards = build_apkg.normalize_objects(cards)

    if enable_media:
        missing = []
        for c in cards:
            for m in media.items(c):
                try:
                    if not media.resolve(media_root or ".", m["file"]).is_file():
                        missing.append(m["file"])
                except ValueError as e:
                    missing.append(str(e))
        if missing:
            shown = ", ".join(sorted(set(missing))[:8])
            raise ValueError(f"media file(s) not found: {shown}"
                             + (f" (+{len(missing) - 8} more)"
                                if len(missing) > 8 else ""))

    with tempfile.TemporaryDirectory() as td:
        scratch = Path(td) / "build.anki2"
        col = Collection(str(scratch))
        if existing_apkg:
            # Import through Anki's own reader, not by copying collection.anki2:
            # it understands legacy and newer packages (collection.anki2 /
            # .anki21 / .anki21b) and preserves decks, notes, scheduling and tags.
            from anki.importing import ImportAnkiPackageRequest
            try:
                col.import_anki_package(
                    ImportAnkiPackageRequest(package_path=str(existing_apkg)))
            except Exception as e:
                col.close()
                raise ValueError(
                    f"could not import merge target {existing_apkg}: {e}") from e

        base_basic = col.models.by_name("Basic")
        base_cloze = col.models.by_name("Cloze")

        # On a merge, the target deck already has these notetypes. Reuse them:
        # adding them again on every merge accumulated two duplicate notetypes
        # per run (8 -> 10 -> 12 on three merges), which is invisible in the
        # cards but bloats the collection and confuses the browser.
        basic_nt = col.models.by_name("3-Layer STEM")
        if basic_nt is None:
            col.models.add_dict(_retype(
                base_basic, name="3-Layer STEM",
                field_names=["Front", "Back", "Layer", "Topic", "Media"],
                qfmt=META + "{{Front}}",
                afmt="{{FrontSide}}<hr id=\"answer\">{{Back}}"))
            basic_nt = col.models.by_name("3-Layer STEM")
        cloze_nt = col.models.by_name("3-Layer STEM Cloze")
        if cloze_nt is None:
            col.models.add_dict(_retype(
                base_cloze, name="3-Layer STEM Cloze",
                field_names=["Text", "Extra", "Layer", "Topic", "Media"],
                qfmt="{{cloze:Text}}" + META,
                afmt="{{cloze:Text}}<hr id=\"answer\">{{Extra}}"))
            cloze_nt = col.models.by_name("3-Layer STEM Cloze")

        deck_id = col.decks.id(deck_name)
        # the export is scoped to the *current* deck, which defaults elsewhere
        col.decks.set_current(deck_id)
        col.decks.select(deck_id)

        # Which notes are already in this collection? Only meaningful when seeding
        # from the user's deck, and it is the whole point of --merge-existing: the
        # note GUID is content-derived (md5 of front|back), so a card already
        # present is identified by its GUID and must not be added again. Without
        # this the merge path duplicated every card on every re-run, while
        # SKILL.md promised it was idempotent.
        existing_guids: set[str] = set()
        if existing_apkg:
            try:
                existing_guids = {str(g) for g in col.db.list("select guid from notes")}
            except Exception as e:      # schema surprise: merge, but say so
                print(f"  ! could not read existing note ids ({e}); merging without "
                      f"de-duplication", file=sys.stderr)

        added, cloze_notes, skipped, already = 0, 0, 0, 0
        media_cards, media_ignored = 0, 0
        for c in cards:
            missing = [k for k in ("front", "back", "layer", "topic") if k not in c]
            if missing:
                print(f"  ! skipping card, missing {missing}: {str(c.get('front'))[:50]}",
                      file=sys.stderr)
                skipped += 1
                continue
            guid = build_apkg.card_hash(c)
            if guid in existing_guids:
                already += 1
                continue
            # Media is opt-in. Without --media the field is ignored: no files are
            # bundled and no <img> is injected, so a text-only build stays text-only.
            media_items = media.items(c) if enable_media else []
            if not enable_media and c.get("media"):
                media_ignored += 1
            media_names, front_imgs, back_imgs = [], [], []
            if media_items:
                if len(media_items) > media.MAX_PER_CARD:
                    print(f"  ! {len(media_items)} media items on a card; using the first "
                          f"{media.MAX_PER_CARD}", file=sys.stderr)
                    media_items = media_items[:media.MAX_PER_CARD]
                for m in media_items:
                    path = media.resolve(media_root or ".", m["file"])
                    if not path.is_file():
                        raise ValueError(f"media file not found: {m['file']} "
                                         f"(looked under {media_root})")
                    prepared, note = media.prepare(path, Path(td) / "_media")
                    if note:
                        print(f"  · {m['file']}: {note}", file=sys.stderr)
                    if prepared is None:
                        continue
                    stored = col.media.add_file(str(prepared))
                    media_names.append(stored)
                    snippet = media.img_html(stored, m["caption"])
                    (front_imgs if m["side"] == "front" else back_imgs).append(snippet)
                if media_names:
                    media_cards += 1
            src = str(c.get("source") or c.get("source_ref") or "")
            src_url = str(c.get("source_url") or "")
            media_src, media_url = media.primary_source(media_items)
            if media_src:
                src = media_src
                src_url = media_url or src_url
            # Tags are a sniper, not a shotgun: the topic plus at most two
            # object tags. The layer used to be a tag here, but "L2" groups by
            # internal kind and returns every understanding card in the deck --
            # the opposite of what a tag is for. Tags are also the ONLY way to
            # pull up "every card about FCC"; they stand in for cross-links
            # (the no-cross-card-pointers rule forbids a back pointing at another card).
            tags = [_tag(c["topic"])] + [_tag(o) for o in (c.get("objects") or [])]
            tags = list(dict.fromkeys(tags))  # dedupe, keep order
            media_field = ",".join(media_names)
            if c.get("cloze"):
                check_cloze_braces(c["front"])
                note = col.new_note(cloze_nt)
                note["Text"] = to_html(c["front"]) + "".join(front_imgs)
                note["Extra"] = with_source(to_html(c["back"]) + "".join(back_imgs),
                                            src, src_url)
                note["Layer"], note["Topic"] = c["layer"], c["topic"]
                note["Media"] = media_field
                cloze_notes += 1
            else:
                note = col.new_note(basic_nt)
                note["Front"] = to_html(c["front"]) + "".join(front_imgs)
                note["Back"] = with_source(to_html(c["back"]) + "".join(back_imgs),
                                           src, src_url)
                note["Layer"], note["Topic"] = c["layer"], c["topic"]
                note["Media"] = media_field
            note.tags = tags
            # Stable, content-derived GUID. Anki otherwise mints a random one, so a
            # rebuilt card never matches the old note: importing "updates" the deck
            # as duplicates instead of replacing, leaving stale broken cards behind.
            # Deriving it from the content means the same card keeps its identity
            # across every rebuild.
            # build_apkg.card_hash is the single definition of a card's identity --
            # it is also what review_server.py records per reviewed card, so a score
            # can be traced back to the note it referred to.
            note.guid = guid
            col.add_note(note, deck_id)
            added += 1

        # Capture the media directory before closing; files added with
        # col.media.add_file() are stored there under their Anki names.
        media_dir = Path(col.media.dir())
        n_notes = col.note_count()
        n_cards = col.card_count()
        col.close()

        # Package the classic .apkg layout by hand: collection.anki2 + a `media`
        # JSON map + files named by their map index. Anki's exporter writes a
        # stub collection.anki2 for legacy readers (the real data goes in
        # collection.anki21), which is not what this skill validates or what
        # older Anki opens. The manual layout is Anki's classic format.
        media_files = (sorted(p for p in media_dir.iterdir() if p.is_file())
                       if media_dir.exists() else [])
        media_map = {str(i): p.name for i, p in enumerate(media_files)}
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(scratch, "collection.anki2")
            for i, p in enumerate(media_files):
                z.write(p, str(i))
            z.writestr("media", json.dumps(media_map))

    return {"notes": n_notes, "cards": n_cards,
            "cloze_notes": cloze_notes, "skipped": skipped, "added": added,
            "already_present": already, "media_cards": media_cards,
            "media_ignored": media_ignored}