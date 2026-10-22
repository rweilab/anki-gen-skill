# Revising an imported deck

New decks are `.apkg` files. Once the caller has imported one, revisions go
through **AnkiConnect** — a local HTTP bridge inside Anki Desktop. Never write
SQLite, import the `anki` library, or use MCP for live revision. If AnkiConnect
is down, attach/audit/plan/apply stop with a setup message; they do not silently
fall back to a rebuild.

Setup: open Anki, install/enable AnkiConnect, keep Anki running. Check with:

```bash
python3 scripts/anki_connect.py
```

## The dossier

`context pack` writes a compact, persistent record under:

```text
${XDG_DATA_HOME:-~/.local/share}/anki-gen/decks/<deck-key>/
```

`pipeline.py --build` packs automatically after a successful build, before stage
14 removes `.anki-gen-temp`. `--no-context` disables it. The dossier holds only
distilled context: card records, topic takeaways, course style/notation, learner
preferences, deck-shape decisions, future work, source anchors/hashes, media
candidate metadata, adaptive previews, and revision logs. It never holds full
PDFs/videos/transcripts, full media, the Anki DB, scheduling copies, secrets, or
hidden reasoning.

`curated.json` in the work directory is the optional model-authored section:
`topics`, `style`, `notation`, `learner`, `preferences`, `decisions`,
`future_work`. Write it while the source context is still on hand; do not do an
end-of-run corpus re-read to summarize. Later packs preserve a dossier section
that already exists.

Portability is explicit:

```bash
python3 scripts/revision.py context export --deck "DECK NAME" --out deck-context.zip
python3 scripts/revision.py context import deck-context.zip            # re-attaches if AnkiConnect is up
python3 scripts/revision.py context import deck-context.zip --no-attach
```

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

## Plan, then apply

The user speaks plaintext; note IDs stay internal.

```bash
python3 scripts/revision.py plan --deck "SCHOOL::RTOS" \
    --intent "cull the easiest cards and fold them into higher-reasoning cards"
```

`plan` reads the dossier plus a live snapshot, resolves by topic/front/tag/score/
leech/family, and writes `revision_plan.md` + `revision_plan.json` under
`revisions/<stamp>/`. It does not write Anki. The human plan names cards by layer,
topic, and front; never by note ID. Useful selectors:

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
  `setDueDate`, `storeMediaFile`, and `sync`.

## Media previews

Unused high/medium candidates are retained as metadata with adaptive previews:
about 640 px general, 768–1024 px for label-heavy diagrams, and 320 px only for
contact-sheet recognition. There is no hard cap. Previews are indexes, not card
media. Re-extract the original at full resolution before attaching. If the source
is gone, a preview may be used only as a warned low-res fallback with
`--allow-low-res`; never silently.
