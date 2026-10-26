"""Record shapes and pure helpers for the deck dossier.

The on-disk form is JSON/JSONL. These helpers keep identity, text matching, and
unknown-field preservation in one place so a future schema change has one home.
"""
from __future__ import annotations

import html
import hashlib
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

SCHEMA = 1
FORMAT = "anki-gen.deck-dossier"
ARCHIVE_FORMAT = "anki-gen.dossier-archive"
FILE_SCHEMAS = {
    "cards.jsonl": ("cards", 1),
    "anki_state.jsonl": ("anki_state", 1),
    "topics.jsonl": ("topics", 1),
    "sources.jsonl": ("sources", 1),
    "media_candidates.jsonl": ("media_candidates", 1),
    "source_excerpts.jsonl": ("source_excerpts", 1),
    "resources.jsonl": ("resources", 1),
}
APP_VERSION = (Path(__file__).resolve().parents[2] / "VERSION").read_text().strip()
CONTENT_HASH_ALG = "md5"
GUID_ALG = "md5"

CARD_KEYS = {
    "rev_id", "guid", "guid_alg", "front", "back", "content_format",
    "content_hash", "content_hash_alg", "layer", "topic", "deck", "objects",
    "tier_zero", "cloze", "stratum", "kc", "retrieval_target", "why",
    "source", "source_url", "media", "review_score", "extra",
}
STATE_KEYS = {
    "rev_id", "anki_note_id", "anki_fields_base", "scheduling", "revlog_count",
    "state", "last_seen", "last_verified", "extra",
}
TOPIC_KEYS = {
    "topic", "takeaways", "notation", "sources", "target_cards", "actual_cards",
    "anchors", "gaps", "decisions", "coverage", "extra",
}
SOURCE_KEYS = {
    "type", "path", "url", "title", "locator", "hash", "fetched_at", "error",
    "captions", "extra",
}
MEDIA_KEYS = {
    "file", "original_path", "sha256", "source", "source_url", "locator",
    "kind", "quality", "vision", "used", "why_unused", "preview",
    "preview_meta", "extra",
}
RESOURCE_KEYS = {
    "resource_id", "kind", "role", "name", "path", "sha256", "bytes",
    "schema", "metadata", "extra",
}


class CardRecord(TypedDict, total=False):
    rev_id: str
    guid: str
    guid_alg: str
    front: str
    back: str
    content_format: str
    content_hash: str
    content_hash_alg: str
    layer: str
    topic: str
    deck: str
    objects: list[str]
    tier_zero: bool
    cloze: bool
    stratum: str
    kc: str
    retrieval_target: str
    why: str
    source: str
    source_url: str
    media: list[dict]
    review_score: int | None
    extra: dict[str, Any]


class StateRecord(TypedDict, total=False):
    rev_id: str
    anki_note_id: int | None
    anki_fields_base: dict[str, str]
    scheduling: dict | None
    revlog_count: int
    state: str
    last_seen: str
    last_verified: str
    extra: dict[str, Any]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_uuid() -> str:
    return str(uuid.uuid4())


def content_hash(front: str, back: str) -> str:
    return hashlib.md5(f"{front}|{back}".encode()).hexdigest()


def plain_text(value) -> str:
    """A stable text form for matching authored text to rendered Anki HTML."""
    s = html.unescape(str(value or ""))
    s = re.sub(r"<div[^>]*class=\"src\"[^>]*>.*?</div>", " ", s,
               flags=re.S | re.I)
    s = re.sub(r"<img[^>]*>", " ", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"</(?:p|li|div|h\d|tr)>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace(r"\(", "$").replace(r"\)", "$")
    s = s.replace(r"\[", "$$").replace(r"\]", "$$")
    s = re.sub(r"\*\*|__|`", "", s)
    s = re.sub(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+", "", s)
    return re.sub(r"\s+", " ", s).strip().casefold()


def card_key(row: dict) -> tuple[str, str]:
    return plain_text(row.get("front")), plain_text(row.get("back"))


def _extract_why(back: str) -> str:
    m = re.search(r"\*\*Why:\*\*\s*(.+)", str(back or ""), re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def preserve_extra(source: dict, dest: dict, known: set[str]) -> None:
    """Keep fields we do not understand under `extra`, never drop them."""
    extra = dict(dest.get("extra") or {})
    for key, value in (source or {}).items():
        if key not in known and key != "extra":
            extra[key] = value
    for key, value in ((source or {}).get("extra") or {}).items():
        extra[key] = value
    if extra:
        dest["extra"] = extra


def card_from_source(card: dict, existing: dict | None = None,
                     review_score=None, deck_name: str = "") -> CardRecord:
    existing = existing or {}
    front = str(card.get("front", ""))
    back = str(card.get("back", ""))
    digest = content_hash(front, back)
    row: CardRecord = {
        "rev_id": existing.get("rev_id") or new_uuid(),
        "guid": existing.get("guid") or digest,
        "guid_alg": GUID_ALG,
        "front": front,
        "back": back,
        "content_format": card.get("content_format")
        or existing.get("content_format") or "authoring",
        "content_hash": digest,
        "content_hash_alg": CONTENT_HASH_ALG,
        "layer": str(card.get("layer", "")),
        "topic": str(card.get("topic", "")),
        "deck": str(card.get("deck") or deck_name),
        "objects": list(card.get("objects") or []),
        "tier_zero": bool(card.get("tier_zero", existing.get("tier_zero", False))),
        "cloze": bool(card.get("cloze", existing.get("cloze", False))),
        "stratum": str(card.get("stratum") or existing.get("stratum") or ""),
        "kc": str(card.get("kc") or existing.get("kc") or ""),
        "retrieval_target": str(card.get("retrieval_target")
                                or existing.get("retrieval_target") or ""),
        "why": str(card.get("why") or existing.get("why")
                   or _extract_why(back)),
        "source": str(card.get("source") or card.get("source_ref") or ""),
        "source_url": str(card.get("source_url") or ""),
        "media": list(card.get("media") or []),
        "review_score": (review_score if review_score is not None
                         else card.get("review_score",
                                       existing.get("review_score"))),
    }
    preserve_extra(existing, row, CARD_KEYS)
    preserve_extra(card, row, CARD_KEYS)
    return row


def state_from_existing(existing: dict | None = None) -> StateRecord:
    existing = existing or {}
    state: StateRecord = {
        "rev_id": existing.get("rev_id", ""),
        "anki_note_id": existing.get("anki_note_id"),
        "anki_fields_base": dict(existing.get("anki_fields_base") or {}),
        "scheduling": existing.get("scheduling"),
        "revlog_count": int(existing.get("revlog_count") or 0),
        "state": str(existing.get("state") or "live"),
        "last_seen": str(existing.get("last_seen") or ""),
        "last_verified": str(existing.get("last_verified") or ""),
    }
    preserve_extra(existing, state, STATE_KEYS)
    return state


def state_index(states: list[dict]) -> dict[str, dict]:
    return {str(s.get("rev_id")): s for s in states if s.get("rev_id")}
