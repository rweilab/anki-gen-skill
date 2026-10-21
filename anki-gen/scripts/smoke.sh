#!/usr/bin/env bash
# anki-gen maintainer smoke test — NOT part of a normal deck run.
#
# Exercises the whole mechanical path on a three-card fixture under $TMPDIR, then
# asserts the review page actually renders a card. Cleans up after itself and never
# kills a process: it asks the review server to finish (POST /finish) and lets its
# own idle-timeout be the backstop.
#
#   bash scripts/smoke.sh
#   KEEP_WORK=1 bash scripts/smoke.sh      # keep the temp tree on failure
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
  KEEP_WORK=1
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
from review_server import render_cloze
from render import to_html
answer = r"$Q_v$ and **two**"
preview = render_cloze("{{c1::" + answer + "}}", True)
assert r"\(Q_v\)" in preview and "<b>two</b>" in preview, preview
assert to_html(answer) in preview, (to_html(answer), preview)
assert "$Q_v$" not in preview
hint = render_cloze("{{c1::answer::$h$}}", False)
assert r"\(h\)" in hint, hint
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

python3 "$SCRIPTS/pipeline.py" --gates-only --out "$WORK/pipeline-test" >/dev/null 2>&1 \
  && fail "pipeline accepted --gates-only without --cards"
python3 "$SCRIPTS/media_index.py" "$WORK/does-not-exist" >/dev/null 2>&1 \
  && fail "media_index accepted a missing directory"
pass "CLI guards"

python3 "$SCRIPTS/triage.py" "$WORK/cards.json" -o "$WORK/review_plan.json" \
  --per-topic 1 --max 3 >/dev/null || fail "triage"
python3 - "$WORK/review_plan.json" <<'PY' || fail "triage did not report media"
import json, sys
p = json.load(open(sys.argv[1]))
assert p["media_total"] == 1 and p["media_shown"] == 1, (p["media_total"], p["media_shown"])
PY
pass "triage reports media"

python3 "$SCRIPTS/build_apkg.py" "$WORK/cards.json" "$WORK/smoke.apkg" \
  --deck-name "SMOKE::TEST" --strict --media --media-root "$WORK" \
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
  --done-file "$WORK/done" --idle-timeout 0.1 --port 0 >"$WORK/server.log" 2>&1 &
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

curl -s -m 3 "$URL" | grep -q 'const CARDS' || fail "page is missing the CARDS payload"
pass "page carries the card payload"

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

curl -s -m 3 -X POST "${URL%/}/finish" >/dev/null 2>&1 || true
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

python3 "$ROOT/tests/hardening.py" || fail "hardening checks"
pass "hardening checks"

python3 "$ROOT/tests/video_hardening.py" || fail "video hardening"
pass "video hardening"

bash "$ROOT/tests/install_test.sh" || fail "installer/upgrade"
pass "installer/upgrade"

printf '\nPASS  anki-gen smoke test\n'
