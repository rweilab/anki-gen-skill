#!/usr/bin/env python3
"""AnkiConnect revision checks: health, attach, audit, plan, apply, conflicts.

A tiny in-process fake AnkiConnect server holds notes/cards so every guard is
tested without Anki. The fake records action names, which is how the tests prove
attach and audit are read-only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import anki_connect  # noqa: E402
import deck_context as dc  # noqa: E402
import render  # noqa: E402

READ_ACTIONS = {"version", "apiReflect", "findNotes", "findCards", "notesInfo",
                "cardsInfo", "getReviewsOfCards", "cardReviews",
                "deckNamesAndIds", "retrieveMediaFile", "getMediaFilesNames"}


class FakeAnki:
    def __init__(self):
        self.decks = {"SCHOOL::RTOS": 1, "AMB::DECK": 2, "REVERT::DECK": 3}
        self.next_note = 1000
        self.next_card = 2000
        self.notes: dict[int, dict] = {}
        self.cards: dict[int, dict] = {}
        self.reviews: dict[int, list] = {}
        self.media: dict[str, bytes] = {}
        self.media_dir = Path(tempfile.gettempdir())
        self.calls: list[str] = []

    def writes(self) -> list[str]:
        return [c for c in self.calls if c not in READ_ACTIONS]

    def add(self, deck: str, model: str, fields: dict, tags=None,
            schedule=None) -> int:
        self.next_note += 1
        nid = self.next_note
        names = (["Text", "Extra", "Layer", "Topic", "Media"] if "Cloze" in model
                 else ["Front", "Back", "Layer", "Topic", "Media"])
        filled = {name: {"value": str(fields.get(name, "")), "order": i}
                  for i, name in enumerate(names)}
        count = 1
        if "Cloze" in model:
            count = max(1, len(set(__import__("re").findall(
                r"\{\{c(\d+)::", str(fields.get("Text", ""))))))
        cids = []
        for _ in range(count):
            self.next_card += 1
            cid = self.next_card
            card = {"cardId": cid, "note": nid, "deckName": deck,
                    "interval": 12, "factor": 2500, "due": 30, "reps": 3,
                    "lapses": 0, "queue": 2, "type": 2, "left": 0}
            card.update(schedule or {})
            self.cards[cid] = card
            self.reviews[cid] = [{"id": 1, "ease": 3}]
            cids.append(cid)
        self.notes[nid] = {"noteId": nid, "deckName": deck, "modelName": model,
                           "fields": filled, "tags": list(tags or []),
                           "cards": cids, "mod": 1}
        return nid

    def handle(self, action: str, params: dict):
        self.calls.append(action)
        if action == "version":
            return 6
        if action == "apiReflect":
            return {"actions": list(params.get("actions") or [])}
        if action == "getMediaDirPath":
            return str(self.media_dir)
        if action == "exportPackage":
            target = Path(params.get("path") or "")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({
                "notes": self.notes, "cards": self.cards,
                "reviews": self.reviews}))
            return True
        if action == "importPackage":
            source = Path(params.get("path") or "")
            if not source.is_absolute():
                source = self.media_dir / source
            data = json.loads(source.read_text())
            for nid, note in data.get("notes", {}).items():
                nid = int(nid)
                if nid in self.notes:
                    continue
                note = json.loads(json.dumps(note))
                self.notes[nid] = note
                for cid in note.get("cards") or []:
                    cid = int(cid)
                    self.cards[cid] = data["cards"].get(str(cid), {})
                    self.reviews[cid] = data.get("reviews", {}).get(str(cid), [])
            return True
        if action == "deckNamesAndIds":
            return self.decks
        if action in ("findNotes", "findCards"):
            import re
            m = re.search(r'deck:"([^"]*)"', str(params.get("query", "")))
            want = m.group(1) if m else ""
            store = self.notes if action == "findNotes" else self.cards
            return sorted(key for key, row in store.items()
                          if not want or row["deckName"].casefold() == want.casefold())
        if action in ("notesInfo", "cardsInfo"):
            key = "notes" if action == "notesInfo" else "cards"
            store = self.notes if key == "notes" else self.cards
            out = []
            for raw in params.get(key) or []:
                item = store.get(int(raw))
                if item:
                    out.append({**item,
                                **({"fields": {k: dict(v) for k, v in
                                               item["fields"].items()}}
                                   if key == "notes" else {})})
                else:
                    out.append({})
            return out
        if action in ("getReviewsOfCards", "cardReviews"):
            return {str(c): self.reviews.get(int(c), [])
                    for c in params.get("cards") or []}
        if action == "updateNoteFields":
            note = params.get("note") or {}
            item = self.notes.get(int(note.get("id")))
            if not item:
                return None
            for name, value in (note.get("fields") or {}).items():
                if name in item["fields"]:
                    item["fields"][name]["value"] = str(value)
            return None
        if action == "addNotes":
            ids = []
            for note in params.get("notes") or []:
                ids.append(self.add(note["deckName"], note["modelName"],
                                    note.get("fields") or {}, note.get("tags")))
            return ids
        if action == "deleteNotes":
            for raw in params.get("notes") or []:
                item = self.notes.pop(int(raw), None)
                if item:
                    for cid in item["cards"]:
                        self.cards.pop(int(cid), None)
                        self.reviews.pop(int(cid), None)
            return None
        if action == "suspend":
            for raw in params.get("cards") or []:
                card = self.cards.get(int(raw))
                if card:
                    card["queue"] = -1
            return None
        if action == "unsuspend":
            for raw in params.get("cards") or []:
                card = self.cards.get(int(raw))
                if card:
                    card["queue"] = 2
            return None
        if action == "changeDeck":
            for raw in params.get("cards") or []:
                card = self.cards.get(int(raw))
                if card:
                    card["deckName"] = params.get("deck")
            return None
        if action == "setDueDate":
            for raw in params.get("cards") or []:
                card = self.cards.get(int(raw))
                if card:
                    card["due"] = int(str(params.get("days") or 0))
            return None
        if action == "storeMediaFile":
            name = params.get("filename")
            if params.get("path"):
                data = Path(params["path"]).read_bytes()
            else:
                import base64
                data = base64.b64decode(params.get("data") or "")
            self.media[name] = data
            return name
        if action == "retrieveMediaFile":
            import base64
            return base64.b64encode(self.media.get(params.get("filename"), b"")).decode()
        if action == "sync":
            return None
        raise ValueError(f"unsupported action {action}")


def serve(fake: FakeAnki):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                result = fake.handle(body.get("action"), body.get("params") or {})
                payload = {"result": result, "error": None}
            except Exception as e:
                payload = {"result": None, "error": str(e)}
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_port}"


def closed_url() -> str:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


def rev(args, url, env, expect=0):
    cmd = [sys.executable, str(SCRIPTS / "revision.py"), "--url", url, *args]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert r.returncode == expect, (r.returncode, r.stdout, r.stderr)
    return r


def live_note(fake: FakeAnki, card: dict, deck="SCHOOL::RTOS", review_score=2):
    front = render.to_html(card["front"])
    back = render.with_source(render.to_html(card["back"]),
                              card.get("source", ""),
                              card.get("source_url", ""))
    if card.get("cloze"):
        fields = {"Text": front, "Extra": back, "Layer": card["layer"],
                  "Topic": card["topic"], "Media": ""}
        model = "3-Layer STEM Cloze"
    else:
        fields = {"Front": front, "Back": back, "Layer": card["layer"],
                  "Topic": card["topic"], "Media": ""}
        model = "3-Layer STEM"
    return fake.add(deck, model, fields, tags=[card["topic"].replace(" ", "_")])


def make_work(td: Path, name: str, cards: list[dict]) -> Path:
    work = td / name
    work.mkdir()
    (work / "intake.md").write_text("# Intake\n\nsecond year\n")
    (work / "scope_gate.md").write_text("# Scope\n\nformula sheet given\n")
    (work / "authoring_ledger.md").write_text("# Ledger\n\n1. why\n")
    (work / "cards.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in cards))
    (work / "curated.json").write_text(json.dumps({
        "style": "# Style\n\n- heap_4\n",
        "learner": "# Learner\n\n- visual\n",
        "topics": {"Memory": {"takeaways": ["classes bound fragmentation"]}},
    }))
    return work


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        env = os.environ.copy()
        env["ANKI_GEN_DATA_HOME"] = str(td / "data")
        os.environ["ANKI_GEN_DATA_HOME"] = env["ANKI_GEN_DATA_HOME"]

        cards = [
            {"front": "Why does heap_4 bound fragmentation?",
             "back": "It keeps one free list per size class. **Why:** constant time.",
             "layer": "L2", "topic": "Memory", "objects": ["rtos"],
             "deck": "SCHOOL::RTOS", "source": "Lec 4 p.2", "review_score": 1},
            {"front": "What does heap_2 trade away?",
             "back": "Exact-fit reuse. **Why:** fixed classes waste space.",
             "layer": "L1", "topic": "Memory", "objects": [], "deck": "SCHOOL::RTOS",
             "source": "Lec 4 p.3", "review_score": 1},
            {"front": "What is a TLB?",
             "back": "A translation cache. **Why:** it avoids page walks.",
             "layer": "L1", "topic": "Memory", "objects": [], "deck": "SCHOOL::RTOS",
             "source": "Lec 4 p.9", "review_score": 1},
            {"front": "Which scheduler state is runnable?",
             "back": "Ready. **Why:** it can run but is not executing.",
             "layer": "L1", "topic": "Scheduling", "objects": [], "deck": "SCHOOL::RTOS",
             "source": "Lec 5 p.1", "review_score": 2},
            {"front": "Which scheduler state is running?",
             "back": "Running. **Why:** it owns the CPU.",
             "layer": "L2", "topic": "Scheduling", "objects": [], "deck": "SCHOOL::RTOS",
             "source": "Lec 5 p.2", "review_score": 2, "tier_zero": True},
            {"front": "The scheduler state is {{c1::ready}}.",
             "back": "It can run. **Why:** the scheduler chose it.",
             "layer": "L1", "topic": "Scheduling", "objects": [], "deck": "SCHOOL::RTOS",
             "source": "Lec 5 p.3", "review_score": 2, "cloze": True},
        ]
        work = make_work(td, "work", cards)
        packed = dc.pack(work, {"deck_name": "SCHOOL::RTOS", "profile": "User 1"})
        key = packed["key"]

        fake = FakeAnki()
        for card in cards:
            live_note(fake, card)
        server, url = serve(fake)
        try:
            # 1. No AnkiConnect: every live command fails with setup text.
            dead = closed_url()
            for args in (["attach", "--deck", "SCHOOL::RTOS"],
                         ["audit", "--deck", "SCHOOL::RTOS"],
                         ["plan", "--deck", "SCHOOL::RTOS", "--intent", "cull easiest"]):
                r = rev(args, dead, env, expect=2)
                assert "AnkiConnect is not reachable" in r.stderr, r.stderr
            print("ok    AnkiConnect unavailable fails attach/audit/plan")

            # 2. Attach maps note IDs and writes nothing to Anki.
            r = rev(["attach", "--deck", "SCHOOL::RTOS", "--json"], url, env)
            assert fake.writes() == [], fake.writes()
            states = [json.loads(x) for x in
                      (Path(packed["path"]) / "anki_state.jsonl").read_text().splitlines()]
            assert all(int(row["anki_note_id"]) in fake.notes for row in states), states
            assert json.loads(r.stdout)["matched"] == len(cards)
            print("ok    attach maps notes read-only")

            # 3. Audit is read-only.
            fake.calls.clear()
            r = rev(["audit", "--deck", "SCHOOL::RTOS", "--json"], url, env)
            report = json.loads(r.stdout)
            assert fake.writes() == [], fake.writes()
            assert report["matched"] == len(cards) and report["field_drift"] == [], report
            print("ok    audit is read-only")

            # 3b. A renamed deck re-associates through its live deck ID.
            fake.decks["SCHOOL::RTOS2"] = fake.decks.pop("SCHOOL::RTOS")
            for note in fake.notes.values():
                if note["deckName"] == "SCHOOL::RTOS":
                    note["deckName"] = "SCHOOL::RTOS2"
            r = rev(["audit", "--deck", "SCHOOL::RTOS2", "--json"], url, env)
            assert json.loads(r.stdout)["matched"] == len(cards)
            fake.decks["SCHOOL::RTOS"] = fake.decks.pop("SCHOOL::RTOS2")
            for note in fake.notes.values():
                if note["deckName"] == "SCHOOL::RTOS2":
                    note["deckName"] = "SCHOOL::RTOS"
            print("ok    renamed deck re-associates by deck ID")

            # 4. Ambiguity: one dossier card, two identical live notes.
            amb_cards = [{"front": "Why is this ambiguous?",
                          "back": "Two notes match. **Why:** same text.",
                          "layer": "L2", "topic": "Amb", "objects": [],
                          "deck": "AMB::DECK", "source": "Lec 1 p.1"}]
            amb_work = make_work(td, "amb", amb_cards)
            amb = dc.pack(amb_work, {"deck_name": "AMB::DECK"})
            live_note(fake, amb_cards[0], deck="AMB::DECK")
            live_note(fake, amb_cards[0], deck="AMB::DECK")
            before = len(fake.writes())
            r = rev(["attach", "--deck", "AMB::DECK"], url, env, expect=2)
            assert "ambiguous" in r.stderr.lower(), r.stderr
            assert len(fake.writes()) == before
            print("ok    attach asks on ambiguity")

            # 4b. Snapshot + one-command revert for field updates and deletes.
            rev_cards = [{"front": "Why is revert tested?",
                          "back": "So one command can undo a revision. **Why:** trust.",
                          "layer": "L2", "topic": "Revert", "objects": [],
                          "deck": "REVERT::DECK", "source": "Lec 1 p.4",
                          "review_score": 1}]
            rev_work = make_work(td, "revert", rev_cards)
            rev_pack = dc.pack(rev_work, {"deck_name": "REVERT::DECK"})
            rev_root = Path(rev_pack["path"])
            live_note(fake, rev_cards[0], deck="REVERT::DECK")
            rev(["attach", "--deck", "REVERT::DECK"], url, env)
            r = rev(["plan", "--deck", "REVERT::DECK", "--intent", "rewrite",
                     "--update-front", "Why is revert tested?=Why is undo tested?",
                     "--json"], url, env)
            p1 = json.loads(r.stdout)["plan"]
            rev(["apply", "--plan", p1, "--browser-closed"], url, env)
            log_path = sorted((rev_root / "revisions").glob("*/apply_log.json"),
                              key=lambda p: p.stat().st_mtime)[-1]
            first_log = json.loads(log_path.read_text())
            snap_meta = json.loads((rev_root / "snapshots" / first_log["snapshot_id"]
                                    / "snapshot.json").read_text())
            assert set(snap_meta) == {
                "schema", "snapshot_id", "created_at", "deck_key", "deck",
                "reason", "apkg", "note_count", "card_count", "apply_log",
                "reverted_by"}, snap_meta
            assert not {"notes", "cards", "revlog_counts"} & set(snap_meta)
            assert snap_meta["note_count"] == 1 and snap_meta["card_count"] == 1, snap_meta
            backup = json.loads((log_path.parent / "backup.json").read_text())
            assert backup["updated_notes"] and not backup.get("reviews"), backup
            assert len(backup["cards"]) == 1 and len(backup["state"]) == 1, backup
            note = next(n for n in fake.notes.values()
                        if "Why is undo tested?" in n["fields"].get("Front", {}).get("value", ""))
            r = rev(["revert", "--deck", "REVERT::DECK", "--last", "--yes",
                     "--browser-closed", "--json"], url, env)
            out = json.loads(r.stdout)
            assert out["verified"] and out["restored"] >= 1, out
            assert "Why is revert tested?" in fake.notes[note["noteId"]]["fields"]["Front"]["value"]
            r = rev(["snapshots", "--deck", "REVERT::DECK", "--json"], url, env)
            assert len(json.loads(r.stdout)) >= 2
            r = rev(["plan", "--deck", "REVERT::DECK", "--intent", "cull easiest",
                     "--json"], url, env)
            p2 = json.loads(r.stdout)["plan"]
            data2 = json.loads(Path(p2).read_text())
            gid2 = data2["destructive_groups"][0]["id"]
            deleted_id = note["noteId"]
            rev(["apply", "--plan", p2, "--choice", f"{gid2}=delete"], url, env)
            assert deleted_id not in fake.notes
            latest_log_path = sorted((rev_root / "revisions").glob("*/apply_log.json"),
                                     key=lambda p: p.stat().st_mtime)[-1]
            latest_log = json.loads(latest_log_path.read_text())
            delete_backup = json.loads((latest_log_path.parent / "backup.json").read_text())
            assert delete_backup["deleted_notes"], delete_backup
            assert delete_backup["suspended_cards"] == [], delete_backup
            r = rev(["revert", "--deck", "REVERT::DECK", "--last", "--yes",
                     "--browser-closed", "--json"], url, env)
            out = json.loads(r.stdout)
            assert out["verified"], out
            assert any("Why is revert tested?" in n["fields"].get("Front", {}).get("value", "")
                       for n in fake.notes.values()), out
            print("ok    slim snapshot, affected backup, and one-command revert")

            r = rev(["snapshots", "--deck", "REVERT::DECK", "--sizes",
                     "--warn-mb", "0", "--warn-count", "999", "--json"], url, env)
            sized = json.loads(r.stdout)
            assert sized["warn"] and sized["snapshot_count"] >= 2, sized
            assert sized["path"] == str(rev_root.resolve()), sized
            assert {"snapshots", "previews", "revisions", "resources"} <= set(sized["dirs"])
            assert all("bytes" in row and "note_count" in row
                       for row in sized["snapshots"]), sized
            assert "--delete" in sized["delete_command"] and "--yes" in sized["delete_command"]
            r = rev(["snapshots", "--deck", "REVERT::DECK", "--sizes",
                     "--warn-mb", "999999", "--warn-count", "0"], url, env)
            assert "warning:" in r.stderr and str(rev_root.resolve()) in r.stderr, r.stderr
            assert "--delete" in r.stderr and "--prune" in r.stderr, r.stderr

            rows = json.loads(rev(["snapshots", "--deck", "REVERT::DECK",
                                   "--json"], url, env).stdout)
            oldest = rows[0]["snapshot_id"]
            assert oldest != latest_log["snapshot_id"], rows
            r = rev(["snapshots", "--deck", "REVERT::DECK", "--delete",
                     oldest, "--yes", "--json"], url, env)
            deleted = json.loads(r.stdout)
            assert deleted["bytes"] > 0 and not deleted["warning"], deleted
            r = rev(["snapshots", "--deck", "REVERT::DECK", "--prune",
                     "--keep", "0", "--yes"], url, env, expect=2)
            assert "--force" in r.stderr, r.stderr
            r = rev(["snapshots", "--deck", "REVERT::DECK", "--delete",
                     latest_log["snapshot_id"], "--yes"], url, env, expect=2)
            assert "--force" in r.stderr, r.stderr
            r = rev(["snapshots", "--deck", "REVERT::DECK", "--delete",
                     "../escape", "--yes"], url, env, expect=2)
            assert "plain directory name" in r.stderr, r.stderr
            r = rev(["snapshots", "--deck", "REVERT::DECK", "--delete",
                     latest_log["snapshot_id"]], url, env, expect=2)
            assert "--yes" in r.stderr, r.stderr
            r = rev(["snapshots", "--deck", "REVERT::DECK", "--delete",
                     latest_log["snapshot_id"], "--yes", "--force", "--json"], url, env)
            deleted = json.loads(r.stdout)
            assert deleted["warning"] and deleted["bytes"] > 0, deleted
            r = rev(["snapshots", "--deck", "REVERT::DECK", "--prune",
                     "--keep", "99", "--yes", "--json"], url, env)
            assert json.loads(r.stdout)["deleted"] == []
            r = rev(["snapshots", "--deck", "REVERT::DECK", "--prune",
                     "--keep", "1", "--yes", "--json"], url, env)
            pruned = json.loads(r.stdout)
            assert len(pruned["kept"]) == 1 and pruned["bytes"] > 0, pruned
            r = rev(["snapshots", "--deck", "REVERT::DECK", "--json"], url, env)
            assert len(json.loads(r.stdout)) == 1
            print("ok    snapshot sizes, explicit delete/prune, and guards")

            # 5. Field update preserves note/card IDs, scheduling, and revlog.
            sched_note = next(n for n in fake.notes.values()
                              if "runnable" in n["fields"]["Front"]["value"])
            before_cards = {cid: dict(fake.cards[cid]) for cid in sched_note["cards"]}
            before_reviews = {cid: len(fake.reviews[cid]) for cid in sched_note["cards"]}
            r = rev(["plan", "--deck", "SCHOOL::RTOS", "--intent", "rewrite wording",
                     "--update-front",
                     "Which scheduler state is runnable?=Which scheduler state can run?",
                     "--json"], url, env)
            plan_path = json.loads(r.stdout)["plan"]
            r = rev(["apply", "--plan", plan_path], url, env, expect=2)
            assert "Browser" in r.stderr, r.stderr
            r = rev(["apply", "--plan", plan_path, "--browser-closed"], url, env)
            sched_note = fake.notes[sched_note["noteId"]]
            assert "can run" in sched_note["fields"]["Front"]["value"]
            assert sched_note["cards"] == list(before_cards)
            for cid in sched_note["cards"]:
                assert fake.cards[cid]["interval"] == before_cards[cid]["interval"]
                assert fake.cards[cid]["due"] == before_cards[cid]["due"]
                assert fake.cards[cid]["reps"] == before_cards[cid]["reps"]
                assert len(fake.reviews[cid]) == before_reviews[cid]
            assert "updateNoteFields" in fake.calls
            print("ok    field update preserves scheduling and revlog")

            # 6. A manual Anki edit wins over the proposed field update.
            r = rev(["plan", "--deck", "SCHOOL::RTOS", "--intent", "rewrite wording",
                     "--update-front",
                     "Which scheduler state is running?=Which state owns the CPU?",
                     "--json"], url, env)
            conflict_plan = json.loads(r.stdout)["plan"]
            running = next(n for n in fake.notes.values()
                           if "running" in n["fields"]["Front"]["value"].lower())
            fake.notes[running["noteId"]]["fields"]["Front"]["value"] = "<p>My edit</p>"
            r = rev(["apply", "--plan", conflict_plan, "--browser-closed"], url, env)
            assert "My edit" in fake.notes[running["noteId"]]["fields"]["Front"]["value"]
            logs = sorted((Path(packed["path"]) / "revisions").glob("*/apply_log.json"),
                          key=lambda p: p.stat().st_mtime)
            log = json.loads(logs[-1].read_text())
            assert log["conflicts"], log
            print("ok    manual Anki edit wins and is reported")

            # 7. Merge keeps the survivor's history; victim is suspended by choice.
            r = rev(["plan", "--deck", "SCHOOL::RTOS", "--intent", "merge the easiest",
                     "--merge-match", "heap_2", "--into",
                     "Which scheduler state is running?", "--json"], url, env)
            merge_plan = json.loads(r.stdout)["plan"]
            data = json.loads(Path(merge_plan).read_text())
            gid = data["destructive_groups"][0]["id"]
            survivor = next(n for n in fake.notes.values()
                            if "Running." in n["fields"]["Back"]["value"])
            victim = next(n for n in fake.notes.values()
                          if "heap_2" in n["fields"].get("Front", {}).get("value", ""))
            survivor_cards = {cid: dict(fake.cards[cid]) for cid in survivor["cards"]}
            r = rev(["apply", "--plan", merge_plan, "--browser-closed",
                     "--choice", f"{gid}=suspend"], url, env)
            assert victim["noteId"] in fake.notes
            assert all(fake.cards[cid]["queue"] == -1 for cid in victim["cards"])
            assert all(fake.cards[cid]["queue"] == survivor_cards[cid]["queue"]
                       for cid in survivor["cards"])
            print("ok    merge keeps survivor history and suspends the victim")

            # 8. Split keeps the existing history and adds new cards.
            heap = next(n for n in fake.notes.values()
                        if "heap_4" in n["fields"]["Front"]["value"])
            heap_cards = {cid: dict(fake.cards[cid]) for cid in heap["cards"]}
            r = rev(["plan", "--deck", "SCHOOL::RTOS", "--intent", "split the card",
                     "--split-match", "Why does heap_4 bound fragmentation?",
                     "--split-front", "What does heap_4 keep per size class?",
                     "--split-back", "One free list. **Why:** allocation is constant time.",
                     "--json"], url, env)
            split_plan = json.loads(r.stdout)["plan"]
            before_notes = len(fake.notes)
            r = rev(["apply", "--plan", split_plan, "--browser-closed"], url, env)
            assert len(fake.notes) == before_notes + 1
            assert all(fake.cards[cid]["interval"] == heap_cards[cid]["interval"]
                       for cid in heap["cards"])
            print("ok    split keeps the existing card's history")

            # 9. Cloze ordinal changes require explicit approval.
            cloze = next(n for n in fake.notes.values()
                         if "{{c1::ready}}" in n["fields"].get("Text", {}).get("value", ""))
            r = rev(["plan", "--deck", "SCHOOL::RTOS", "--intent", "rewrite wording",
                     "--update-front",
                     "{{c1::ready}}={{c1::runnable}} {{c2::scheduled}}",
                     "--json"], url, env)
            cloze_plan = json.loads(r.stdout)["plan"]
            before_text = fake.notes[cloze["noteId"]]["fields"]["Text"]["value"]
            r = rev(["apply", "--plan", cloze_plan, "--browser-closed"], url, env,
                    expect=2)
            assert "cloze ordinals" in r.stderr, r.stderr
            assert fake.notes[cloze["noteId"]]["fields"]["Text"]["value"] == before_text
            print("ok    cloze ordinal change is refused without approval")

            # 10. Destructive choices: none, keep, suspend, delete.
            r = rev(["plan", "--deck", "SCHOOL::RTOS",
                     "--intent", "cull the easiest cards score 1", "--json"], url, env)
            cull_plan = json.loads(r.stdout)["plan"]
            data = json.loads(Path(cull_plan).read_text())
            gid = data["destructive_groups"][0]["id"]
            cull_ids = [int(n) for n in data["destructive_groups"][0]["note_ids"]]
            md = Path(cull_plan).with_suffix(".md").read_text()
            for action in data["actions"]:
                assert str(action["note_id"]) not in md, md
            assert "Delete permanently / Suspend / Keep" in md, md
            before = len(fake.writes())
            r = rev(["apply", "--plan", cull_plan], url, env, expect=2)
            assert len(fake.writes()) == before
            r = rev(["apply", "--plan", cull_plan, "--choice", f"{gid}=keep"], url, env)
            assert "kept" in r.stdout
            r = rev(["apply", "--plan", cull_plan, "--choice", f"{gid}=suspend"], url, env)
            assert cull_ids and all(fake.cards[c]["queue"] == -1
                                    for nid in cull_ids for c in fake.notes[nid]["cards"])
            r = rev(["apply", "--plan", cull_plan, "--choice", f"{gid}=delete"], url, env)
            assert all(nid not in fake.notes for nid in cull_ids)
            backups = list((Path(packed["path"]) / "revisions").glob("*/backup.json"))
            assert backups, "destructive apply did not back up"
            print("ok    destructive apply requires delete/suspend/keep and backs up")

            # 11. Context archive roundtrip is local; attach can be re-run.
            archive = td / "context.zip"
            r = rev(["context", "export", "--deck", "SCHOOL::RTOS",
                     "--out", str(archive)], url, env)
            assert archive.is_file()
            r = rev(["context", "import", str(archive)], url, env)
            assert "dossier" in r.stdout
            print("ok    context export/import")

            # 12. No fallback surface is imported by the revision modules.
            for name in ("anki_connect.py", "revision.py"):
                text = (SCRIPTS / name).read_text()
                assert "import anki" not in text and "sqlite3" not in text, name
            print("ok    revision uses AnkiConnect only")

            plugin = td / "plugin.zip"
            with __import__("zipfile").ZipFile(plugin, "w") as z:
                z.writestr("anki-connect-test/plugin/__init__.py", "# test\n")
            base = td / "Anki2"
            base.mkdir()
            prior = os.environ.get("ANKI_GEN_ANKI2_DIR")
            os.environ["ANKI_GEN_ANKI2_DIR"] = str(base)
            try:
                info = anki_connect.detect()
                assert info["anki2"] == str(base) and info["addons21"].endswith("addons21")
                dest = anki_connect.install(str(plugin))
            finally:
                if prior is None:
                    os.environ.pop("ANKI_GEN_ANKI2_DIR", None)
                else:
                    os.environ["ANKI_GEN_ANKI2_DIR"] = prior
            assert dest == base / "addons21" / anki_connect.ADDON_CODE, dest
            assert (dest / "__init__.py").read_text() == "# test\n", dest
            print("ok    Anki detection and pinned installer copy only the plugin")
        finally:
            server.shutdown()
            server.server_close()

    print("\nPASS  revision hardening")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
