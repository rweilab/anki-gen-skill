# Dossier format

Read this only when changing the dossier, writing a migration, or debugging
`context` storage. It is not loaded on normal deck runs.

## Compatibility policy

- `manifest.json` declares `format`, `schema`, `features`, a file table with
  per-file checksums, and `extensions`.
- Additive changes do not bump `schema`. Readers ignore unknown keys and writers
  preserve them under `extra` / `extensions`.
- Breaking changes bump `schema` and require a migration. A dossier from a newer
  schema is refused for writes; it is never silently rewritten or downgraded.
- `index.json` is a rebuildable cache, not the source of truth.

## Layout

```text
decks/<deck_uuid>/
  manifest.json
  cards.jsonl          authored identity/context
  anki_state.jsonl     note IDs, last-seen fields, scheduling, live state
  topics.jsonl
  style.md
  notation.json
  learner.md
  preferences.json
  decisions.md
  future_work.md
  deck_context.md
  sources.jsonl
  source_excerpts.jsonl
  media_candidates.jsonl
  resources.jsonl      open resource index
  resources/           arbitrary files (media, notes, datasets, future kinds)
  thumbnails/          adaptive previews, not card media
  evidence/            intake.md, scope_gate.md, authoring_ledger.md
  revisions/           plans, conflicts, affected-state backups, apply/verify/revert logs
  snapshots/           AnkiConnect exportPackage (deck.apkg) + metadata-only snapshot.json
```

`cards.jsonl` and `anki_state.jsonl` are deliberately separate. `cards.jsonl`
holds authored identity and content; `anki_state.jsonl` holds mutable Anki
identity, last-seen HTML fields, scheduling fingerprints, and live/deleted/
suspended state.

## Extension points

- `manifest.extensions`: namespaced future metadata, preserved on every pack.
- `manifest.features`: optional capabilities; unknown optional features are
  ignored.
- `manifest.files`: role/schema/checksum/size for every stored file.
- `resources.jsonl`: `resource_id`, `kind`, `role`, `name`, `path`, `sha256`,
  `bytes`, `schema`, `metadata`, `extra`. `kind` and `role` are open strings.
  Any file type can live under `resources/`; unknown fields are preserved.
- Every JSONL record may carry `extra`; writers preserve it.

## Writes

Dossiers are written through `dossier/store.py`: a lock, a staging tree, fsync,
then an atomic directory swap. A crash leaves the previous complete tree or the
new complete tree, never a half-written mix. Destructive revision operations take
an AnkiConnect snapshot first.

## Snapshots and retention

`snapshots/<id>/` holds `deck.apkg` plus `snapshot.json` metadata only. Reverting
state comes from the matching `revisions/<stamp>/backup.json`, which stores only
affected notes, cards, and dossier rows. Snapshots are retained until an explicit
`revision.py snapshots --delete` or `--prune`; nothing is removed automatically.
`--sizes` warns above 256 MB or 16 snapshots by default. `snapshots/` is excluded
from context export unless `--include-snapshots` is passed.

## Resources

`context add-resource --deck NAME --file PATH --kind ... --role ...` copies a
file into `resources/` and records its hash, size, kind, role, and metadata.
Resources are included in archives; `snapshots/` is excluded from context export
unless `--include-snapshots` is passed.
