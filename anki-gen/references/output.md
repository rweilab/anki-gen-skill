# Output mechanics

- `./<topic>.apkg` in cwd.
- **Cleanup is part of the output contract.** After the build validates, the only new entry in the
  caller's directory is the `.apkg`. The work directory is deleted in full and the review server is
  stopped; no source folder is left unless the caller named one.
- **Deck naming is the caller's.** Pass through `--deck-name`; impose no convention (rule 23). It is
  **required** — a silent `"Default"` fallback once let a valid deck land somewhere nobody finds.
  Ask in the source survey. A `::` nests; Anki matches case-insensitively.
- **A note's identity is its content.** The GUID is `hash` = `md5(front|back)` (`scripts/cardid.py`),
  which makes a re-run idempotent — but a card whose *text* is edited becomes a new note, orphaning
  the old one's scheduling history. This applies to **every** build. Fix wording in the source of
  truth *before* the deck goes into Anki for real use; once it is being reviewed, edit the note in
  Anki for pure wording fixes (history stays attached) and return to the source only for structural
  changes (split, cut, rewritten front). Never "fix" a live deck by rebuilding and importing beside
  the old one.
- Merge: `--merge-existing` starts from the existing deck (history and scheduling survive) and adds
  only cards whose `hash` is absent, printing the skip count — **idempotent**. (*This was false
  until now:* the merge path added every card unconditionally.)
- Media is opt-in: files are bundled only with `--media --media-root <work>`, otherwise the
  `media` field is ignored. See `references/optional.md`.
- Import: `File → Import` → AnkiWeb sync.
