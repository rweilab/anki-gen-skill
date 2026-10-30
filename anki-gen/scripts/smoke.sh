#!/usr/bin/env bash
# anki-gen maintainer smoke test — NOT part of a normal deck run.
#
# Exercises the whole mechanical path on a three-card fixture under $TMPDIR, then
# asserts the review page actually renders a card. Cleans up after itself and never
# kills a process: it asks the review server to finish (POST /finish) and lets its
# own idle-timeout be the backstop.
#
#   bash scripts/smoke.sh
#   KEEP_WORK=1 bash scripts/smoke.sh      # opt in to keeping the temp tree
#   SMOKE_DEBUG=1 bash scripts/smoke.sh    # trace shell commands
#
# Requires: python3, the `anki` library, and the skill's scripts. A headless Chrome
# is used when present; the render assertion is skipped cleanly when it is not.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
[ "${SMOKE_DEBUG:-0}" = "1" ] && set -x

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS="$ROOT/scripts"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/anki-gen-smoke.XXXXXX")"
VERSION="$(cat "$ROOT/VERSION")"
BEFORE_STATUS="$(git -C "$ROOT/.." status --porcelain --untracked-files=all 2>/dev/null || true)"
BEFORE_JUNK="$(find "$ROOT/.." -maxdepth 1 \( -name '*.apkg' -o -name 'review_done' -o -name '.anki-gen-temp' \) -print 2>/dev/null | sort)"
URL=""
server_pid=""
KEEP_WORK="${KEEP_WORK:-0}"

cleanup() {
  # Ask the server to stop; never kill it. Idle-timeout is the backstop.
  if [ -n "$URL" ]; then
    curl -s -m 2 -X POST "${URL%/}/finish" >/dev/null 2>&1 || true
  fi
  # This is the smoke test's own child, never a wildcard kill.
  if [ -n "$server_pid" ] && kill -0 "$server_pid" 2>/dev/null; then
    sleep 1
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  if [ "$KEEP_WORK" = "1" ]; then
    printf 'work kept: %s\n' "$WORK" >&2
  else
    rm -rf "$WORK"
  fi
}
trap cleanup EXIT

pass() { printf 'ok    %s\n' "$1"; }

hint_for() {
  case "$1" in
    *validate_cards*)
      echo "Hint: python3 \"$SCRIPTS/validate_cards.py\" \"$WORK/cards.json\" --json"
      echo "      inspect the failing card in $WORK/cards.json"
      ;;
    *build_apkg*|*validate_apkg*|*merge*|*downscale*|*media*)
      echo "Hint: inspect $WORK; try: python3 \"$SCRIPTS/doctor.py\""
      echo "      build logs and .apkg files are in $WORK"
      ;;
    *review*|*GET*|*page*|*server*)
      echo "Hint: cat $WORK/server.log; check the review URL and port"
      echo "      the server self-exits on /finish or idle timeout"
      ;;
    *triage*|*plan*)
      echo "Hint: python3 \"$SCRIPTS/triage.py\" \"$WORK/cards.json\" --json"
      ;;
    *packet*|*hardening*|*assert*|*render*|*cloze*|*feedback*)
      echo "Hint: rerun the failing Python block or: python3 tests/hardening.py"
      echo "      use KEEP_WORK=1 to keep the fixture"
      ;;
    *)
      echo "Hint: inspect $WORK; run python3 \"$SCRIPTS/doctor.py\""
      ;;
  esac
}

show_logs() {
  local f
  for f in "$WORK"/*.log; do
    [ -f "$f" ] || continue
    printf '\n--- %s (last 30 lines) ---\n' "$f" >&2
    tail -n 30 "$f" >&2 || true
  done
}

fail() {
  local rc=$? msg="${1:-unknown failure}"
  [ "$rc" -ne 0 ] || rc=1
  printf '\nFAIL  %s\n' "$msg" >&2
  printf 'line: %s\n' "${BASH_LINENO[0]:-?}" >&2
  printf 'work: %s\n' "$WORK" >&2
  echo "rerun: KEEP_WORK=1 SMOKE_DEBUG=1 bash $ROOT/scripts/smoke.sh" >&2
  hint_for "$msg" >&2
  show_logs
  exit "${rc:-1}"
}


cat > "$WORK/cards.json" <<'JSON'
[
  {"front":"What does this smoke test verify?","back":"**Why:** that validate, triage, build, import and the review page all run end to end.","layer":"L2","topic":"Smoke","objects":["smoke_test"],"deck":"SMOKE::TEST","source":"smoke p.1"},
  {"front":"In vacuum, light travels at what speed (symbol and approximate value)?","back":"$c \\approx 3\\times10^8$ m/s.","layer":"L1","topic":"Smoke","objects":["smoke_test"],"deck":"SMOKE::TEST","source":"smoke p.2"},
  {"front":"A body-centred cell has {{c1::2}} atoms per unit cell.","back":"Eight corners at 1/8 plus one interior atom.","layer":"L1","topic":"Smoke","cloze":true,"objects":["smoke_test"],"deck":"SMOKE::TEST","source":"smoke p.3"},
  {"front":"Which diagram shows the unit cell?","back":"The one with the labelled corners.","layer":"L2","topic":"Smoke","objects":["smoke_test"],"deck":"SMOKE::TEST","source":"smoke p.4","media":[{"file":"media/pixel.png","side":"back","caption":"pixel","source":"smoke"}]}
]
JSON

python3 - "$WORK/media/pixel.png" <<'PY'
import base64, pathlib, sys
p = pathlib.Path(sys.argv[1]); p.parent.mkdir(parents=True, exist_ok=True)
p.write_bytes(base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII="))
PY

python3 "$SCRIPTS/validate_cards.py" "$WORK/cards.json" >/dev/null || fail "validate_cards"
python3 "$ROOT/scripts/changelog_check.py" || fail "changelog/version"
pass "changelog/version"

bash "$ROOT/scripts/package_handoff.sh" --check >/dev/null || fail "package/shipping check"
pass "package/shipping check"

pass "validate_cards"

python3 - "$SCRIPTS" <<'PY' || fail "render matrix"
import sys
sys.path.insert(0, sys.argv[1])
import render
out = render.to_html(r"$$\begin{bmatrix} 1 & 2 \\ 3 & 4 \end{bmatrix}$$")
assert r"\begin{bmatrix}" in out and r"\\" in out, out
assert '<div class="math-block">' in out, out
PY
pass "render matrix"

python3 - "$SCRIPTS" <<'PY' || fail "cloze preview fidelity"
import sys
sys.path.insert(0, sys.argv[1])
from review_server import render_cloze, render_cards
from render import to_html
answer = r"$Q_v$ and **two**"
preview = render_cloze("{{c1::" + answer + "}}", True)
assert r"\(Q_v\)" in preview and "<b>two</b>" in preview, preview
assert to_html(answer) in preview, (to_html(answer), preview)
assert "$Q_v$" not in preview
hint = render_cloze("{{c1::answer::$h$}}", False)
assert r"\(h\)" in hint, hint
card = {"front": "A {{c1::B}}", "back": "x", "layer": "L1", "topic": "T",
        "cloze": True, "media": [{"file": "media/pixel.png", "side": "front"}]}
rendered = render_cards([card])[0]
assert "/media/media/pixel.png" in rendered["back"], rendered["back"]
PY
pass "cloze preview fidelity"

python3 - "$SCRIPTS" <<'PY' || fail "feedback identity"
import sys, tempfile, json
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from review_server import Store
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "f.jsonl"
    p.write_text(json.dumps({"i": 0, "n": 1, "hash": "a", "score": 5}) + "\n"
                 + json.dumps({"i": 1, "n": 2, "hash": "b", "score": 2}) + "\n")
    s = Store(p)
    assert s.state()["a"]["score"] == 5, s.state()
    s.put({"i": 1, "n": 2, "hash": "a", "score": 3})
    assert s.state()["a"]["score"] == 3, s.state()
    old = Path(td) / "old.jsonl"
    old.write_text(json.dumps({"i": 7, "score": 4}) + "\n")
    assert Store(old).state()["7"]["score"] == 4
PY
pass "feedback identity"

python3 - "$SCRIPTS" <<'PY' || fail "cheap correctness"
import sys
sys.path.insert(0, sys.argv[1])
from extract_pdf import tag_for
from validate_apkg import audit
assert tag_for("https://example.com/path/lecture.pdf") == "lecture", tag_for("https://example.com/path/lecture.pdf")
assert not any("stray $" in x for x in audit("Use <code>$</code> for inline math."))
PY
pass "URL tag and code-span audit"

python3 - "$ROOT" <<'PY' || fail "docs path audit"
import re
import sys
from pathlib import Path
root = Path(sys.argv[1])
bad = []
maint = (root / "MAINTAINERS.md").read_text()
deprecated = set()
if "## Deprecations" in maint:
    block = maint.split("## Deprecations", 1)[1].split("\n## ", 1)[0]
    deprecated = set(re.findall(r"`([^`]+\.(?:md|py|sh))`", block))
for md in root.rglob("*.md"):
    text = md.read_text()
    for match in re.finditer(
            r"`((?:references|maintainers|scripts|tests)/[^`\s]+?\.(?:md|py|sh))`",
            text):
        rel = match.group(1)
        if "<" in rel or rel in deprecated:
            continue
        if not (root / rel).exists():
            bad.append(f"{md.relative_to(root)}: missing {rel}")
    for old in ("references/" + "output.md", "references/" + "lessons.md",
                "references/" + "dossier-format.md"):
        if old in text:
            bad.append(f"{md.relative_to(root)}: deprecated {old}")
maintainers = {p.name for p in (root / "maintainers").glob("*.md")}
if maintainers != {"lessons.md", "dossier-format.md"}:
    bad.append(f"maintainers/: expected lessons.md + dossier-format.md, got {sorted(maintainers)}")
agents = (root / "AGENTS.md").read_text()
if "## Documentation architecture" not in agents:
    bad.append("AGENTS.md: missing ## Documentation architecture")
for name in ("maintainers/lessons.md", "maintainers/dossier-format.md"):
    if name not in agents:
        bad.append(f"AGENTS.md: not linked from read order: {name}")
for name in ("NOTES.md", "TODO.md", "SUMMARY.md", "PLAN.md"):
    for path in (root / name, root / "maintainers" / name):
        if path.exists():
            bad.append(f"scratch doc committed: {path.relative_to(root)}")
runtime_docs = [root / "SKILL.md", root / "MAINTAINERS.md", root / "AGENTS.md",
                *sorted((root / "references").glob("*.md"))]
for md in runtime_docs:
    text = md.read_text()
    rel = md.relative_to(root)
    if re.search(r"\brule-\d+|\bstage[s]? \d", text):
        bad.append(f"{rel}: stale rule/stage number")
    if "self-audit" in text:
        bad.append(f"{rel}: self-audit is not a runtime step")
    if "caller declines" in text:
        bad.append(f"{rel}: adversarial review is mandatory when available")
    if "glossary info" in text or "reports (info, not a warning)" in text:
        bad.append(f"{rel}: glossary severity is a warning")
authoring = (root / "references" / "authoring.md").read_text()
for line in authoring.splitlines():
    if line.startswith("Optional fields:") and "evidence_quote" in line:
        bad.append("references/authoring.md: evidence_quote is a KC field, not a card field")
video = (root / "references" / "video.md").read_text()
for stale in ("first pixel path", "Use image-vision first"):
    if stale in video:
        bad.append(f"references/video.md: stale media policy: {stale}")
if not re.search(r"`direct` candidates may attach", (root / "SKILL.md").read_text()):
    bad.append("SKILL.md: missing direct/confirm media policy")
if bad:
    print("\n".join(bad), file=sys.stderr)
    raise SystemExit(1)
PY
pass "docs paths"
python3 - "$ROOT" <<'PY' || fail "runbook contract audit"
import sys
from pathlib import Path
root = Path(sys.argv[1])
skill = (root / "SKILL.md").read_text()
bad = [name for name in ("authoring_ledger.md", "make_cards.py", "new_cards.C",
                         "NOT CERTIFIED") if name in skill]
if bad:
    print(f"SKILL.md retains legacy runtime surface: {bad}", file=sys.stderr)
    raise SystemExit(1)
if "kcs.md" not in skill or "pipeline.py" not in skill:
    print("SKILL.md is missing the KC gate or the one pipeline entry point", file=sys.stderr)
    raise SystemExit(1)
if len(skill.splitlines()) > 300:
    print(f"SKILL.md is {len(skill.splitlines())} lines; keep the runbook under 300",
          file=sys.stderr)
    raise SystemExit(1)
PY
pass "runbook contract"


python3 "$SCRIPTS/pipeline.py" --gates-only --out "$WORK/pipeline-test" >/dev/null 2>&1 \
  && fail "pipeline accepted --gates-only without --cards"
python3 "$SCRIPTS/media_index.py" "$WORK/does-not-exist" >/dev/null 2>&1 \
  && fail "media_index accepted a missing directory"
python3 "$SCRIPTS/cardid.py" --help >/dev/null || fail "cardid.py rejected --help"
python3 "$SCRIPTS/cardid.py" >/dev/null 2>&1 && fail "cardid.py accepted no path"
python3 "$SCRIPTS/pipeline.py" --cards "$WORK/cards.json" --gates-only --build \
  --out "$WORK/no-deck" --out-apkg "$WORK/no-deck.apkg" >/dev/null 2>&1 \
  && fail "pipeline built without --deck-name"
printf 'not a package\n' > "$WORK/fake.apkg"
if python3 "$SCRIPTS/validate_apkg.py" "$WORK/fake.apkg" \
    >"$WORK/fake.out" 2>"$WORK/fake.err"; then
  fail "validate_apkg accepted a non-package"
fi
grep -q "not an Anki package" "$WORK/fake.err" \
  || fail "validate_apkg did not explain the non-package"
grep -q "Traceback" "$WORK/fake.err" \
  && fail "validate_apkg dumped a traceback for a non-package"
pass "CLI guards"

python3 "$SCRIPTS/triage.py" "$WORK/cards.json" -o "$WORK/review_plan.json" \
  --per-topic 1 --max 3 >/dev/null || fail "triage"
python3 - "$WORK/review_plan.json" <<'PY' || fail "triage did not report media"
import json, sys
p = json.load(open(sys.argv[1]))
assert p["media_total"] == 1 and p["media_shown"] == 1, (p["media_total"], p["media_shown"])
PY
pass "triage reports media"

python3 - "$WORK/review_plan.json" "$WORK/stale_plan.json" <<'PY' \
  || fail "could not build a stale review plan"
import json, sys
p = json.load(open(sys.argv[1]))
p["entries"][0]["hash"] = "deadbeef" * 4
json.dump(p, open(sys.argv[2], "w"))
PY
status=0
python3 "$SCRIPTS/review_server.py" --cards "$WORK/cards.json" \
  --plan "$WORK/stale_plan.json" --out "$WORK/stale_feedback.jsonl" \
  --done-file "$WORK/stale_done" --idle-timeout 0.1 --port 0 \
  >"$WORK/stale.out" 2>"$WORK/stale.err" || status=$?
[ "$status" -ne 0 ] || fail "stale review plan did not abort"
grep -q "out of date" "$WORK/stale.err" || fail "stale plan abort did not explain"
pass "stale review plan aborts"

python3 "$SCRIPTS/build_apkg.py" "$WORK/cards.json" "$WORK/smoke.apkg" \
  --deck-name "SMOKE::TEST" --media --media-root "$WORK" \
  >/dev/null || fail "build_apkg"
pass "build_apkg (media)"

python3 "$SCRIPTS/validate_apkg.py" "$WORK/smoke.apkg" >/dev/null || fail "validate_apkg (real import)"
pass "validate_apkg (real import)"

# Media is opt-in: the same deck without --media must carry no files at all.
python3 "$SCRIPTS/build_apkg.py" "$WORK/cards.json" "$WORK/plain.apkg" \
  --deck-name "SMOKE::TEST" >/dev/null || fail "text-only build"
python3 - "$WORK/plain.apkg" <<'PY' || fail "text-only build bundled media"
import json, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    assert json.loads(z.read("media")) == {}, z.read("media")
    assert not [n for n in z.namelist() if n.isdigit()], z.namelist()
PY
pass "default build has no media"

# Over-cap media is downscaled before it would ever be skipped.
python3 - "$WORK/media/big.png" <<'PY'
import os, sys
from PIL import Image
Image.frombytes("RGB", (2400, 1200), os.urandom(2400 * 1200 * 3)).save(sys.argv[1])
PY
python3 - "$WORK/big.json" <<'PY'
import json, sys
json.dump([{"front": "Does the over-cap image survive?", "back": "It is downscaled, not dropped.",
            "layer": "L2", "topic": "Smoke", "objects": ["smoke_test"], "deck": "SMOKE::TEST",
            "source": "smoke p.5", "media": [{"file": "media/big.png", "side": "back", "caption": "big"}]}],
          open(sys.argv[1], "w"))
PY
python3 "$SCRIPTS/build_apkg.py" "$WORK/big.json" "$WORK/big.apkg" \
  --deck-name "SMOKE::TEST" --media --media-root "$WORK" >/dev/null || fail "downscale build"
python3 - "$WORK/big.apkg" <<'PY' || fail "over-cap image was not downscaled"
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    files = [i for i in z.infolist() if i.filename.isdigit()]
    assert files, "no media file bundled"
    assert max(i.file_size for i in files) <= 1_000_000, [i.file_size for i in files]
PY
pass "over-cap image is downscaled"

# Merge must be idempotent AND must not add a second copy of the notetypes.
python3 "$SCRIPTS/build_apkg.py" "$WORK/cards.json" "$WORK/merged.apkg" \
  --deck-name "SMOKE::TEST" --merge-existing "$WORK/smoke.apkg" >/dev/null || fail "merge"
python3 - "$WORK/smoke.apkg" "$WORK/merged.apkg" <<'PY' || fail "merge added duplicate notetypes"
import sqlite3, sys, tempfile, zipfile
from pathlib import Path
def count(p):
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(p) as z: z.extract("collection.anki2", td)
        con = sqlite3.connect(Path(td) / "collection.anki2")
        try: return con.execute("select count(*) from notetypes").fetchone()[0]
        finally: con.close()
a, b = count(sys.argv[1]), count(sys.argv[2])
if a != b:
    print(f"notetypes {a} -> {b}", file=sys.stderr); sys.exit(1)
PY
pass "merge keeps one notetype per kind"

# The documented log reduction must be runnable, not just prose.
printf '%s\n' '{"i":0,"hash":"h","score":5}' '{"i":0,"hash":"h","score":3}' > "$WORK/log.jsonl"
python3 "$SCRIPTS/cardid.py" "$WORK/log.jsonl" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["h"]["score"] == 3' \
  || fail "cardid last-row reduction"
pass "cardid reduces to the last row"

# A large image deck gets a bounded cross-section, never all of them.
python3 - "$WORK/many.json" <<'PY'
import json, sys
cards = [{"front": f"Image card {i} with a long enough front?", "back": "A long enough back.",
          "layer": "L2", "topic": f"T{i % 3}", "objects": ["x"], "deck": "X",
          "source": f"s p.{i}", "media": [{"file": f"media/f{i}.png"}]} for i in range(12)]
json.dump(cards, open(sys.argv[1], "w"))
PY
python3 "$SCRIPTS/triage.py" "$WORK/many.json" -o "$WORK/many_plan.json" --max 20 >/dev/null
python3 - "$WORK/many_plan.json" <<'PY' || fail "media cross-section"
import json, sys
p = json.load(open(sys.argv[1]))
assert p["media_total"] == 12, p["media_total"]
assert 3 <= p["media_shown"] <= 8, p["media_shown"]
PY
pass "media review is a bounded cross-section"

python3 "$SCRIPTS/review_server.py" --cards "$WORK/cards.json" \
  --media-root "$WORK" --plan "$WORK/review_plan.json" --out "$WORK/feedback.jsonl" \
  --idle-timeout 0.1 --port 0 >"$WORK/server.log" 2>&1 &
server_pid=$!

i=0
while [ "$i" -lt 25 ]; do
  URL="$(grep -oE 'http://127\.0\.0\.1:[0-9]+/' "$WORK/server.log" 2>/dev/null | head -1 || true)"
  [ -n "$URL" ] && break
  sleep 0.2
  i=$((i + 1))
done
[ -n "$URL" ] || fail "review server did not print a URL"
pass "review server up at $URL"

code="$(curl -s -m 3 -o /dev/null -w '%{http_code}' "$URL" || true)"
[ "$code" = "200" ] || fail "GET / returned $code, expected 200"
pass "GET / 200"

PAGE_HTML="$(curl -s -m 3 "$URL")" || fail "GET / page failed"
page_has() { case "$PAGE_HTML" in *"$1"*) return 0 ;; *) return 1 ;; esac; }
page_has 'const CARDS' || fail "page is missing the CARDS payload"
# Markers for the finish-ready and done screens.
for needle in 'function allMarked' 'id="finish-review"' '--finish-bg' 'finish-spotlight' \
              'prefers-reduced-motion' "You're done!" 'id="confetti"' 'function tryClose' \
              'setTimeout(tryClose, 6000)' "anki-gen $VERSION"; do
  page_has "$needle" || fail "page is missing $needle"
done
pass "page carries cards and the finish/done UI"

code="$(curl -s -m 3 -o /dev/null -w '%{http_code}' "${URL}media/media/pixel.png" || true)"
[ "$code" = "200" ] || fail "media route returned $code"
pass "media route 200"

CHROME="$(command -v google-chrome || command -v chromium || command -v chromium-browser || true)"
if [ -n "$CHROME" ]; then
  DOM="$(timeout 25 "$CHROME" --headless=new --disable-gpu --no-sandbox \
         --virtual-time-budget=6000 --dump-dom "$URL" 2>/dev/null || true)"
  printf '%s' "$DOM" | python3 -c '
import re, sys
dom = sys.stdin.read()
m = re.search(r"id=\"sheet\"[^>]*>(.*?)</div>\s*</div>", dom, re.S)
ok = bool(m) and len(m.group(1).strip()) > 40
sys.exit(0 if ok else 1)
' || fail "review page rendered an empty #sheet (JS error)"
  pass "review page renders a card"
else
  printf 'skip  headless browser not found; render assertion skipped\n'
fi

curl -s -m 3 -X POST -H 'Content-Type: application/json' \
  --data '{"n":1,"i":1,"score":1,"comment":"too easy"}' \
  "${URL%/}/feedback" >/dev/null || fail "POST /feedback"
python3 - "$WORK/feedback.jsonl" <<'FEEDBACK' || fail "feedback row was not stored"
import json, sys
rows = [json.loads(x) for x in open(sys.argv[1]) if x.strip()]
assert any(r.get("score") == 1 and r.get("comment") == "too easy" for r in rows), rows
FEEDBACK
pass "POST /feedback stores a row"

code="$(curl -s -m 3 -o /dev/null -w '%{http_code}' -X POST \
  -H 'Origin: https://evil.example' -H 'Content-Type: application/json' \
  --data '{"n":1,"i":1,"score":5}' "${URL%/}/feedback" || true)"
[ "$code" = "403" ] || fail "cross-origin feedback was not rejected"
code="$(curl -s -m 3 -o /dev/null -w '%{http_code}' -X POST \
  -H 'Content-Type: text/plain' --data '{"n":1,"i":1,"score":5}' \
  "${URL%/}/feedback" || true)"
[ "$code" = "415" ] || fail "non-JSON feedback was not rejected"
pass "review server rejects cross-origin and non-JSON feedback"

curl -s -m 3 -X POST "${URL%/}/finish" >/dev/null 2>&1 || true
[ -f "$WORK/review_done" ] || fail "finish sentinel was not written beside the feedback log"
[ ! -e "./review_done" ] || fail "finish sentinel leaked into the caller cwd"
i=0
while [ "$i" -lt 25 ]; do
  kill -0 "$server_pid" 2>/dev/null || break
  sleep 0.2
  i=$((i + 1))
done
if kill -0 "$server_pid" 2>/dev/null; then
  sleep 1   # let the idle-timeout backstop finish it
fi
kill -0 "$server_pid" 2>/dev/null && fail "review server did not self-exit"
server_pid=""
pass "review server self-exited"

python3 "$SCRIPTS/review_server.py" --cards "$WORK/cards.json"   --plan "$WORK/review_plan.json" --out "$WORK/review_recall.jsonl"   --done-file "$WORK/recall_done" --ask recall --idle-timeout 0.1 --port 0   >"$WORK/recall_server.log" 2>&1 &
recall_pid=$!
i=0
while [ "$i" -lt 25 ]; do
  RECALL_URL="$(grep -oE 'http://127\.0\.0\.1:[0-9]+/' "$WORK/recall_server.log" 2>/dev/null | head -1 || true)"
  [ -n "$RECALL_URL" ] && break
  sleep 0.2
  i=$((i + 1))
done
[ -n "$RECALL_URL" ] || fail "recall review server did not print a URL"
curl -s -m 3 "$RECALL_URL" | grep -q 'const MODE = "recall"' || fail "recall mode page marker"
curl -s -m 3 -X POST -H 'Content-Type: application/json'   --data '{"n":1,"i":1,"recall":false}' "${RECALL_URL%/}/feedback" >/dev/null || fail "recall feedback POST"
curl -s -m 3 -X POST "${RECALL_URL%/}/finish" >/dev/null 2>&1 || true
python3 - "$WORK/review_recall.jsonl" <<'RECALL'
import json, sys
rows = [json.loads(x) for x in open(sys.argv[1]) if x.strip()]
assert any(r.get("recall") is False for r in rows), rows
RECALL
i=0
while [ "$i" -lt 25 ]; do
  kill -0 "$recall_pid" 2>/dev/null || break
  sleep 0.2
  i=$((i + 1))
done
kill -0 "$recall_pid" 2>/dev/null && fail "recall review server did not self-exit"
recall_pid=""
pass "recall-mode review stores a false row"

python3 "$ROOT/tests/hardening.py" || fail "hardening checks"
pass "hardening checks"

python3 "$ROOT/tests/visual_hardening.py" || fail "visual hardening"
pass "visual hardening"

python3 "$ROOT/tests/video_hardening.py" || fail "video hardening"
pass "video hardening"

python3 "$ROOT/tests/slides_hardening.py" || fail "slides hardening"
pass "slides hardening"

python3 "$ROOT/tests/local_media_hardening.py" || fail "local media hardening"
pass "local media hardening"

python3 "$ROOT/tests/pipeline_hardening.py" || fail "pipeline hardening"
pass "pipeline hardening"

python3 "$ROOT/tests/context_hardening.py" || fail "context hardening"
pass "context hardening"

python3 "$ROOT/tests/revision_hardening.py" || fail "revision hardening"
pass "revision hardening"

python3 "$ROOT/tests/quality_precision.py" || fail "quality precision"
pass "quality precision"

bash "$ROOT/tests/install_test.sh" || fail "installer/upgrade"
pass "installer/upgrade"

AFTER_STATUS="$(git -C "$ROOT/.." status --porcelain --untracked-files=all 2>/dev/null || true)"
AFTER_JUNK="$(find "$ROOT/.." -maxdepth 1 \( -name '*.apkg' -o -name 'review_done' -o -name '.anki-gen-temp' \) -print 2>/dev/null | sort)"
if [ "$AFTER_STATUS" != "$BEFORE_STATUS" ] || [ "$AFTER_JUNK" != "$BEFORE_JUNK" ]; then
  fail "test changed the working tree or left files behind"
fi
pass "no test litter in the working tree"

printf '\nPASS  anki-gen smoke test\n'
