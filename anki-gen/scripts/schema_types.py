"""Typed shapes for the JSON that crosses module boundaries.

Static only: gates remain the runtime validation. Keeping the shapes here lets a
maintainer (or an agent) see what `cards.jsonl`, the KC map, review logs, and
plans actually carry.
"""
from __future__ import annotations

from typing import Literal, TypedDict

Layer = Literal["L1", "L2", "L3", "Procedure"]
Side = Literal["front", "back"]
Severity = Literal["err", "warn", "info"]
Score = Literal[1, 2, 3, 4, 5]


class MediaItem(TypedDict, total=False):
    file: str
    side: Side
    caption: str
    source: str
    source_url: str


class Card(TypedDict, total=False):
    front: str
    back: str
    layer: Layer
    topic: str
    source: str
    source_ref: str
    source_url: str
    kc: str
    objects: list[str]
    cloze: bool
    tier_zero: bool
    media: list[MediaItem | str]
    stratum: str
    rev_id: str


class KC(TypedDict, total=False):
    type: str
    claim: str
    why: str
    source: str
    evidence_quote: str
    requires: list[str]


class PlanEntry(TypedDict, total=False):
    i: int
    hash: str
    kind: str
    reasons: list[str]


class FeedbackRow(TypedDict, total=False):
    i: int
    n: int
    hash: str
    score: Score
    comment: str
    recall: bool


class ReviewAction(TypedDict, total=False):
    cards: list[int]
    topic: str
    stratum: str
    kc: str
    comments: list[str]
    action: str
    target: str
    net_delta: int
