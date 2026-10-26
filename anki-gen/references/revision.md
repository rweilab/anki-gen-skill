# Revising an imported deck

New decks are `.apkg` files. Once the caller has imported one, revisions go
through **AnkiConnect** — a local HTTP bridge inside Anki Desktop.

**Revising an imported deck is not a rebuild.** Attach/audit/revision use AnkiConnect and the
dossier; do not fix a live deck by re-importing beside it.

**Hard rules:** never open, copy, query, or inspect the live Anki collection DB
(`collection.anki2`, `collection.anki21b`), even read-only. Do not use raw SQLite,
the `anki` library, or MCP for live revision. The DB schema changes; AnkiConnect
is the only supported surface. If AnkiConnect is down, stop and fix setup; do not
fall back to a rebuild or a database edit. Do not hand-roll AnkiConnect in a
`/tmp` script: use `revision.py` or `anki_connect.py`.

## Before you start

1. Ask the user to open Anki Desktop and leave it running.
2. Check the bridge:
   ```bash
   python3 scripts/anki_connect.py
   ```
3. If it is missing or broken, detect Anki and install the pinned add-on only
   after asking:
   ```bash
   python3 scripts/anki_connect.py --detect
   python3 scripts/anki_connect.py --install --yes
   ```
   The installer finds the Anki profile/add-ons directory on Linux, macOS,
   Windows, or Flatpak. If detection fails, open Anki once so it creates the
   profile, or pass `--addons-dir PATH`. Then restart Anki and check again. Do
   not install upstream `master`; recent releases broke many clients.
4. Ask which outcome the user wants:
   - **Update the deck already in Anki** — keeps scheduling and review history;
     recommended once they have studied it.
   - **Regenerate a `.apkg`** — fresh import; review history is not carried over
     automatically.

If setup fails, stop. Do not inspect the collection DB to work around it.

## Route the request, do not invent a script

| Request | Use |
|---|---|
| List decks, or inspect one live deck read-only | `revision.py decks`; `revision.py inspect --deck NAME` |
| Lowercase/normalize tags on an existing deck | `revision.py tags --deck NAME --lowercase` |
| Rewrite many backs/fronts or tags | `revision.py update --deck NAME --file edits.json --browser-closed` |
| One wording fix, or cull/merge/split | `revision.py plan` then `revision.py apply` |
| Sync an authored card set into a live deck | `revision.py sync --deck NAME --cards FILE` then `apply` |
| Snapshot without applying | `revision.py snapshots --deck NAME --create --reason "..."` |
| Undo the last applied change | `revision.py revert --deck NAME --last --yes` |
| Inspect snapshots or storage | `revision.py snapshots --deck NAME --sizes` |

If the supported command does not cover the request, stop and report. Do not fall back to a
`/tmp` Python script, a loop of raw `curl` calls, or a custom AnkiConnect wrapper. Those are where
the field/tag argument mistakes and repeated retries came from. Deck spin-off is deferred and has
no verb yet; do not invent one.

Never use collection-wide tag operations for a deck edit. `replaceTagsInAllNotes` and
`clearUnusedTags` can change other decks; the supported tag path is deck-scoped.

## The dossier

`context pack` writes a compact, persistent record under:

```text
${XDG_DATA_HOME:-~/.local/share}/anki-gen/decks/<deck-uuid>/
```

`<deck-uuid>` is stable for the dossier's whole life. `index.json` is a rebuildable
cache, not the source of truth.

`pipeline.py --build --context` packs after a successful build, before the work
tree is removed. Without `--context`, no dossier is written. The dossier holds only
distilled context: authored card records, live Anki state,
topic takeaways, course style/notation, learner preferences, deck-shape decisions,
future work, source anchors/hashes, media-candidate metadata, adaptive previews,
revision logs, and snapshots. `cards.jsonl` is authored identity/context;
`anki_state.jsonl` is note IDs, last-seen fields, scheduling fingerprints, and
live state. It never holds full PDFs/videos/transcripts, full media, the Anki DB,
secrets, or hidden reasoning. `manifest.json` declares the schema, file table,
checksums, features, and deck identity.

`curated.json` in the work directory is the optional model-authored section:
`topics`, `style`, `notation`, `learner`, `preferences`, `decisions`,
`future_work`. Write it while the source context is still on hand; do not do an
end-of-run corpus re-read to summarize. Later packs preserve a dossier section
that already exists.

Portability is explicit:

```bash
python3 scripts/revision.py context export --deck "DECK NAME" --out deck-context.zip
python3 scripts/revision.py context import deck-context.zip            # restore only
python3 scripts/revision.py context import deck-context.zip --attach   # restore + attach
```

Archives are deterministic, per-file checksummed, and reject unsafe paths,
symlinks, duplicate entries, and oversized content. Imports are staged, verified,
backed up, and atomically swapped.

Context stays local by default. Do not put it in Anki notes or media.

## Identity

- `rev_id` — stable UUID in the dossier, generated at pack time.
- `anki_note_id` — primary identity after attach.
- `guid` — the `.apkg` GUID (`md5(front|back)`), stored for output.
- `content_hash` — fingerprint/diagnostic only, never revision identity.

AnkiConnect `notesInfo` exposes note IDs but not GUIDs. `attach` maps by deck plus
normalized front/back text and stores note IDs. Re-attach by deck plus
fingerprints when IDs change. Ambiguity is never guessed: attach lists the
candidates and asks for a resolution (`--map REV_ID=NOTE_ID`, internal only).

```bash
python3 scripts/revision.py attach --deck "SCHOOL::RTOS"
python3 scripts/revision.py attach --deck "SCHOOL::RTOS" --reconstruct   # old deck, no dossier
python3 scripts/revision.py audit --deck "SCHOOL::RTOS"                 # read-only
```

`--reconstruct` builds a `confidence: reconstructed` record from live fields and
tags. It does not invent a ledger, `why`, or source evidence. Audit never writes.

### Build identity and merge

A note's identity is its content. The `.apkg` GUID is `hash = md5(front|back)`
(`scripts/cardid.py`), which makes a re-run idempotent — but a card whose *text*
is edited becomes a new note, orphaning the old one's scheduling history. This
applies to **every** build. Fix wording in the source of truth *before* the deck
goes into Anki for real use; once it is being reviewed, edit the note in Anki for
pure wording fixes (history stays attached) and return to the source only for
structural changes (split, cut, rewritten front). Never "fix" a live deck by
rebuilding and importing beside the old one.

`--merge-existing` starts from the existing deck (history and scheduling survive)
and adds only cards whose `hash` is absent, printing the skip count — **idempotent**.
(This was false until v1.5: the merge path added every card unconditionally.)

## Snapshots and one-command revert

Every `apply` takes an AnkiConnect snapshot before writing: `deck.apkg` is exported
with scheduling (`exportPackage`, `includeSched`) and `snapshot.json` stores only
metadata (ID, deck, reason, note/card counts, apply-log link). Old fields and
queue state live in `revisions/<stamp>/backup.json`, limited to affected notes,
cards, and dossier rows. The apply log records the snapshot ID.

```bash
python3 scripts/revision.py snapshots --deck "SCHOOL::RTOS"
python3 scripts/revision.py snapshots --deck "SCHOOL::RTOS" --sizes
python3 scripts/revision.py snapshots --deck "SCHOOL::RTOS" \
    --create --reason "before sync"
python3 scripts/revision.py revert --deck "SCHOOL::RTOS" --last --yes
```

`--create` writes a checkpoint without applying anything. Snapshots live only under the dossier's
`snapshots/` directory; there is no legacy `anki/<deck>/` backup path.

`--sizes` reports snapshots, previews, revisions, resources, and per-snapshot
bytes. It warns above 256 MB or 16 snapshots by default; override with
`--warn-mb` and `--warn-count`. Retention is always explicit:

```bash
python3 scripts/revision.py snapshots --deck "SCHOOL::RTOS" --delete ID --yes
python3 scripts/revision.py snapshots --deck "SCHOOL::RTOS" --prune --keep 4 --yes
```

Nothing is deleted automatically. Deleting the snapshot used by the latest apply
removes the easy `revert --last` path, so it requires `--force`. Context export
still excludes `snapshots/` unless `--include-snapshots` is passed.

`revert --last` restores the last applied revision from `backup.json` +
`apply_log.json`: field updates by note ID, added cards are removed, deleted cards
are restored through `importPackage`, and suspension state is restored. Manual
edits made after the revision are preserved by default and reported as conflicts;
`--force` overrides them. A pre-revert snapshot is taken first. `--dry-run` prints
the counts. Field restores require `--browser-closed`; sync is opt-in and only
after verification.

## Plan, then apply

The user speaks plaintext; note IDs stay internal.

```bash
python3 scripts/revision.py plan --deck "SCHOOL::RTOS" \
    --intent "cull the easiest cards and fold them into higher-reasoning cards"
```

`plan` reads the dossier plus a live snapshot, resolves by topic/front/tag/score/
leech/family, and writes `revision_plan.md` + `revision_plan.json` under
`revisions/<stamp>/`. It does not write Anki. The human plan names cards by layer,
topic, and front; never by note ID. To inspect them in Anki: open **Browse**,
select the deck, and search for one of the fronts shown in the plan (OS-agnostic;
no file paths). Useful selectors:

- `--topic`, `--front`, `--tag`, `--layer`, `--stratum`, `--score 1..5`, `--leech`
- `--update-front OLD=NEW`, `--update-back OLD=NEW`
- `--merge-match TEXT --into TEXT`
- `--split-match TEXT --split-front ... --split-back ...`
- `--attach-media` (or intent words visual/image/diagram/figure)
- `--allow-anchors` — tier-zero cards are protected by default

Intent vocabulary that changes the shape: cull/trim/drop/reduce (score-1
candidates), merge/fold (victims into a higher-layer survivor), leech, visual.
**Score 1 means “known / too easy,” not automatic rejection.** Use it to rescope,
re-level, merge trivial variants, protect anchors, or shift focus.

## Sync authored changes into a live deck

When `cards.jsonl` changes after import, do not rebuild and re-import beside the old deck. `sync`
reconciles the authored set with the attached live deck and writes a normal apply plan; it never
writes Anki itself. Use `inspect` first if you need to see the live notes, models, dossier, or
the live note to dossier `rev_id` mapping.

```bash
python3 scripts/revision.py inspect --deck "SCHOOL::RTOS"
python3 scripts/revision.py sync --deck "SCHOOL::RTOS" --cards "$WORK/cards.jsonl"
python3 scripts/revision.py apply --plan <sync_plan.json> \
    --choice retire-1=keep --browser-closed
```

Matching is deterministic: `rev_id`, then content hash, then exact normalized front/back. A card
with an unknown `rev_id` is an error; omit `rev_id` for a new card. Ambiguous matches are reported,
never guessed; resolve with `--map REV_ID=INDEX`, where `INDEX` is the 1-based line in the authored
file. Live notes absent from the new set become the `retire-1` group, so apply needs an explicit
`keep`, `suspend`, or `delete` choice. Updates keep note/card IDs and scheduling; new cards start
new. `sync` plans are transient apply plans, not a published format; do not script against them.

## Bulk field and tag edits

For a large rewrite or tag cleanup, do not write an ad-hoc AnkiConnect script. Attach first, then
use the supported bulk path. It snapshots, backs up affected notes, verifies fields/tags, and
checks that scheduling/revlog did not change.

```bash
python3 scripts/revision.py tags --deck "SCHOOL::RTOS" --lowercase
python3 scripts/revision.py update --deck "SCHOOL::RTOS" --file edits.json --browser-closed
```

`edits.json` uses `rev_id` (or an exact `front`) and never raw note IDs:

```json
{"schema": 1, "edits": [
  {"rev_id": "...", "fields": {"Back": "<p>...</p>"}, "tags": ["concurrency", "rtos"]}
]}
```

Rules:

- `tags --lowercase` is deck-scoped. Old tag names may remain in Anki's sidebar until the
  collection clears them; this command does not run global tag cleanup.
- Never call `replaceTagsInAllNotes` or `clearUnusedTags` for a deck edit. They are
  collection-wide and can change other decks.
- For more than ~20 changed cards, show 3–5 before/after examples and wait before applying.
- Use `--dry-run` first when the edit is broad or generated by a model.

## Destructive groups

Every cull/merge group is shown in full with its scheduling consequence. Apply
requires an explicit choice **per group**; there is no hidden default:

```bash
python3 scripts/revision.py apply --plan <plan.json> \
    --choice cull-1=delete --choice merge-1=suspend
```

Choices are `delete`, `suspend`, or `keep`. Deletion removes cards and review
history; it is allowed only after the explicit choice and a backup written to
`revisions/<stamp>/backup.json`. Some callers never suspend — that is why
permanent delete is a first-class choice, and why “keep” exists.

Before field updates, close Anki's Browser window and pass `--browser-closed`;
`updateNoteFields` can silently fail while a note is open. Sync is opt-in and
happens only after verification: `--sync`.

## Conflicts

Apply runs a three-way check: dossier base vs current Anki note vs proposed
revision. Manual Anki edits win by default. Conflicting fields/cards are skipped
and written to `conflicts.json`; only `--overwrite-conflicts` overrides that, and
only after the caller has seen the report.

## Scheduling policy

- Field-only updates preserve note/card IDs, `due`, `interval`, `factor`, `reps`,
  `lapses`, `queue`, `type`, and revlog count. Verification fails the apply if any
  changed.
- New cards start new.
- Merge: the survivor keeps its history; victims are deleted/suspended/kept by
  the group choice.
- Split: the existing card keeps its history; new cards start new. There is no
  clean revlog split.
- Cloze ordinal changes are refused unless `--allow-card-shape-change`: unchanged
  ordinals keep history, removed cards lose it, new cards start new.
- No notetype, field, or template changes in routine revision. Use only
  `updateNoteFields`, `addNotes`, `deleteNotes`, `suspend`, `changeDeck`,
  `setDueDate`, `storeMediaFile`, `exportPackage`, `importPackage`, and `sync`.

## Resources

`resources/` is the forward-compatible home for files that are not card media:
datasets, notes, audio, future formats. `resources.jsonl` records `kind` and
`role` as open strings plus a hash and metadata. Add with:

```bash
python3 scripts/revision.py context add-resource --deck "NAME" --file path \
    --kind dataset --role reference --name "name"
python3 scripts/revision.py context resources --deck "NAME"
```

The default dossier still stores metadata/previews rather than full media unless
the caller explicitly adds a resource.

## Media previews

Unused high/medium candidates are retained as metadata with adaptive previews:
about 640 px general, 768–1024 px for label-heavy diagrams, and 320 px only for
contact-sheet recognition. There is no hard cap. Previews are indexes, not card
media. Re-extract the original at full resolution before attaching. If the source
is gone, a preview may be used only as a warned low-res fallback with
`--allow-low-res`; never silently.
