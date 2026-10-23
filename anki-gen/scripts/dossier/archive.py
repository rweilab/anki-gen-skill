"""Deterministic, verified dossier archives."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path

from . import index as idx
from .errors import ArchiveError, SchemaTooNew
from .manifest import sha256_file
from .model import ARCHIVE_FORMAT, APP_VERSION, SCHEMA, now
from .store import DossierStore

MAX_TOTAL = 200 * 1024 * 1024
MAX_FILE = 50 * 1024 * 1024
MAX_ENTRIES = 20000
FIXED_DATE = (1980, 1, 1, 0, 0, 0)


def _safe(name: str) -> bool:
    path = Path(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def export(selector: str, out_path, *, include_snapshots: bool = False) -> Path:
    uuid = idx.resolve(selector)
    if not uuid:
        raise FileNotFoundError(f"no dossier for {selector!r}")
    root = idx.deck_dir(uuid)
    out_path = Path(out_path).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    files = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel.startswith("snapshots/") and not include_snapshots:
            continue
        if rel == "_export.json":
            continue
        if path.stat().st_size > MAX_FILE:
            raise ArchiveError(f"file too large to export: {rel}")
        files.append({"path": rel, "sha256": sha256_file(path),
                      "bytes": path.stat().st_size})
    meta = {
        "format": ARCHIVE_FORMAT, "schema": 1, "dossier_schema": SCHEMA,
        "deck_uuid": uuid, "created_at": now(), "app_version": APP_VERSION,
        "files": files,
    }
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for entry in files:
            info = zipfile.ZipInfo(entry["path"], FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            z.writestr(info, (root / entry["path"]).read_bytes())
        info = zipfile.ZipInfo("_export.json", FIXED_DATE)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o600 << 16
        z.writestr(info, json.dumps(meta, indent=2) + "\n")
    os.replace(tmp, out_path)
    return out_path


def _verify(path: Path) -> tuple[dict, dict[str, bytes]]:
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        raise ArchiveError(f"not a readable zip: {e}") from e
    with z:
        names = z.namelist()
        if len(names) > MAX_ENTRIES:
            raise ArchiveError("archive has too many entries")
        if len(set(names)) != len(names):
            raise ArchiveError("archive has duplicate entries")
        for name in names:
            if not _safe(name):
                raise ArchiveError(f"unsafe archive path: {name}")
        if "_export.json" not in names:
            raise ArchiveError("archive is missing _export.json")
        try:
            meta = json.loads(z.read("_export.json"))
        except json.JSONDecodeError as e:
            raise ArchiveError("invalid _export.json") from e
        if meta.get("format") != ARCHIVE_FORMAT:
            raise ArchiveError("not an anki-gen dossier archive")
        found = int(meta.get("dossier_schema") or 0)
        if found > SCHEMA:
            raise SchemaTooNew(found, SCHEMA)
        if found != SCHEMA:
            raise ArchiveError("archive dossier schema is not supported")
        listed = {e["path"]: e for e in meta.get("files") or []}
        data = {}
        total = 0
        for name in names:
            if name == "_export.json":
                continue
            if name not in listed:
                raise ArchiveError(f"unlisted archive file: {name}")
            raw = z.read(name)
            total += len(raw)
            if total > MAX_TOTAL:
                raise ArchiveError("archive is too large")
            if len(raw) > MAX_FILE:
                raise ArchiveError(f"archive file too large: {name}")
            entry = listed[name]
            if len(raw) != entry.get("bytes"):
                raise ArchiveError(f"size mismatch: {name}")
            if hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
                raise ArchiveError(f"checksum mismatch: {name}")
            data[name] = raw
        return meta, data


def import_archive(path, *, dry_run: bool = False) -> dict:
    path = Path(path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(path)
    meta, data = _verify(path)
    if "manifest.json" not in data:
        raise ArchiveError("archive is missing manifest.json")
    manifest = json.loads(data["manifest.json"])
    uuid = str(meta.get("deck_uuid") or manifest.get("deck", {}).get("uuid") or "")
    if not uuid or not _safe(uuid):
        raise ArchiveError("archive has no valid deck UUID")
    if dry_run:
        return {"key": uuid, "files": len(data), "dry_run": True}
    store = DossierStore(uuid)
    backup = store.backup("import") if store.exists() else None
    with store.transaction() as stage:
        for item in list(stage.iterdir()):
            if item.name == "manifest.json":
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        for name, raw in data.items():
            if name == "manifest.json":
                continue
            dest = stage / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
        (stage / "manifest.json").write_bytes(data["manifest.json"])
    idx.register(uuid, {
        "deck_name": manifest.get("deck", {}).get("name", ""),
        "aliases": manifest.get("deck", {}).get("aliases") or [],
        "profile": manifest.get("deck", {}).get("profile", ""),
        "deck_id": manifest.get("deck", {}).get("anki_deck_id", ""),
        "notetypes": manifest.get("deck", {}).get("notetypes") or [],
    })
    return {"key": uuid, "path": str(store.path), "backup": str(backup or ""),
            "files": len(data)}
