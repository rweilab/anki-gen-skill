# Test map

Read this before opening a suite. Keep negative fixtures local to the suite that
owns the rule; shared setup must not hide the defect being tested.

| File | Owns | Speed | External tools |
|---|---|---:|---|
| `hardening.py` | card validation, KC/evidence checks, authoring API, build/APKG, merge, cloze, mutation probes, missing-anki honesty | 5s | anki, PIL |
| `revision_hardening.py` | fake AnkiConnect, attach/audit/plan/apply/revert/snapshots | 4s | none |
| `context_hardening.py` | dossier pack, schema, previews, archive, resources | <1s | PIL |
| `pipeline_hardening.py` | pipeline extraction/build/gates/merge flow, review actions, packet, shape, mixed sources | 2s | ffmpeg |
| `video_hardening.py` | captions, playlist range, frames, labels | 7s | ffmpeg, tesseract |
| `visual_hardening.py` | visual scoring, PDF figures, media index, vision bridge | 2s | PyMuPDF, PIL |
| `slides_hardening.py` | PPTX text/notes/images and rejections | <1s | PIL |
| `local_media_hardening.py` | sidecars, audio-only, model selection, local WAV decode | <1s | ffmpeg |
| `quality_precision.py` | validator false-positive floor | <1s | none |
| `install_test.sh` | installer/upgrade and key preservation | smoke | bash |

Canonical ownership:

- notetype/order/card identity: `hardening.py`
- AnkiConnect behavior and snapshots: `revision_hardening.py`
- dossier format and archives: `context_hardening.py`
- pipeline flag passthrough, combined sources, media state/resume, review actions, packet, shape, mixed sources: `pipeline_hardening.py`
- per-video progress and playlist resume: `video_hardening.py`
- authoring helpers and authors: `hardening.py`
- vision confirmation selection: `visual_hardening.py`
- review plan staleness, review page, and UI text: `scripts/smoke.sh`

Run one suite directly while iterating. Run `bash scripts/smoke.sh` once before
handoff; it contains the changelog, package, UI, installer, and no-litter gates.
