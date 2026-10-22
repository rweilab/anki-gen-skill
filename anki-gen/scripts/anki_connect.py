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
import socket
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_URL = "http://127.0.0.1:8765"
SETUP = ("anki-gen: AnkiConnect is not reachable at {url}. Open Anki with the "
         "AnkiConnect add-on, then retry.")


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

    # -- read-only -----------------------------------------------------
    def find_notes(self, query: str) -> list[int]:
        return list(self.request("findNotes", query=query) or [])

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

    def suspend(self, card_ids):
        return self.request("suspend", cards=[int(i) for i in card_ids])

    def unsuspend(self, card_ids):
        return self.request("unsuspend", cards=[int(i) for i in card_ids])

    def change_deck(self, card_ids, deck: str):
        return self.request("changeDeck", cards=[int(i) for i in card_ids],
                            deck=deck)

    def set_due_date(self, card_ids, days: str):
        return self.request("setDueDate", cards=[int(i) for i in card_ids],
                            days=str(days))

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

    def retrieve_media_file(self, filename: str) -> bytes:
        encoded = self.request("retrieveMediaFile", filename=filename) or ""
        return base64.b64decode(encoded)

    def sync(self):
        return self.request("sync")


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Check the local AnkiConnect bridge.")
    ap.add_argument("--url", default=None)
    args = ap.parse_args(argv)
    try:
        version = AnkiConnect(args.url).ensure_available()
    except AnkiConnectError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"AnkiConnect {version} at {args.url or DEFAULT_URL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
