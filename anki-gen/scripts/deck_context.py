#!/usr/bin/env python3
"""Deck dossier facade.

Implementation lives in `dossier/`: transactional storage, manifest/file
checksums, stable deck UUIDs, adaptive previews, and verified archives.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dossier import archive, packer, resources, validate as validator  # noqa: E402
from dossier import index as idx  # noqa: E402
from dossier.manifest import verify  # noqa: E402
from dossier.model import now, plain_text  # noqa: E402
from dossier.store import write_json  # noqa: E402
from dossier.previews import long_edge as preview_long_edge  # noqa: E402

# Re-exported names keep the rest of the skill on one import surface.
data_root = idx.data_root
decks_root = idx.decks_root
deck_dir = idx.deck_dir
resolve = idx.resolve
find_by_deck_id = idx.find_by_deck_id
register = idx.register
identity = packer.identity
pack = packer.pack
save = packer.save
load = packer.load
update_cards = packer.update_cards
add_resource = resources.add
list_resources = resources.list_resources
revision_dir = packer.revision_dir
snapshots_dir = packer.snapshots_dir
export = archive.export


def import_archive(path, *, dry_run: bool = False):
    return archive.import_archive(path, dry_run=dry_run)


def validate(context: dict | None = None, deck_key_or_selector: str | None = None):
    if context is None:
        context = load(deck_key_or_selector)
    return validator.validate(context, deck_key_or_selector)


def file_problems(selector: str) -> list[str]:
    context = load(selector)
    if not context:
        return ["missing dossier"]
    return verify(Path(context["path"]), context["manifest"])
