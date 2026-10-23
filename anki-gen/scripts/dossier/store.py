"""Transactional dossier storage with a POSIX advisory lock.

The live dossier is never written in place. A transaction hard-links the last
complete tree into a staging directory, writes there, fsyncs, and swaps the
directory in. If the process dies mid-swap, the next open restores the previous
or staging tree.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import time
from pathlib import Path

from . import index as idx
from .errors import DossierCorrupt, DossierLocked, SchemaTooNew
from .model import SCHEMA, now
from .manifest import verify

LOCK_STALE_SECONDS = 120


def _read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    try:
        text = path.read_text()
    except OSError:
        return rows
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            raise DossierCorrupt(f"invalid JSONL line in {path.name}",
                                 "Restore the dossier from backups/ or re-pack.")
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _read_text(path: Path) -> str:
    try:
        return path.read_text()
    except OSError:
        return ""


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    os.replace(tmp, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(text.rstrip() + "\n")
    os.replace(tmp, path)


def _fsync_tree(root: Path) -> None:
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        with path.open("rb") as f:
            os.fsync(f.fileno())
    fd = os.open(root, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _copy_or_link(src: str, dst: str) -> str:
    try:
        os.link(src, dst)
        return dst
    except OSError:
        shutil.copy2(src, dst)
        return dst


class DossierStore:
    def __init__(self, deck_uuid: str):
        self.uuid = deck_uuid
        self.path = idx.deck_dir(deck_uuid)
        self.lock_path = idx.decks_root() / f".{deck_uuid}.lock"
        self.stage_path = idx.decks_root() / f".{deck_uuid}.stage"
        self.prev_path = idx.decks_root() / f".{deck_uuid}.prev"

    def exists(self) -> bool:
        return (self.path / "manifest.json").is_file()

    @contextlib.contextmanager
    def _lock(self):
        idx.decks_root().mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(self.lock_path,
                             os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(fd, f"{os.getpid()} {time.time()}".encode())
                os.close(fd)
                break
            except FileExistsError:
                try:
                    age = time.time() - self.lock_path.stat().st_mtime
                except OSError:
                    continue
                if age > LOCK_STALE_SECONDS:
                    try:
                        self.lock_path.unlink()
                    except OSError:
                        pass
                    continue
                raise DossierLocked(str(self.lock_path))
        try:
            yield
        finally:
            try:
                self.lock_path.unlink()
            except OSError:
                pass

    def _recover_locked(self) -> None:
        if not self.path.exists():
            if (self.stage_path / "manifest.json").is_file():
                os.replace(self.stage_path, self.path)
            elif (self.prev_path / "manifest.json").is_file():
                os.replace(self.prev_path, self.path)
        if self.path.exists():
            shutil.rmtree(self.stage_path, ignore_errors=True)
            shutil.rmtree(self.prev_path, ignore_errors=True)
        else:
            shutil.rmtree(self.stage_path, ignore_errors=True)

    def read(self, verify_files: bool = False) -> dict:
        with self._lock():
            self._recover_locked()
            if not self.exists():
                raise DossierCorrupt(f"dossier not found: {self.path}",
                                     "Run context pack or import a dossier.")
            manifest = _read_json(self.path / "manifest.json", {}) or {}
            schema = manifest.get("schema")
            if schema is None:
                raise DossierCorrupt("manifest has no schema")
            if int(schema) > SCHEMA:
                raise SchemaTooNew(int(schema), SCHEMA)
            if int(schema) < SCHEMA:
                raise DossierCorrupt(
                    f"unsupported old schema {schema}",
                    "This build supports dossier schema 1 only; re-pack the dossier.")
            if verify_files:
                problems = verify(self.path, manifest)
                if problems:
                    raise DossierCorrupt("; ".join(problems[:5]),
                                         "Restore from backups/ or re-pack.")
            return {
                "uuid": self.uuid,
                "path": self.path,
                "manifest": manifest,
                "cards": _read_jsonl(self.path / "cards.jsonl"),
                "state": _read_jsonl(self.path / "anki_state.jsonl"),
                "topics": _read_jsonl(self.path / "topics.jsonl"),
                "sources": _read_jsonl(self.path / "sources.jsonl"),
                "media_candidates": _read_jsonl(self.path / "media_candidates.jsonl"),
                "resources": _read_jsonl(self.path / "resources.jsonl"),
                "preferences": _read_json(self.path / "preferences.json", {}) or {},
                "notation": _read_json(self.path / "notation.json", {}) or {},
                "style": _read_text(self.path / "style.md"),
                "learner": _read_text(self.path / "learner.md"),
                "decisions": _read_text(self.path / "decisions.md"),
                "future": _read_text(self.path / "future_work.md"),
                "deck_context": _read_text(self.path / "deck_context.md"),
            }

    def backup(self, reason: str = "backup") -> Path:
        stamp = now().replace(":", "").replace("-", "").replace("+", "")
        target = idx.data_root() / "backups" / f"{self.uuid}-{reason}-{stamp}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.path, target)
        return target

    @contextlib.contextmanager
    def transaction(self):
        with self._lock():
            self._recover_locked()
            if self.exists():
                shutil.rmtree(self.stage_path, ignore_errors=True)
                shutil.copytree(self.path, self.stage_path,
                                copy_function=_copy_or_link)
            else:
                self.stage_path.mkdir(parents=True, exist_ok=True)
            try:
                yield self.stage_path
                if not (self.stage_path / "manifest.json").is_file():
                    raise DossierCorrupt("transaction did not write manifest.json")
                _fsync_tree(self.stage_path)
                shutil.rmtree(self.prev_path, ignore_errors=True)
                if self.path.exists():
                    os.replace(self.path, self.prev_path)
                try:
                    os.replace(self.stage_path, self.path)
                except Exception:
                    if self.prev_path.exists() and not self.path.exists():
                        os.replace(self.prev_path, self.path)
                    raise
                shutil.rmtree(self.prev_path, ignore_errors=True)
            finally:
                shutil.rmtree(self.stage_path, ignore_errors=True)
