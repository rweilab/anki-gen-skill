#!/usr/bin/env python3
"""Minimal AnkiConnect client for live deck attach, audit, and revision.

AnkiConnect is the only live Anki surface this skill uses. It is a local HTTP
JSON API served by the AnkiConnect add-on inside Anki Desktop, so every call
goes through Anki's own collection layer; nothing here writes SQLite directly.

If the add-on is not running there is no fallback: callers get
`AnkiConnectUnavailable` with the setup message and must exit nonzero. New
`.apkg` creation does not import this module.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_URL = "http://127.0.0.1:8765"
ADDON_CODE = "2055492159"
# The upstream add-on changed its schema in late 2026 and broke many clients.
# Pin a known-good commit instead of installing whatever master contains.
PINNED_COMMIT = "de6e6e1b8aaf4ae195eb1d1ff6db5409b99b2a3e"
REQUIRED_ACTIONS = (
    "version", "findNotes", "findCards", "notesInfo", "cardsInfo",
    "updateNoteFields", "addNotes", "deleteNotes",
    "suspend", "unsuspend", "exportPackage", "importPackage",
    "getMediaDirPath",
)
SETUP = ("anki-gen: AnkiConnect is not reachable at {url}. Open Anki Desktop, "
         "enable the AnkiConnect add-on (code " + ADDON_CODE + "), wait for the "
         "main window, then retry. Do not inspect or edit collection.anki2.")


class AnkiConnectError(RuntimeError):
    """The server answered, but the action failed."""


class AnkiConnectUnavailable(AnkiConnectError):
    """No usable AnkiConnect endpoint; callers must stop, not fall back."""


class AnkiConnect:
    def __init__(self, url: str | None = None, timeout: float = 10.0,
                 retries: int = 1):
        self.url = (url or os.environ.get("ANKI_GEN_ANKI_CONNECT_URL")
                    or DEFAULT_URL).rstrip("/")
        self.timeout = timeout
        self.retries = max(0, retries)

    def request(self, action: str, timeout: float | None = None, **params):
        payload = json.dumps({"action": action, "version": 6,
                              "params": params}).encode()
        req = Request(self.url, data=payload, method="POST",
                      headers={"Content-Type": "application/json"})
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urlopen(req, timeout=timeout or self.timeout) as resp:
                    body = json.loads(resp.read().decode() or "{}")
                break
            except HTTPError as e:
                # AnkiConnect returns an error envelope with HTTP 200; an HTTP
                # code means the endpoint itself is wrong, so do not retry it.
                raise AnkiConnectError(f"AnkiConnect HTTP {e.code} at {self.url}") from e
            except (URLError, TimeoutError, socket.timeout, OSError,
                    json.JSONDecodeError) as e:
                last = e
                if attempt >= self.retries:
                    raise AnkiConnectUnavailable(
                        SETUP.format(url=self.url)) from e
        else:                                  # pragma: no cover - loop always breaks/raises
            raise AnkiConnectUnavailable(SETUP.format(url=self.url)) from last

        if body.get("error"):
            raise AnkiConnectError(f"AnkiConnect {action}: {body['error']}")
        return body.get("result")

    def ensure_available(self) -> int | str:
        """Short health check. Raises with the setup message, never falls back."""
        try:
            return self.request("version", timeout=2.0)
        except AnkiConnectError as e:
            if isinstance(e, AnkiConnectUnavailable):
                raise
            raise AnkiConnectUnavailable(SETUP.format(url=self.url)) from e

    def ensure_compatible(self, actions=REQUIRED_ACTIONS) -> None:
        """Fail early when this AnkiConnect build lacks an action we need."""
        try:
            result = self.request("apiReflect", scopes=["actions"],
                                  actions=list(actions))
        except AnkiConnectError:
            return                       # older builds have no apiReflect
        known = set((result or {}).get("actions") or [])
        missing = [action for action in actions if action not in known]
        if missing:
            raise AnkiConnectUnavailable(
                "anki-gen: this AnkiConnect build is missing "
                f"{', '.join(missing)}. Install the pinned add-on with "
                "`python3 scripts/anki_connect.py --install --yes`, then "
                "restart Anki.")

    # -- read-only -----------------------------------------------------
    def find_notes(self, query: str) -> list[int]:
        return list(self.request("findNotes", query=query) or [])

    def find_cards(self, query: str) -> list[int]:
        return list(self.request("findCards", query=query) or [])

    def notes_info(self, note_ids) -> list[dict]:
        return list(self.request("notesInfo", notes=[int(i) for i in note_ids]) or [])

    def cards_info(self, card_ids) -> list[dict]:
        return list(self.request("cardsInfo", cards=[int(i) for i in card_ids]) or [])

    def deck_names_and_ids(self) -> dict:
        return dict(self.request("deckNamesAndIds") or {})

    def get_reviews_of_cards(self, card_ids) -> dict:
        try:
            return dict(self.request(
                "getReviewsOfCards", cards=[int(i) for i in card_ids]) or {})
        except AnkiConnectError:
            # Older AnkiConnect builds have cardReviews instead. A missing
            # review history is not a reason to skip verification; callers get
            # an empty map and report revlog as unverified.
            try:
                return dict(self.request(
                    "cardReviews", cards=[int(i) for i in card_ids]) or {})
            except AnkiConnectError:
                return {}

    # -- writes --------------------------------------------------------
    def update_note_fields(self, note_id: int, fields: dict):
        return self.request("updateNoteFields",
                            note={"id": int(note_id), "fields": fields})

    def add_notes(self, notes: list[dict]) -> list:
        return list(self.request("addNotes", notes=notes) or [])

    def delete_notes(self, note_ids):
        return self.request("deleteNotes", notes=[int(i) for i in note_ids])

    def add_tags(self, note_ids, tags):
        tags = " ".join(str(t) for t in tags if str(t).strip())
        if tags:
            return self.request("addTags", notes=[int(i) for i in note_ids],
                                tags=tags)

    def remove_tags(self, note_ids, tags):
        tags = " ".join(str(t) for t in tags if str(t).strip())
        if tags:
            return self.request("removeTags", notes=[int(i) for i in note_ids],
                                tags=tags)

    def suspend(self, card_ids):
        return self.request("suspend", cards=[int(i) for i in card_ids])

    def unsuspend(self, card_ids):
        return self.request("unsuspend", cards=[int(i) for i in card_ids])

    def get_media_dir_path(self) -> str:
        return str(self.request("getMediaDirPath") or "")

    def export_package(self, deck: str, path: str | Path,
                       include_sched: bool = True) -> bool:
        return bool(self.request("exportPackage", deck=deck, path=str(path),
                                 includeSched=bool(include_sched)))

    def import_package(self, path: str | Path) -> bool:
        return bool(self.request("importPackage", path=str(path)))

    def store_media_file(self, filename: str, path: str | Path | None = None,
                         data: bytes | None = None) -> str:
        params: dict = {"filename": filename}
        if path is not None:
            params["path"] = str(path)
        elif data is not None:
            params["data"] = base64.b64encode(data).decode()
        else:
            raise ValueError("store_media_file needs path or data")
        return str(self.request("storeMediaFile", **params))

    def sync(self):
        return self.request("sync")


def anki2_candidates() -> list[Path]:
    """Likely Anki profile roots, in preference order."""
    override = os.environ.get("ANKI_GEN_ANKI2_DIR")
    if override:
        return [Path(override).expanduser()]
    home = Path.home()
    if sys.platform == "darwin":
        return [home / "Library" / "Application Support" / "Anki2"]
    if sys.platform.startswith("win"):
        return [Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
                / "Anki2"]
    base = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
    return [base / "Anki2",
            home / ".var" / "app" / "net.ankiweb.Anki" / "data" / "Anki2"]


def find_anki2() -> Path | None:
    bases = anki2_candidates()
    for base in bases:
        if ((base / "collection.anki2").is_file()
                or (base / "collection.anki21").is_file()
                or (base / "addons21").is_dir()):
            return base
    return next((base for base in bases if base.is_dir()), None)


def anki_binary() -> str:
    found = shutil.which("anki")
    if found:
        return found
    home = Path.home()
    if sys.platform == "darwin":
        paths = [Path("/Applications/Anki.app"),
                 home / "Applications" / "Anki.app"]
    elif sys.platform.startswith("win"):
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        paths = [local / "Programs" / "Anki" / "anki.exe",
                 Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
                 / "Anki" / "anki.exe"]
    else:
        paths = [Path("/usr/bin/anki"), Path("/usr/local/bin/anki"),
                 home / ".local" / "bin" / "anki"]
    return str(next((p for p in paths if p.exists()), ""))


def detect() -> dict:
    base = find_anki2()
    return {
        "anki2": str(base) if base else "",
        "addons21": str(base / "addons21") if base else "",
        "binary": anki_binary(),
        "candidates": [str(path) for path in anki2_candidates()],
    }


def addons_dir(*, create: bool = False) -> Path:
    """Locate Anki's add-ons directory on Linux, macOS, Windows, or Flatpak."""
    base = find_anki2()
    if not base:
        message = ("Anki profile not found. Open Anki once so it creates its "
                   "profile, or pass --addons-dir. Checked: "
                   + ", ".join(str(p) for p in anki2_candidates()))
        if create:
            raise FileNotFoundError(message)
        return anki2_candidates()[0] / "addons21"
    path = base / "addons21"
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def install(source: str | None = None, addons: str | Path | None = None) -> Path:
    """Install a pinned AnkiConnect plugin without touching the collection."""
    dest = (Path(addons).expanduser() if addons
            else addons_dir(create=True) / ADDON_CODE)
    archive = Path(source).expanduser() if source else None
    tmp = None
    try:
        if archive is None:
            fd, name = tempfile.mkstemp(suffix=".zip")
            os.close(fd)
            tmp = Path(name)
            url = (f"https://github.com/FooSoft/anki-connect/archive/"
                   f"{PINNED_COMMIT}.zip")
            with urlopen(url, timeout=60) as response:
                tmp.write_bytes(response.read())
            archive = tmp
        with zipfile.ZipFile(archive) as z:
            prefix = next((name.split("plugin/", 1)[0] + "plugin/"
                           for name in z.namelist()
                           if name.endswith("/plugin/__init__.py")), "")
            if not prefix:
                raise ValueError("archive does not contain an AnkiConnect plugin")
            dest.mkdir(parents=True, exist_ok=True)
            for name in z.namelist():
                if not name.startswith(prefix):
                    continue
                rel = name[len(prefix):]
                if not rel or rel.endswith("/") or ".." in Path(rel).parts:
                    continue
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(name))
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)
    return dest


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Check the local AnkiConnect bridge.")
    ap.add_argument("--url", default=None)
    ap.add_argument("--detect", action="store_true",
                    help="locate Anki's profile, add-ons, and binary")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--install", action="store_true",
                    help="install the pinned AnkiConnect add-on")
    ap.add_argument("--yes", action="store_true",
                    help="confirm add-on installation")
    ap.add_argument("--source", default=None,
                    help="local AnkiConnect plugin zip")
    ap.add_argument("--addons-dir", default=None,
                    help="override Anki's addons21 directory")
    args = ap.parse_args(argv)
    if args.detect:
        info = detect()
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            print(f"Anki profile: {info['anki2'] or 'not found'}")
            print(f"Add-ons:      {info['addons21'] or 'not found'}")
            print(f"Anki binary:  {info['binary'] or 'not found on PATH/app dirs'}")
        return 0 if info["anki2"] else 1
    if args.install:
        if not args.yes:
            print("anki_connect.py: installation needs --yes after user consent",
                  file=sys.stderr)
            return 2
        try:
            dest = install(args.source, args.addons_dir)
        except Exception as e:
            print(f"anki_connect.py: install failed: {e}", file=sys.stderr)
            return 2
        print(f"installed AnkiConnect {ADDON_CODE} -> {dest}")
        print("restart Anki, then run: python3 scripts/anki_connect.py")
        return 0
    try:
        ac = AnkiConnect(args.url)
        version = ac.ensure_available()
        ac.ensure_compatible()
    except AnkiConnectError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"AnkiConnect {version} at {args.url or DEFAULT_URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
