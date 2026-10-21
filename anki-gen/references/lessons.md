# Regression lessons

Architecture/token postmortem: `MAINTAINERS.md` (not loaded by the skill).

## Regression lessons


Behaviour changes, leading with the why; the rule or section carries the full reasoning. Kept short
because these are the failures that are invisible until they bite.

- **`--merge-existing` duplicated the whole deck on re-run.** Cards already present are now skipped
  by GUID, with the count printed.
- **`genanki` and `--engine` are gone.** That path could not produce a cloze deck Anki 26 opens,
  forced `genanki` on every import, and hashed with sha256 where everything else uses md5, so
  identity did not survive an engine change. `anki` is now a hard requirement.
- **`--strict` did nothing on the default path** (implemented only on the deleted genanki path). It
  now runs the static checks and refuses on an error.
- **`roi_report.py` has no built-in exam weights.** Coverage groups by `topic`; weighting is
  optional via `--exam-weights`; without it the report says so instead of printing dead "unscored"
  rows. Anchors come from `tier_zero`, not phrase-matching.
- **Review is a triaged subset.** `triage.py` always runs; `--plan` renders its choice with a reason
  per card. The whole deck is still reviewable without `--plan`.
- **`render.py` no longer corrupts code spans or display-math lines.** It had run its math pass
  inside inline code (rendering a card that explained the delimiters as garbage, then blaming the
  author's stray `$`) and deleted prose sharing a line with `$$...$$`. Own-line display blocks
  render byte-identically.
- **Card identity has one definition** (`scripts/cardid.py`): builder, review server and triage all
  derive `md5(front|back)` from it, so a review score and a note GUID agree by construction.
- **`triage.py`'s format axis keys on `stratum`**, so a deck-authored sub-kind earns its own exemplar
  instead of being *reported* as "0 of 3 shown" with no mechanism to fix it.
- **The review budget is breadth-first** — measured: `--per-topic 1 --max 30` showed 20 cards over
  19/19 topics; `--per-topic 3 --max 24` showed 24 over 16/19.
- **The card face leads with the topic; tags are a sniper.** `META` was `{{Layer}} · {{Topic}}`, so
  every card was headed "L2", and the tag set was `[topic, layer]` — a tag returning every
  understanding card and saying nothing about the subject. The face shows the topic; the layer ships
  as a field and reads as a word (`Recall`/`Understanding`/`Boundary`) where a human sees it.
- **New `objects` field: 0–2 tags naming the specific things a card is about.** A topic tag returns
  everything relevant (shotgun); an object tag returns the cards specifically about a thing
  (sniper). A card on vacancy concentration in copper gets `#vacancy_concentration` and `#cu`, not a
  third tag restating its topic. `validate_cards.py` enforces the cap, rejects a layer code in
  `topic`, flags an object that duplicates the topic (Anki folds tags case-insensitively and would
  drop it), and reports the object census to catch singleton tags.
- **Object tags are how "related notes" works.** Rule 26 forbids a back pointing at another card; a
  related-notes footer is the same thing and goes stale. "Every card about FCC" is a tag query.
- **Status lines while it runs.** Short plain-language status is encouraged at every level, replacing
  "never narrate the pipeline"; what stays banned is *jargon* narration — stage numbers, layer codes,
  validator output. The estimate is a hedge, never a promise; the write stage is the only slow part
  and its length depends on the material.
- **The review URL gets one sentence** — what the page is and to come back when done — then the URL
  alone on its own line, so it stays paste-able. A beginner who has never seen the page needs to
  know what it is; a bare URL told them nothing.
- **`rejected.json` / `--rejected` are gone; a 5 is handled by editing the source.** The tombstone
  could not hold — a re-scope rewrites card text, so a reworded rejected card carried a new hash and
  slipped the filter — while adding a file and a silent stale-list failure mode. `cardid.py` keeps
  `card_hash` and `last_row_per_card`.
- **The deck audit is opt-in; the web review is unconditional** — never offered as a question.
- **Three gates no longer block a beginner** — the source survey proceeds on stated assumptions, the
  deck audit is skipped, and the trim list moves into the report.
- **Cleanup is explicit and default-delete.** Stage 14 is a checklist: the `.apkg` is the only new
  file in the caller's cwd, the work directory is deleted in full, and a hand-authored source is
  promoted only to a caller-named path — never to a folder the agent invents. (A run that left a
  `midterm1_deck/` folder behind is why this is a checklist.)
- **Rule 26, no cross-card pointers.** Only *stale* pointers were called out before, missing the
  structural case: the reference resolves to nothing on the one screen where it is needed.
- **The formula sheet is a question, not a rule.** "Do not card what the sheet prints" is wrong for
  a reference deck. The high-value half survives: when the sheet is given, the deck's mass moves to
  its absences and the decisions around each equation.
- **Boundary cards became a calibration axis.** The L3 exemption is a default, not a law; a learner
  who prefers boundaries as decisions gets the same content reframed.
- **The review page had no JS smoke test.** An undefined helper (`layer_word`) left `#sheet` empty
  while the page loaded; only a browser console showed it. The lesson: after rendering the page,
  assert the first card is in the DOM, not just that the server returned 200.
- **Media is opt-in and human-audited.** A default build must carry no media files; the review
  samples image cards and shows a missing-file placeholder. Model vision is never assumed —
  uncertain figures are dropped and listed, not guessed.
- **Text-first is the default; `image-vision` is external.** Handwritten/scanned sources are
  transcribed with `image-vision` (Gemini), not OCR'd by the builder. Never build a deck from
  an empty extract; attach a figure only on request and audit it.
- **Over-cap images are downscaled, not skipped.** Pillow (optional, image builds only) shrinks to
  1600 px and re-encodes; EXIF orientation is applied on re-encode. Only a file still over 1 MB is
  dropped, so good web images are not lost to a strict pixel cap.
- **Anki's exporter writes a stub `collection.anki2`** for legacy readers (the real data goes in
  `collection.anki21`), so it cannot be used here. The builder hand-writes the classic layout:
  `collection.anki2` + a `media` JSON map + numbered files.
- **Token discipline is a workflow, not a card cut.** Batch 10–15 cards after a one-line ledger;
  read only the allowlist; phase-split large reviews. The 2026-10 MA2034 audit: 67 one-card edits
  and a 77k script read-back made a 99-card build 905k input; a 67-card build with 2 writes + 11
  edits was 148k. Reasoning per card and heuristic coverage are the invariant; card density is not
  a token lever. If a rule or script is wrong, fix it yourself: reproduce, smallest edit, run
  `smoke.sh`, add a changelog line. No lock.
- **Removed:** `deck_audit.py` (never scored anything), `parse_intent`'s `--resume` (its session
  directory was never created), `schemas/intent.json` (read by nothing), Image Occlusion and Type-in
  templates (no notetype implements them), and the lettered check labels (`A3`, `B4`) in favour of
  rule numbers.
