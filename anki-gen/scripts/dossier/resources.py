"""Generic resource storage for media, notes, datasets, and future artifacts.

`resources.jsonl` is an open index: `kind` and `role` are strings, unknown
fields are preserved under `extra`, and any file type can live under
`resources/`. Nothing in the core schema assumes only images.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import packer
from .manifest import file_table, sha256_file
from .model import FILE_SCHEMAS, RESOURCE_KEYS, new_uuid, now, preserve_extra
from .store import DossierStore, write_json, write_jsonl


def _safe_name(name: str) -> str:
    stem = Path(name).stem or "resource"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-.") or "resource"
    suffix = Path(name).suffix[:16]
    return f"{stem[:72]}{suffix}"


def list_resources(selector: str) -> list[dict]:
    context = packer.load(selector)
    if not context:
        raise FileNotFoundError(f"no dossier for {selector!r}")
    return list(context.get("resources") or [])


def add(selector: str, source_path, *, kind: str = "other",
        role: str = "reference", name: str = "",
        metadata: dict | None = None) -> dict:
    context = packer.load(selector)
    if not context:
        raise FileNotFoundError(f"no dossier for {selector!r}")
    source = Path(source_path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(source)
    resource_id = new_uuid()
    filename = f"{resource_id}_{_safe_name(name or source.name)}"
    rel = f"resources/{filename}"
    digest = sha256_file(source)
    row = {
        "resource_id": resource_id, "kind": str(kind or "other"),
        "role": str(role or "reference"), "name": name or source.name,
        "path": rel, "sha256": digest, "bytes": source.stat().st_size,
        "schema": 1, "metadata": dict(metadata or {}), "extra": {},
    }
    preserve_extra(row, row, RESOURCE_KEYS)
    store = DossierStore(context["uuid"])
    with store.transaction() as stage:
        dest = stage / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        dest.write_bytes(source.read_bytes())
        rows = list(context.get("resources") or []) + [row]
        write_jsonl(stage / "resources.jsonl", rows)
        manifest = json.loads((stage / "manifest.json").read_text())
        manifest["files"] = file_table(stage, FILE_SCHEMAS)
        manifest["counts"]["resources"] = len(rows)
        manifest["updated_at"] = now()
        write_json(stage / "manifest.json", manifest)
    return row


def path(selector: str, resource_id: str) -> Path:
    context = packer.load(selector)
    row = next((r for r in (context or {}).get("resources") or []
                if r.get("resource_id") == resource_id), None)
    if not row:
        raise FileNotFoundError(f"resource not found: {resource_id}")
    return Path(context["path"]) / row["path"]
