"""Dossier locations and the rebuildable deck index."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .model import now

FORMAT = "anki-gen.deck-index"
SCHEMA = 1


def data_root() -> Path:
    override = os.environ.get("ANKI_GEN_DATA_HOME")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base).expanduser() / "anki-gen"


def decks_root() -> Path:
    return data_root() / "decks"


def deck_dir(deck_uuid: str) -> Path:
    return decks_root() / deck_uuid


def index_path() -> Path:
    return decks_root() / "index.json"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(text)
    os.replace(tmp, path)


def read_index() -> dict:
    try:
        data = json.loads(index_path().read_text())
        if data.get("format") == FORMAT and isinstance(data.get("decks"), dict):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"format": FORMAT, "schema": SCHEMA, "decks": {}}


def write_index(index: dict) -> None:
    atomic_write(index_path(), json.dumps(index, indent=2) + "\n")


def rebuild_index() -> dict:
    index = {"format": FORMAT, "schema": SCHEMA, "decks": {}}
    root = decks_root()
    if not root.is_dir():
        return index
    for manifest_path in sorted(root.glob("*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        deck = manifest.get("deck") or {}
        uuid = str(deck.get("uuid") or manifest_path.parent.name)
        index["decks"][uuid] = {
            "deck_name": deck.get("name") or "",
            "aliases": list(deck.get("aliases") or []),
            "profile": deck.get("profile") or "",
            "deck_id": str(deck.get("anki_deck_id") or ""),
            "notetypes": list(deck.get("notetypes") or []),
            "updated_at": manifest.get("updated_at") or now(),
        }
    write_index(index)
    return index


def read_or_rebuild_index() -> dict:
    index = read_index()
    if index["decks"] or not decks_root().is_dir():
        return index
    return rebuild_index()


def register(deck_uuid: str, identity: dict,
             aliases: list[str] | None = None) -> None:
    index = read_or_rebuild_index()
    old = index["decks"].get(deck_uuid, {})
    name = identity.get("deck_name") or old.get("deck_name") or ""
    merged = sorted({*(old.get("aliases") or []), *(aliases or []),
                     old.get("deck_name") or ""} - {name})
    index["decks"][deck_uuid] = {
        "deck_name": name,
        "aliases": merged,
        "profile": identity.get("profile") or old.get("profile") or "",
        "deck_id": str(identity.get("deck_id") or old.get("deck_id") or ""),
        "notetypes": list(identity.get("notetypes") or old.get("notetypes") or []),
        "updated_at": now(),
    }
    write_index(index)


def resolve(selector: str | None = None) -> str | None:
    if not selector:
        keys = [k for k in read_or_rebuild_index()["decks"]
                if deck_dir(k).is_dir()]
        return keys[0] if len(keys) == 1 else None
    want = str(selector)
    index = read_or_rebuild_index()
    if want in index["decks"] and deck_dir(want).is_dir():
        return want
    low = want.casefold()
    matches = []
    for uuid, entry in index["decks"].items():
        names = [entry.get("deck_name", ""), *(entry.get("aliases") or [])]
        if any(str(n).casefold() == low for n in names):
            matches.append(uuid)
        elif entry.get("deck_id") and str(entry["deck_id"]) == want:
            matches.append(uuid)
    return matches[0] if len(matches) == 1 else None


def find_by_deck_id(deck_id: str) -> str | None:
    for uuid, entry in read_or_rebuild_index()["decks"].items():
        if entry.get("deck_id") and str(entry["deck_id"]) == str(deck_id):
            return uuid
    return None
