"""Manifest envelope, file table, and checksum verification."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .model import APP_VERSION, FORMAT, SCHEMA, now

EXCLUDED_DIRS = {"revisions", "snapshots"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def file_table(root: Path, schemas: dict[str, tuple[str, int]] | None = None) -> dict:
    table = {}
    schemas = schemas or {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel == "manifest.json" or rel.split("/", 1)[0] in EXCLUDED_DIRS:
            continue
        if rel.endswith(".tmp") or ".tmp-" in path.name:
            continue
        role, schema = schemas.get(rel, ("file", 1))
        table[rel] = {
            "role": role,
            "schema": schema,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    return table


def build(uuid: str, deck: dict, files: dict, counts: dict, *,
          created_at: str = "", confidence: str = "authored",
          migrations: list | None = None, extensions: dict | None = None) -> dict:
    return {
        "format": FORMAT,
        "schema": SCHEMA,
        "min_reader_schema": SCHEMA,
        "app_version": APP_VERSION,
        "deck": {
            "uuid": uuid,
            "anki_deck_id": str(deck.get("deck_id") or ""),
            "name": str(deck.get("deck_name") or deck.get("name") or ""),
            "aliases": list(deck.get("aliases") or []),
            "profile": str(deck.get("profile") or ""),
            "notetypes": list(deck.get("notetypes") or []),
        },
        "features": ["cards.identity.v1", "state.split.v1",
                     "media.preview.adaptive.v1", "resources.v1"],
        "files": files,
        "counts": counts,
        "created_at": created_at or now(),
        "updated_at": now(),
        "confidence": confidence,
        "migrations": list(migrations or []),
        "extensions": dict(extensions or {}),
    }


def verify(root: Path, manifest: dict) -> list[str]:
    problems = []
    for rel, entry in (manifest.get("files") or {}).items():
        path = root / rel
        if not path.is_file():
            problems.append(f"missing file: {rel}")
            continue
        if path.stat().st_size != entry.get("bytes"):
            problems.append(f"size changed: {rel}")
        if sha256_file(path) != entry.get("sha256"):
            problems.append(f"checksum changed: {rel}")
    return problems
