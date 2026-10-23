"""AnkiConnect deck snapshots, size reporting, and explicit retention."""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import deck_context as dc
from anki_connect import AnkiConnect, AnkiConnectError
from dossier.store import write_json

from .common import PlanError, deck_query

DEFAULT_WARN_BYTES = 256 * 1024 * 1024
DEFAULT_WARN_COUNT = 16


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _tree_bytes(path: Path) -> int:
    try:
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    except OSError:
        return 0


def _dirs(context: dict) -> list[Path]:
    root = dc.snapshots_dir(context["uuid"])
    return sorted((p for p in root.iterdir()
                   if p.is_dir() and not p.is_symlink()), key=lambda p: p.name)


def create(ac: AnkiConnect, context: dict, deck_name: str,
           reason: str) -> dict:
    snap_id = f"{_stamp()}-{uuid.uuid4().hex[:8]}"
    root = dc.snapshots_dir(context["uuid"]) / snap_id
    root.mkdir(parents=True, exist_ok=False)
    try:
        apkg = root / "deck.apkg"
        ac.export_package(deck_name, apkg, include_sched=True)
        if not apkg.is_file() or apkg.stat().st_size == 0:
            raise AnkiConnectError(
                "AnkiConnect exportPackage did not write a package")
        note_count = len(ac.find_notes(deck_query(deck_name)))
        card_count = len(ac.find_cards(deck_query(deck_name)))
        data = {
            "schema": 1, "snapshot_id": snap_id, "created_at": dc.now(),
            "deck_key": context["uuid"], "deck": deck_name, "reason": reason,
            "apkg": "deck.apkg", "note_count": note_count,
            "card_count": card_count, "apply_log": "", "reverted_by": "",
        }
        write_json(root / "snapshot.json", data)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return {"snapshot_id": snap_id, "path": str(root), "notes": note_count,
            "cards": card_count}


def load(context: dict, snapshot_id: str = "latest") -> dict:
    root = dc.snapshots_dir(context["uuid"])
    if snapshot_id in ("latest", "last", ""):
        dirs = [p for p in _dirs(context) if (p / "snapshot.json").is_file()]
        if not dirs:
            raise FileNotFoundError("no snapshots for this deck")
        directory = dirs[-1]
    else:
        directory = root / snapshot_id
    path = directory / "snapshot.json"
    if not path.is_file():
        raise FileNotFoundError(f"snapshot not found: {snapshot_id}")
    data = json.loads(path.read_text())
    data["_dir"] = str(directory)
    return data


def mark_apply(snapshot: dict, apply_log: str) -> None:
    path = Path(snapshot["_dir"]) / "snapshot.json"
    data = json.loads(path.read_text())
    data["apply_log"] = apply_log
    write_json(path, data)


def list_snapshots(context: dict) -> list[dict]:
    out = []
    for path in _dirs(context):
        try:
            data = json.loads((path / "snapshot.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
        out.append({
            "snapshot_id": data.get("snapshot_id", path.name),
            "created_at": data.get("created_at", ""),
            "reason": data.get("reason", ""),
            "note_count": int(data.get("note_count")
                              or len(data.get("notes") or [])),
            "card_count": int(data.get("card_count")
                              or len(data.get("cards") or [])),
            "bytes": _tree_bytes(path),
            "apply_log": data.get("apply_log", ""),
            "reverted_by": data.get("reverted_by", ""),
        })
    return out


def latest_apply_snapshot(context: dict) -> str:
    root = Path(context["path"]) / "revisions"
    logs = sorted(root.glob("*/apply_log.json"),
                  key=lambda p: p.stat().st_mtime)
    for path in reversed(logs):
        try:
            log = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if log.get("snapshot_id"):
            return str(log["snapshot_id"])
    return ""


def _size_mb(value: int) -> str:
    return f"{value / (1024 * 1024):.1f} MB"


def sizes(context: dict, *, warn_mb: int = DEFAULT_WARN_BYTES // (1024 * 1024),
          warn_count: int = DEFAULT_WARN_COUNT) -> dict:
    if warn_mb < 0 or warn_count < 0:
        raise PlanError("--warn-mb and --warn-count cannot be negative")
    root = Path(context["path"]).resolve()
    dirs = {name: _tree_bytes(root / rel) for name, rel in (
        ("snapshots", "snapshots"), ("previews", "thumbnails"),
        ("revisions", "revisions"), ("resources", "resources"))}
    rows = list_snapshots(context)
    total = _tree_bytes(root)
    warn_bytes = int(warn_mb) * 1024 * 1024
    warn = total > warn_bytes or len(rows) > int(warn_count)
    deck = str((context.get("manifest") or {}).get("deck", {}).get("name") or "")
    largest = max(rows, key=lambda row: row["bytes"], default=None)
    delete_command = (
        f'python3 scripts/revision.py snapshots --deck "{deck}" '
        f'--delete {largest["snapshot_id"]} --yes' if largest else "")
    prune_command = (
        f'python3 scripts/revision.py snapshots --deck "{deck}" '
        f'--prune --keep 1 --yes' if rows else "")
    warning = ""
    if warn:
        parts = [f"deck dossier is {_size_mb(total)} with {len(rows)} snapshot(s) "
                 f"at {root} (thresholds: {warn_mb} MB or {warn_count} snapshots)"]
        if delete_command:
            parts.append(f"delete one: {delete_command}")
        if prune_command:
            parts.append(f"prune: {prune_command}")
        warning = "; ".join(parts)
    return {
        "deck_key": context["uuid"], "deck": deck, "path": str(root),
        "total_bytes": total, "dirs": dirs, "snapshot_count": len(rows),
        "warn_bytes": warn_bytes, "warn_count": int(warn_count),
        "warn": warn, "warning": warning, "delete_command": delete_command,
        "prune_command": prune_command, "snapshots": rows,
    }


def _valid_id(snapshot_id: str) -> bool:
    return (bool(snapshot_id) and snapshot_id not in (".", "..")
            and Path(snapshot_id).name == snapshot_id
            and "/" not in snapshot_id and "\\" not in snapshot_id)


def delete(context: dict, snapshot_id: str, *, force: bool = False) -> dict:
    if not _valid_id(snapshot_id):
        raise PlanError("snapshot id must be a plain directory name")
    directory = dc.snapshots_dir(context["uuid"]) / snapshot_id
    if directory.is_symlink() or not (directory / "snapshot.json").is_file():
        raise FileNotFoundError(f"snapshot not found: {snapshot_id}")
    warning = ""
    if snapshot_id == latest_apply_snapshot(context):
        warning = (f"snapshot {snapshot_id} is the easy-revert target for the "
                   "latest apply")
        if not force:
            raise PlanError(warning + "; pass --force to delete it")
    freed = _tree_bytes(directory)
    shutil.rmtree(directory)
    return {"snapshot_id": snapshot_id, "bytes": freed, "warning": warning}


def prune(context: dict, keep: int, *, force: bool = False) -> dict:
    if keep < 0:
        raise PlanError("--keep must be zero or greater")
    dirs = [p for p in _dirs(context) if (p / "snapshot.json").is_file()]
    targets = dirs[:-keep] if keep else list(dirs)
    latest = latest_apply_snapshot(context)
    warning = ""
    if latest and latest in {p.name for p in targets}:
        warning = (f"snapshot {latest} is the easy-revert target for the latest "
                   "apply")
        if not force:
            raise PlanError(warning + "; pass --force to prune it")
    deleted, freed = [], 0
    for path in targets:
        freed += _tree_bytes(path)
        shutil.rmtree(path)
        deleted.append(path.name)
    return {"deleted": deleted, "bytes": freed,
            "kept": [p.name for p in dirs if p.name not in set(deleted)],
            "warning": warning}
