#!/usr/bin/env python3
"""Validate a built .apkg by reading what actually landed in the collection.

Checks the ARTIFACT, not the source, because that is where silent breakage shows
up: a deck can import perfectly and still be unreadable on screen.

Catches: stray $ delimiters, literal markdown, unbalanced MathJax, tag imbalance,
control-char corruption, empty fields, duplicate fronts.

Uses stdlib sqlite3 rather than the `anki` library, so it runs even where the anki
package is absent -- importing an .apkg for real is slow and mutates state, which
is not something you want in a check step.
"""
import argparse
import json
import re
import sqlite3
import sys
import tempfile
import zipfile
from difflib import SequenceMatcher
from pathlib import Path

ALLOWED_TAGS = {"p", "b", "strong", "i", "em", "u", "ul", "ol", "li", "table", "tr",
                "th", "td", "code", "pre", "div", "span", "br", "hr", "sub", "sup",
                "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "dl", "dt", "dd",
                "img"}
VOID = {"br", "hr", "img"}
CTRL = re.compile(r"[\x07\x08\x09\x0b\x0c\x0d]")


def audit(card_text: str) -> list[str]:
    bad = []
    if CTRL.search(card_text):
        bad.append("control-char corruption (raw-string escape leak)")
    prose = re.sub(r"<(code|pre)\b.*?</\1>", "", card_text, flags=re.S | re.I)
    if re.search(r"(?<!\\)\$", prose):
        bad.append("stray $ delimiter -- Anki will NOT render this as math")
    if prose.count(r"\(") != prose.count(r"\)"):
        bad.append("unbalanced \\( \\) inline math")
    if prose.count(r"\[") != prose.count(r"\]"):
        bad.append("unbalanced \\[ \\] display math")
    for m in re.finditer(r"\\[\[(](.+?)\\[\])]", card_text, re.S):
        if m.group(1).count("{") != m.group(1).count("}"):
            bad.append(f"brace imbalance in display math: {m.group(1)[:40]!r}")
    if "**" in card_text or "`" in card_text:
        bad.append("literal markdown (** or `) -- Anki renders no markdown")
    if re.search(r"^\s*\|", card_text, re.M):
        bad.append("literal markdown table")
    if re.search(r"<p>(?:(?!</p>).)*?<div", card_text, re.S):
        bad.append("<div> nested inside <p>")
    tags = [(m.group(1), m.group(2).lower())
            for m in re.finditer(r"<(/?)([a-zA-Z]+)", card_text)]
    unknown = sorted({t for _, t in tags if t not in ALLOWED_TAGS})
    if unknown:
        bad.append(f"unexpected tag(s): {unknown}")
    opens = sum(1 for c, t in tags if not c and t not in VOID)
    closes = sum(1 for c, t in tags if c)
    if opens != closes:
        bad.append(f"tag imbalance {opens} open vs {closes} close")
    return bad


def render_test(apkg: str) -> list[str]:
    """Render every card. Catches the browser/reviewer template split.

    Anki renders in two places from two template pairs: qfmt/afmt in the
    reviewer, bqfmt/bafmt in the browser. A note type with only the first pair
    reviews perfectly and previews as raw field text -- `{{c1::4}}` visible
    where a blank should be. No structural check can see this; only rendering the
    card and looking for leftover cloze markers can.
    """
    try:
        import tempfile
        from anki.collection import Collection
        from anki.importing import ImportAnkiPackageRequest
    except ImportError:
        return []
    problems = []
    try:
        with tempfile.TemporaryDirectory() as td:
            col = Collection(str(Path(td) / "t.anki2"))
            try:
                col.import_anki_package(ImportAnkiPackageRequest(package_path=apkg))
                for cid in col.find_cards(""):
                    # BOTH paths matter: qfmt/afmt drive the reviewer,
                    # bqfmt/bafmt drive the browser. Only the first being
                    # populated reviews fine and previews as raw field text.
                    for browser in (False, True):
                        r = col._backend.render_existing_card(
                            card_id=cid, browser=browser, partial_render=False)
                        if "{{c" in str(r.question_nodes):
                            where = "browser preview" if browser else "reviewer"
                            problems.append(
                                f"card {cid}: raw {{{{cN::}} marker in the "
                                f"{where} FRONT -- the deletion is not being "
                                "blanked (bqfmt/bafmt not populated?)")
                            break
                # Math damage check on the REVIEWER path only. Anki's renderer
                # rewrites inline \(..\) to display \[..\], so unbalanced \[ is a
                # real defect, not a formatting artefact. This catches the class
                # of bug where a cloze deletion swallows the tail of a LaTeX
                # expression, leaving \\frac{4R}{\\sqrt{3 orphaned on the front.
                for cid in col.find_cards(""):
                    r = col._backend.render_existing_card(
                        card_id=cid, browser=False, partial_render=False)
                    for attr in ("question_nodes", "answer_nodes"):
                        body = re.sub(r"<[^>]+>", "", str(getattr(r, attr)))
                        for o, c, lbl in ((r"\(", r"\)", r"inline \(\)"),
                                          (r"\[", r"\]", r"display \[\]")):
                            if body.count(o) != body.count(c):
                                problems.append(
                                    f"card {cid} {attr}: unbalanced {lbl} "
                                    f"({body.count(o)} open vs {body.count(c)} close)")
                        for m in re.finditer(r"\\\[(.*?)\\\]", body, re.S):
                            if m.group(1).count("{") != m.group(1).count("}"):
                                problems.append(
                                    f"card {cid} {attr}: unbalanced LaTeX braces "
                                    f"inside math: {m.group(1)[:60]!r}")
            finally:
                col.close()
    except Exception as e:
        problems.append(f"render check failed: {type(e).__name__}: {e}")
        return problems
    return problems[:10]


def import_test(apkg: str) -> list[str]:
    """Actually import the package. The only check that proves Anki will accept it.

    Structural inspection cannot predict this. A genanki-written package passes
    every field/DDL check and still dies on import with
    `InvalidColumnType(6, "type", Integer)`; and setting cards.type = ord+1 by
    hand to fix cloze produces that exact error. Both were observed. Only a real
    import settles it.
    """
    try:
        import tempfile
        from anki.collection import Collection
        from anki.importing import ImportAnkiPackageRequest
    except ImportError:
        return []                      # anki library absent; structural checks only

    problems = []
    try:
        with tempfile.TemporaryDirectory() as td:
            col = Collection(str(Path(td) / "t.anki2"))
            try:
                col.import_anki_package(ImportAnkiPackageRequest(package_path=apkg))
            finally:
                col.close()
    except Exception as e:
        problems.append(f"Anki refused to import this package: "
                        f"{type(e).__name__}: {str(e)[:180]}")
    return problems


def media_test(apkg: str) -> list[str]:
    """Every <img src> that names a local file must be present in the package media."""
    try:
        from anki.collection import Collection
        from anki.importing import ImportAnkiPackageRequest
    except ImportError:
        return []
    problems = []
    try:
        with tempfile.TemporaryDirectory() as td:
            col = Collection(str(Path(td) / "t.anki2"))
            try:
                col.import_anki_package(ImportAnkiPackageRequest(package_path=apkg))
                for nid in col.db.list("select id from notes"):
                    for field in col.get_note(nid).fields:
                        for m in re.finditer(r'<img[^>]+src="([^"]+)"', field):
                            name = m.group(1)
                            if name.startswith(("http:", "https:", "data:")):
                                continue
                            if not col.media.have(name):
                                problems.append(
                                    f"note {nid}: image {name!r} is referenced but "
                                    "not present in the package media")
            finally:
                col.close()
    except Exception as e:
        problems.append(f"media check failed: {type(e).__name__}: {str(e)[:160]}")
    return problems[:10]


def cloze_integrity(tmpdir: str) -> list[str]:
    """Cloze notes must expand to one card per deletion, and vice versa."""
    problems = []
    db = Path(tmpdir) / "collection.anki2"
    con = sqlite3.connect(db)
    try:
        cloze_mids = set()
        try:                                     # classic schema: col.models JSON
            raw = con.execute("select models from col").fetchone()
            if raw:
                cloze_mids = {m["id"] for m in json.loads(raw[0]).values()
                              if m.get("type") == 1}
        except (json.JSONDecodeError, TypeError):
            pass
        if not cloze_mids:
            try:                                 # native schema: templates carry it
                rows = con.execute(
                    "select nt.id from notetypes nt join templates t "
                    "on t.ntid = nt.id where t.qfmt like '%cloze:%'").fetchall()
                cloze_mids = {r[0] for r in rows}
            except sqlite3.OperationalError:
                pass
        if not cloze_mids:
            return problems

        marks = ",".join(str(m) for m in cloze_mids)
        notes = con.execute(
            f"select count(*) from notes where mid in ({marks})").fetchone()[0]
        cards = con.execute(
            f"select count(*) from cards where nid in "
            f"(select id from notes where mid in ({marks}))").fetchone()[0]
        if not notes:
            return problems
        if cards <= notes:
            problems.append(
                f"{notes} cloze note(s) produced only {cards} card(s) — deletions "
                "were not split into separate cards, so {{cN::}} will render raw")
        return problems
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("apkg")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show", type=int, default=0, help="print N sample fields")
    args = ap.parse_args()

    if not Path(args.apkg).exists():
        print(f"File not found: {args.apkg}", file=sys.stderr)
        return 1

    errors, warnings, samples = (import_test(args.apkg) + render_test(args.apkg)
                                 + media_test(args.apkg)), [], []
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(args.apkg) as z:
            z.extractall(td)
        db = Path(td) / "collection.anki2"
        if not db.exists():
            note = ("package has no collection.anki2 (newer Anki format); SQLite "
                    "structural checks skipped, the anki-library import/render checks "
                    "above still ran")
            print(note, file=sys.stderr)
            if args.json:
                print(json.dumps({"valid": not errors, "note": note,
                                  "errors": errors, "warnings": warnings}, indent=2))
            else:
                print(f"0 notes audited structurally | {len(errors)} error(s), "
                      f"{len(warnings)} warning(s)")
                for e in errors:
                    print("  ERROR  ", e)
            return 1 if errors else 0
        errors.extend(cloze_integrity(td))
        con = sqlite3.connect(db)
        rows = con.execute("select flds from notes").fetchall()
        con.close()

    fronts = []
    for n, (flds,) in enumerate(rows, 1):
        fields = flds.split("\x1f")
        front, back = (fields + ["", ""])[:2]
        fronts.append(front)
        for idx, (name, txt) in enumerate((("front", front), ("back", back))):
            if not txt.strip():
                errors.append(f"note {n}: empty {name}")
            for b in audit(txt):
                errors.append(f"note {n} ({name}): {b}")
        if len(samples) < args.show:
            samples.append({"note": n, "front": front[:400], "back": back[:400]})

    for i in range(len(fronts)):
        for j in range(i + 1, len(fronts)):
            r = SequenceMatcher(None, fronts[i], fronts[j]).ratio()
            if r > 0.9:
                warnings.append(f"notes {i+1} and {j+1} fronts {r:.0%} similar")

    result = {"valid": not errors, "note_count": len(rows),
              "errors": errors, "warnings": warnings, "samples": samples}

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{len(rows)} notes | {len(errors)} error(s), {len(warnings)} warning(s)")
        for e in errors[:30]:
            print("  ERROR  ", e)
        if len(errors) > 30:
            print(f"  ... and {len(errors) - 30} more")
        for w in warnings[:15]:
            print("  warn   ", w)
        for s in samples:
            print(f"\n--- note {s['note']} ---\n{s['front']}\n{s['back']}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())