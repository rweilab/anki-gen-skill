#!/usr/bin/env python3
"""Local review surface for a generated deck.

WHY THIS EXISTS
---------------
Review used to happen in the chat: the agent printed every card's full front and
back and the user answered y/n/e/s/q. Two problems. Every card's text passed
through the conversation, which for a 60+ card deck is a large amount of context
spent on text that never needed to be there. And the answer set collapsed to
accept/reject/edit, so it could not express "too hard for my current skillset" or
"I already know this cold" -- the two signals that should drive cutting and
splitting.

So review happens here instead: a throwaway page on localhost, scored 1-5.

FIDELITY IS THE POINT
---------------------
Preview fidelity rests on this module importing render.py rather than
re-implementing it. to_html(), with_source() and CSS are the SAME code the build
path uses, so what is reviewed is what ships. If render ever gets inlined into
this file, preview and deck drift apart silently -- which is the exact failure
rule 1 exists to prevent. Do not do that.

The one piece of rendering NOT shared with the build path is cloze expansion:
Anki applies its own `cloze:` filter, which a browser does not have. That is the
most likely source of a preview/deck mismatch, so it is kept small and obvious.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cardid import card_hash, load_cards                 # noqa: E402
from render import to_html, with_source, CSS  # noqa: E402
import media  # noqa: E402

# Vendored MathJax. One self-contained file with the glyphs embedded as SVG
# paths -- deliberately NOT the chtml bundle, which lazily fetches font files
# relative to its own script URL and would 404 once copied out of the CDN. Local
# means review works with no network, and it is the same engine Anki bundles, so
# the preview is what the deck will show.
#
# Resolved from this file rather than the cwd, so the server can be launched from
# any directory.
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
MATHJAX_URL = "/assets/mathjax/tex-svg.js"
MATHJAX_PATH = ASSETS_DIR / "mathjax" / "tex-svg.js"
SKILL_VERSION = ((ASSETS_DIR.parent / "VERSION").read_text().strip()
                 if (ASSETS_DIR.parent / "VERSION").is_file() else "unknown")

# ------------------------------------------------------------------ cloze
# Non-greedy to the FIRST '}}' -- deliberately matching Anki's own parser, which
# is why braces inside a deletion are forbidden (validate_cards enforces that at
# build time; this module does not re-check it, because a malformed deletion is
# already caught before review ever runs).
CLOZE_RE = re.compile(r"\{\{c(\d+)::(.*?)\}\}", re.DOTALL)

# Internal marker for a deletion while markdown is converted. Chosen to survive
# _esc() and every _inline() regex untouched.
_TOK = "\x01c{}\x01"


def _split_hint(body: str) -> tuple[str, str]:
    """`answer::hint` -> (answer, hint). Anki shows the hint inside the blank."""
    if "::" in body:
        answer, hint = body.split("::", 1)
        return answer, hint
    return body, ""


def render_cloze(text: str, reveal: bool) -> str:
    """Expand Anki cloze syntax into rendered HTML.

    front (reveal=False) -> every deletion becomes a blank marker
    back  (reveal=True)  -> every deletion becomes its answer, highlighted
    """
    marks: list[tuple[str, str]] = []

    def grab(m):
        marks.append(_split_hint(m.group(2)))
        return _TOK.format(len(marks) - 1)

    out = to_html(CLOZE_RE.sub(grab, text))
    for i, (answer, hint) in enumerate(marks):
        if reveal:
            repl = f'<span class="cloze-reveal">{to_html(answer)}</span>'
        else:
            label = to_html(hint) if hint else "&hellip;"
            repl = f'<span class="cloze-blank">[{label}]</span>'
        out = out.replace(_TOK.format(i), repl)
    return out


# ------------------------------------------------------------------ cards
META = '<div class="meta">{topic}</div>'

# Same topic-first rule as build_native.py: the label is the chapter name, not
# the internal layer code. The browser-side mapping lives in APP_JS.
def render_cards(cards: list[dict], plan_entries: list[dict] | None = None,
                 media_root: str | None = None) -> list[dict]:
    """Build the front/back HTML for every card, mirroring build_native's templates.

    Basic:  qfmt=META+{{Front}}          afmt={{FrontSide}}<hr>{{Back}}
    Cloze:  qfmt={{cloze:Text}}+META     afmt={{cloze:Text}}<hr>{{Extra}}

    Mirroring the templates exactly is what makes the review page show the card
    the deck will show, rather than a plausible-looking approximation of it.

    With `plan_entries` (from triage.py), each card carries the reason it was
    selected and is numbered by its position in cards.json rather than by its
    place in the subset -- so a card keeps the number every other script, and the
    feedback log, calls it by.
    """
    out = []
    for n, c in enumerate(cards, 1):
        e = plan_entries[n - 1] if plan_entries else None
        layer = str(c.get("layer", ""))
        topic = str(c.get("topic", ""))
        source = str(c.get("source") or c.get("source_ref") or "")
        source_url = str(c.get("source_url") or "")
        meta = META.format(topic=html.escape(topic))
        objects = [str(o) for o in (c.get("objects") or [])]
        if objects:
            # The tags a reviewer could search the deck by, shown where they can
            # see them. Object tags are the point of the whole scheme: they are
            # how "every card about FCC" is found without a cross-reference.
            meta += ('<div class="objects">'
                     + html.escape(" · ".join(objects))
                     + "</div>")

        # Media is shown in review whether or not the deck bundle had --media:
        # the auditor is checking the intended image. A missing file becomes a
        # visible placeholder, not a silent broken <img>.
        front_imgs, back_imgs = [], []
        media_items = media.items(c)
        media_src, media_url = media.primary_source(media_items)
        if media_src:
            source = media_src
            source_url = media_url or source_url
        for m in media_items:
            try:
                missing = not media.resolve(media_root or ".", m["file"]).is_file()
            except ValueError:
                missing = True
            snippet = media.img_html(f"/media/{m['file']}", m["caption"], missing)
            (front_imgs if m["side"] == "front" else back_imgs).append(snippet)

        if c.get("cloze"):
            text = str(c.get("front", ""))
            front = render_cloze(text, reveal=False) + "".join(front_imgs) + meta
            back = (render_cloze(text, reveal=True)
                    + '<hr id="answer">'
                    + with_source(to_html(str(c.get("back", ""))) + "".join(back_imgs),
                                  source, source_url))
        else:
            front = meta + to_html(str(c.get("front", ""))) + "".join(front_imgs)
            back = (front
                    + '<hr id="answer">'
                    + with_source(to_html(str(c.get("back", ""))) + "".join(back_imgs),
                                  source, source_url))

        out.append({
            "n": e["i"] if e else n,
            # Same content hash build_native.py uses for the note GUID, so a score
            # in the log can be traced back to the exact note it referred to, even
            # after cards have been reordered. One definition, in cardid.py, so
            # this cannot drift from the builder's.
            "hash": e["hash"] if e else card_hash(c),
            "front": front,
            "back": back,
            "topic": topic,
            "layer": layer,
            "cloze": bool(c.get("cloze")),
            # Why triage chose this card. Shown above it, so the reviewer is never
            # guessing what a card is doing in front of them.
            "kind": e["kind"] if e else "",
            "why": list(e.get("reasons") or []) if e else [],
        })
    return out


# ------------------------------------------------------------------ state
def row_key(row: dict) -> str:
    """Card identity, not array position: hash, then note number, then old index."""
    h = row.get("hash")
    if h:
        return str(h)
    n = row.get("n")
    if n is not None:
        return str(n)
    i = row.get("i")
    return str(i) if i is not None else ""


class Store:
    """Append-only feedback log. One JSON object per line, last write wins.

    Append-per-event is what makes closing the tab harmless, and re-reading the
    log on load is what makes reopening it resume. Rows are keyed by card
    identity, not by the current review subset's array position.
    """

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.rows: dict[str, dict] = {}
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                key = row_key(r)
                if key:
                    self.rows[key] = r

    def put(self, row: dict) -> None:
        with self.lock:
            self.rows[row_key(row)] = row
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(row) + "\n")

    def state(self) -> dict:
        with self.lock:
            return {k: v for k, v in sorted(self.rows.items())}


# ------------------------------------------------------------------ page
APP_CSS = """
/* Only the app chrome is themed here. The card content keeps the deck's own CSS
   (render.py), so what you read in the review page is what Anki will show. */
:root{
  /* gruvbox light. --bg is bg0 = light0 = #fbf1c7: the classic gruvbox light
     background, a warm cream. Do NOT switch it to light0_hard (#f9f5d7): that is
     the *hard contrast* variant, deliberately the palest and least saturated, and
     against the card's near-white paper it reads as a sickly olive rather than
     cream. Colours here are from morhetz/gruvbox colors/gruvbox.vim.
     In gruvbox, light1 (#ebdbb2) is a selection/hover tint, not a surface -- an
     earlier version filled the header, controls and sidebar with it and the whole
     page read as tan blocks. Structure comes from 1px borders instead; light1 is
     only used for small areas (keycaps, hover, a cloze blank). */
  color-scheme:light;    /* NOT a Dark Reader signal -- DR reads this to spot a site that
                            is natively DARK and leave it alone, so declaring "light" only
                            tells it this is a light page (which it would darken anyway).
                            The protection is the darkreader-lock meta tag in PAGE. This
                            line is for the BROWSER: form controls, focus rings and
                            scrollbars render light instead of following the OS dark
                            preference and putting dark widgets on cream. */
  --bg:#fbf1c7;          /* bg0 / light0 -- cream. The page and the card stage. */
  --panel:#fbf1c7;       /* light: panels match the page; dark mode lifts them
                            (see the dark block below, which follows gruvbox's
                            editor-bg / chrome-bg / cursorline division) */
  --raised:#ebdbb2;      /* light1 -- small areas only */
  --raised-soft:#f2e5bc; /* light0_soft -- the gentlest raised tint */
  --on-accent:#fbf1c7;   /* text sitting ON a saturated fill (a scored index
                            button, an active score, the Next button) */
  --border:#d5c4a1;      /* light2 */
  --border-strong:#bdae93; /* light3 */
  --fg:#282828;          /* fg0 -- the high-contrast foreground */
  --fg-dim:#665c54;      /* fg3 */
  --muted:#928374;       /* gray */
  --red:#9d0006; --green:#79740e; --yellow:#b57614; --blue:#076678;
  --purple:#8f3f71; --aqua:#427b58; --orange:#af3a03;
  /* Finish-ready state: gruvbox faded blue on light. */
  --finish-bg:#076678; --finish-fg:#fbf1c7;
}

/* ---------------------------------------------------------------------- dark
   gruvbox DARK at hard contrast: the page is dark0_hard (#1d2021). The role
   assignment is gruvbox's own, taken from colors/gruvbox.vim rather than invented:
   page = bg0 (Normal's background), chrome = bg1 (CursorLine / StatusLineNC),
   raised surfaces and small fills = bg2 (Pmenu), dividers = bg3 (VertSplit), body
   text = fg1 (Normal's foreground), muted = gray (Comment), and the accents are the
   BRIGHT set -- gruvbox maps its accent names to bright_* in dark mode and to
   faded_* in light mode, which is exactly the switch made here (see :root above).

   Note fg0 is light0 (#fbf1c7), not light0_hard: in gruvbox "hard contrast" moves
   the BACKGROUND floor only; the text ramp does not change.

   The card itself is deliberately not themed here. It is styled by render.py's CSS,
   the same file the deck ships, and its .night_mode block is what Anki applies in
   night mode -- so the preview goes on showing the deck rather than a page-only idea
   of it. The .sheet wrapper is page chrome, so it is themed below. */
:root[data-theme="dark"]{
  color-scheme:dark;     /* browser widgets (scrollbars, textarea) follow the theme */
  --bg:#1d2021;          /* dark0_hard -- high-contrast background */
  --panel:#282828;       /* dark0 -- chrome one step above the page */
  --raised:#3c3836;      /* dark1 -- keycaps, hover, a cloze blank */
  --raised-soft:#32302f; /* dark0_soft -- pairs with light's light0_soft. Must be
                            restated here: custom properties inherit, so leaving it
                            out keeps the LIGHT cream and puts a cloze reveal's
                            light text on a light highlight */
  --border:#504945;      /* dark2 */
  --border-strong:#665c54; /* dark3 */
  --fg:#fbf1c7;          /* fg0 == light0 */
  --fg-dim:#bdae93;      /* fg3 */
  --muted:#928374;       /* gray */
  --red:#fb4934; --green:#b8bb26; --yellow:#fabd2f; --blue:#83a598;
  --purple:#d3869b; --aqua:#8ec07c; --orange:#fe8019;
  --on-accent:#1d2021;   /* the accent fills are bright here, so their text is dark */
  /* Finish-ready state: gruvbox bright blue on dark. */
  --finish-bg:#83a598; --finish-fg:#1d2021;
}
/* The sheet keeps the PAGE colour in dark mode, not the panel colour: the card it
   holds is styled by the deck (#2b2b2e in its night rules), and gruvbox layers
   surfaces with the work area darkest and content raised above it. Putting the
   sheet at --panel would have left the card almost flush with its own frame. */
:root[data-theme="dark"] .sheet{background:var(--bg);border-color:var(--border)}
*{box-sizing:border-box}
/* `.scores{display:flex}` below would otherwise beat the UA's [hidden] rule, so the
   hidden panels (the recall question in scale mode, and vice versa) would show. */
[hidden]{display:none!important}
html,body{margin:0;padding:0;background:var(--bg);color:var(--fg);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  /* Text is sized in rem, so it follows the reader's browser font-size setting rather than
     being pinned to pixels; control minimums scale with their labels, and the card index uses
     em against its own 12px label (30x26 at default). Borders and spacing stay px: zoom scales
     those anyway, and a 1px hairline must not scale at all. */
  font-size:.9375rem}
/* One row, two columns. The sidebar width is a clamp, not a constant: a fixed 230px is a
   sliver beside a 52em card on a wide monitor, and it swallows the card in a half-screen
   window. px inside clamp is right -- those two ends are guards, not rhythm. dvh follows the
   visible viewport, so it survives browser chrome and zoom changing what 100vh means. */
body{display:grid;grid-template-columns:clamp(200px,17vw,290px) 1fr;height:100vh;height:100dvh}
/* The sidebar carries what the top bar used to: every pixel the header took came out of
   the card's height, and the card is the thing being read. */
.side-head{padding:10px 12px 9px;border-bottom:1px solid var(--border)}
aside h1{font-size:0.8125rem;margin:0 0 8px;font-weight:600;letter-spacing:.02em;line-height:1.35;
  color:var(--fg)}
.side-btns{display:flex;align-items:center;gap:6px}
.counts{margin-top:7px;color:var(--fg-dim);font-size:0.75rem;font-variant-numeric:tabular-nums}
.counts .sep{color:var(--muted);margin:0 3px}
.version{color:var(--muted);font-size:0.6875rem;margin-top:3px}
.hdrbtn{background:var(--panel);border:1px solid var(--border-strong);border-radius:6px;
  padding:6px 12px;font-size:0.8125rem;color:var(--fg);cursor:pointer;min-width:4.125rem;
  display:inline-flex;align-items:center;justify-content:center}
.hdrbtn:hover{background:var(--raised)}
.hdrbtn.ready{background:var(--finish-bg);border-color:var(--finish-bg);color:var(--finish-fg);
  font-weight:600;box-shadow:0 0 0 2px var(--bg),0 0 0 4px var(--finish-bg);
  animation:finish-spotlight 1.2s ease-out 1}
@keyframes finish-spotlight{
  0%{transform:scale(1);box-shadow:0 0 0 2px var(--bg),0 0 0 4px var(--finish-bg),0 0 0 var(--finish-bg)}
  35%{transform:scale(1.07);box-shadow:0 0 0 3px var(--bg),0 0 0 10px var(--finish-bg),0 0 24px var(--finish-bg)}
  100%{transform:scale(1);box-shadow:0 0 0 2px var(--bg),0 0 0 4px var(--finish-bg),0 0 0 transparent}}
@media (prefers-reduced-motion:reduce){.hdrbtn.ready{animation:none}}
#themebtn{min-width:34px;padding:6px 8px}
.icon{width:16px;height:16px;display:block}
/* The button shows the theme you would get, not the one you are in: a moon while the page
   is light ("go dark"), a sun while it is dark. Only one of the two is ever displayed. */
.icon-sun{display:none}
:root[data-theme="dark"] .icon-moon{display:none}
:root[data-theme="dark"] .icon-sun{display:block}
/* The card's own number in cards.json -- under a triage plan the position in the
   subset and the card number differ, and every other script means the latter. */
.cardno{color:var(--muted);font-size:0.75rem;font-variant-numeric:tabular-nums}
.bar{position:absolute;left:0;right:0;top:-1px;height:2px;background:var(--border)}
.bar>i{display:block;height:100%;background:var(--aqua);width:0}

.side-index{flex:1;min-height:0;overflow-y:auto;padding-bottom:8px}
.side-keys{border-top:1px solid var(--border);padding-bottom:26px}  /* sits clear of the
                                                                        corner rather than in it */
aside{background:var(--panel);border-right:1px solid var(--border);display:flex;
  flex-direction:column;min-height:0}
aside h2{font-size:0.625rem;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);
  margin:14px 12px 6px}
.idx{display:flex;flex-wrap:wrap;gap:4px;padding:0 12px}
.idx button{width:2.5em;height:2.1667em;border:1px solid var(--border);background:var(--panel);
  color:var(--fg-dim);border-radius:4px;font-size:0.75rem;cursor:pointer;font-variant-numeric:tabular-nums}
.idx button:hover{background:var(--raised);border-color:var(--border-strong);color:var(--fg)}
.idx button[data-cur="1"]{outline:2px solid var(--blue);outline-offset:1px}
.idx button[data-s="1"]{background:var(--aqua);color:var(--on-accent);border-color:var(--aqua)}
.idx button[data-s="2"]{background:var(--blue);color:var(--on-accent);border-color:var(--blue)}
.idx button[data-s="3"]{background:var(--yellow);color:var(--on-accent);border-color:var(--yellow)}
.idx button[data-s="4"]{background:var(--orange);color:var(--on-accent);border-color:var(--orange)}
.idx button[data-s="5"]{background:var(--red);color:var(--on-accent);border-color:var(--red)}
.keys{padding:8px 14px 4px;color:var(--fg-dim);font-size:0.75rem;display:grid;
  grid-template-columns:auto 1fr;gap:5px 10px;align-items:baseline}
.keys .k{white-space:nowrap;text-align:right}
.keys .l{color:var(--fg-dim)}
.keys kbd{background:var(--raised);border:1px solid var(--border-strong);border-bottom-width:2px;
  border-radius:4px;padding:1px 5px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:0.6875rem;
  color:var(--fg)}

main{display:flex;flex-direction:column;overflow:hidden}
.stage{flex:1;overflow-y:auto;padding:22px;
  /* Fixed floor so flipping to a long back does not shove the controls upwards. */
  min-height:52vh}
.sheet{max-width:52em;margin:0 auto;cursor:pointer;background:#fdfdfb;border:1px solid var(--border);
  border-radius:8px;padding:4px 2px;box-shadow:0 1px 3px rgba(60,56,54,.10)}

.cloze-blank{background:var(--raised);border-bottom:2px solid var(--border-strong);
  border-radius:3px;padding:0 7px;font-weight:600;color:var(--fg-dim)}
.cloze-reveal{background:var(--raised-soft);border-bottom:2px solid var(--aqua);
  border-radius:3px;padding:0 5px;font-weight:600}

.controls{position:relative;border-top:1px solid var(--border-strong);background:var(--panel);
  padding:10px 16px;display:flex;flex-wrap:wrap;gap:14px;align-items:flex-start}
/* The prompt above the buttons. flex-basis:100% puts it on its own line inside the
   wrapping flex row, so the buttons keep their own row underneath. */
.lead{flex-basis:100%;margin:0 0 2px;color:var(--fg);font-size:0.8125rem}
.scores{display:flex;gap:6px;flex-wrap:wrap}
.scores button{border:1px solid var(--border-strong);background:var(--panel);color:var(--fg);
  border-radius:6px;padding:7px 12px;cursor:pointer;font-size:0.8125rem;line-height:1.25;text-align:left;
  min-width:6rem}
.scores button b{display:block;font-size:0.6875rem;opacity:.65;font-weight:600}
.scores button[data-on="1"]{border-color:transparent;color:var(--on-accent)}
.scores button[data-k="1"][data-on="1"]{background:var(--aqua)}
.scores button[data-k="2"][data-on="1"]{background:var(--blue)}
.scores button[data-k="3"][data-on="1"]{background:var(--yellow)}
.scores button[data-k="4"][data-on="1"]{background:var(--orange)}
.scores button[data-k="5"][data-on="1"]{background:var(--red)}
/* --ask recall: the binary rule-9 question, in place of the 1-5 scale. Same
   button treatment so the page does not change shape between modes. */
.recall{display:flex;gap:6px;flex-wrap:wrap}
.recall button{border:1px solid var(--border-strong);background:var(--panel);color:var(--fg);
  border-radius:6px;padding:7px 14px;cursor:pointer;font-size:0.8125rem;line-height:1.25;
  text-align:left;min-width:10.5rem}
.recall button b{display:block;font-size:0.6875rem;opacity:.65;font-weight:600}
.recall button[data-on="1"]{border-color:transparent;color:var(--on-accent)}
.recall button[data-r="1"][data-on="1"]{background:var(--aqua)}
.recall button[data-r="0"][data-on="1"]{background:var(--red)}
.comment{flex:1;min-width:16.25rem}
.comment textarea{width:100%;min-height:58px;resize:vertical;background:var(--bg);
  border:1px solid var(--border-strong);border-radius:6px;padding:7px 9px;font:inherit;
  font-size:0.8125rem;color:var(--fg)}
.nav{display:flex;gap:6px;align-items:center}
.nav button{background:var(--panel);border:1px solid var(--border-strong);border-radius:6px;
  padding:7px 12px;font-size:0.8125rem;color:var(--fg);cursor:pointer}
.nav .go{background:var(--aqua);border-color:var(--aqua);color:var(--on-accent);font-weight:600}

.overlay{position:fixed;inset:0;background:rgba(60,56,54,.55);display:none;
  align-items:center;justify-content:center;padding:20px}
.overlay.on{display:flex}
.summary{position:relative;background:var(--panel);border:1px solid var(--border-strong);
  border-radius:10px;max-width:44em;width:100%;max-height:86vh;overflow-y:auto;padding:20px 24px}
.summary h3{margin:0 0 4px;font-size:1.0625rem}
.summary p{color:var(--fg-dim);font-size:0.8125rem;margin:0 0 14px}
.summary table{border-collapse:collapse;width:100%;font-size:0.8125rem;margin:0 0 16px}
.summary th,.summary td{border-bottom:1px solid var(--border);padding:5px 8px;text-align:left}
.summary td.n{width:3em;color:var(--muted);font-variant-numeric:tabular-nums}
.summary ul{margin:0 0 16px;padding-left:18px;font-size:0.8125rem}
.decknote{display:block;margin:0 0 18px;font-size:0.8125rem;font-weight:600}
.decknote span{display:block;font-weight:400;color:var(--fg-dim);margin:2px 0 6px}
.decknote textarea{width:100%;min-height:62px;resize:vertical;background:var(--bg);
  border:1px solid var(--border-strong);border-radius:6px;padding:8px 10px;font:inherit;
  font-size:0.8125rem;color:var(--fg)}
#close-hint{color:var(--fg-dim);font-size:0.75rem;margin:10px 0 0}
.summary button{background:var(--aqua);border:0;border-radius:6px;color:var(--on-accent);
  padding:9px 16px;font-size:0.875rem;cursor:pointer}
.summary button:disabled{background:var(--border-strong);cursor:default}
.done{text-align:center;padding:18px 0 6px}
.done-check{width:58px;height:58px;margin:0 auto 10px;border-radius:50%;
  background:var(--aqua);color:var(--on-accent);font-size:34px;line-height:58px;font-weight:700}
.done h3{font-size:1.25rem;margin:0 0 6px}
.done p{color:var(--fg-dim);font-size:0.875rem;margin:0 0 16px}
.done b{color:var(--fg)}
.done-check,.done h3,.done p,.done button{position:relative;z-index:1}
.confetti{position:absolute;inset:0;overflow:hidden;pointer-events:none;z-index:0}
.confetti i{position:absolute;top:-12px;width:6px;height:10px;border-radius:1px;
  animation:confetti-fall 1.6s ease-in forwards}
@keyframes confetti-fall{to{transform:translateY(70vh) rotate(540deg);opacity:0}}
@media (prefers-reduced-motion:reduce){.confetti{display:none}}
"""

APP_JS = r"""
const el = (s) => document.querySelector(s);
// Keep in sync with LAYER_WORDS above. The template calls this from the index
// tooltip, so it has to exist in the browser as well as in Python.
const LAYER_WORDS = {L1:'Recall', L2:'Understanding', L3:'Boundary', Procedure:'Procedure'};
const layer_word = (code) => LAYER_WORDS[code] || code;
// Two modes. 'scale' is the 1-5 difficulty/keep scale. 'recall' replaces it with
// the binary rule-9 question: could you answer this without working it out?
//
// They are different axes and the difference is the point -- a card can be hard
// AND perfectly recallable, so "how hard was that?" cannot see a front that asks
// for a computed value. Rule 9 is the highest-stakes rule in the skill and this
// is its only enforcement.
const RECALL = MODE === 'recall';
let cur = 0, flipped = false;

// Same identity order as Store.row_key: hash, note number, then old index.
function cardKey(c){
  return c.hash ? String(c.hash) : (c.n !== undefined ? String(c.n) : String(c.i));
}

function allMarked(){
  return CARDS.every(c=>{
    const r = STATE[cardKey(c)] || {};
    return RECALL ? typeof r.recall === 'boolean' : r.score != null;
  });
}

function markFinishReady(){
  const ready = allMarked();
  const btn = el('#finish-review');
  if (!btn) return;
  btn.classList.toggle('ready', ready);
  btn.title = ready ? 'All cards marked — finish the review' : '';
}

function typeset(node){
  if (window.MathJax && MathJax.typesetPromise) {
    MathJax.typesetPromise([node]).catch(()=>{});
  }
}

function paint(){
  const c = CARDS[cur];
  el('#sheet').innerHTML = flipped ? c.back : c.front;
  typeset(el('#sheet'));
  el('#count').textContent = (cur+1) + ' / ' + CARDS.length;
  el('#cardno').textContent = 'card ' + c.n;
  el('#barfill').style.width = ((cur+1)/CARDS.length*100) + '%';

  // Nothing about WHY triage picked this card is on screen: that strip sat above the
  // card and pushed the answer below the fold on every flip. The reason lives in the
  // index button's tooltip instead (see buildIndex), where it costs no height.
  const r = STATE[cardKey(CARDS[cur])] || {};
  el('#comment').value = r.comment || '';
  if (RECALL) {
    document.querySelectorAll('.recall button').forEach(b=>{
      b.dataset.on = (r.recall === (b.dataset.r === '1')) ? '1' : '0';
    });
  } else {
    // Scoring 4 changes nothing about the layout: the comment box and the nav buttons
    // stay exactly where they are, so the row of controls never moves under the cursor.
    document.querySelectorAll('.scores button').forEach(b=>{
      b.dataset.on = (String(r.score) === b.dataset.k) ? '1' : '0';
    });
  }
  document.querySelectorAll('.idx button').forEach(b=>{
    b.dataset.cur = (Number(b.dataset.i) === cur) ? '1' : '0';
  });
  // Keep the current card's number visible in the sidebar. Without this, arrow-key
  // navigation scrolls the deck past the edge of a 72-card index and the reader
  // loses track of where they are.
  const curBtn = document.querySelector('.idx button[data-cur="1"]');
  if (curBtn && curBtn.scrollIntoView) curBtn.scrollIntoView({block: 'nearest'});
  markFinishReady();
}

function buildIndex(){
  const box = el('#idx');
  box.innerHTML = '';
  CARDS.forEach((c,i)=>{
    const b = document.createElement('button');
    b.textContent = c.n; b.dataset.i = i;
    // The triage reason rides in the tooltip rather than on the page: on screen it
    // pushed the card down and forced a scroll on every flip, but it is still worth
    // being able to hover a number and see why it is in the review set. title is set
    // as a property (not innerHTML), so quoting card text back cannot inject markup.
    b.title = 'card ' + c.n + '  ' + c.topic + '  [' + layer_word(c.layer) + ']'
              + ((c.why && c.why.length) ? '\n' + c.why.join('\n') : '');
    b.onclick = ()=>{ cur = i; flipped = false; paint(); };
    box.appendChild(b);
  });
}

function save(){
  const r = STATE[cardKey(CARDS[cur])] || {};
  const row = {i: cur, n: CARDS[cur].n, hash: CARDS[cur].hash,
               topic: CARDS[cur].topic,
               // Both verdict fields are written on every row, one of them null, so
               // a reader of the log never has to know which mode produced a row in
               // order to know what it means: `score` is null in recall mode, and
               // `recall` is null under the ordinary 1-5 scale. There is no `reason`
               // field: the dropdown that used to feed it was removed, and a card's
               // comment is where the explanation goes now.
               score: r.score ?? null,
               recall: r.recall ?? null,
               comment: el('#comment').value || null, cloze: CARDS[cur].cloze};
  STATE[cardKey(CARDS[cur])] = row;
  fetch('/feedback', {method:'POST', headers:{'Content-Type':'application/json'},
                      body: JSON.stringify(row)}).catch(()=>{});
  const b = document.querySelector('.idx button[data-i="'+cur+'"]');
  if (b) {
    b.dataset.s = RECALL
      ? (r.recall === true ? '1' : r.recall === false ? '5' : '')
      : (r.score ? String(r.score) : '');
  }
}

function score(k){
  if (RECALL) return;
  const r = STATE[cardKey(CARDS[cur])] || {};
  r.score = k; STATE[cardKey(CARDS[cur])] = r;
  save();
  paint();
  // Scoring deliberately does NOT advance, so a card can be scored and commented
  // before leaving it. Nothing about the layout changes for any score -- 4 included.
  // Move on with the arrow keys or the Next button.
}

function answerRecall(v){
  const r = STATE[cardKey(CARDS[cur])] || {};
  r.recall = v; STATE[cardKey(CARDS[cur])] = r;
  save();
  paint();
  // Same as scoring: answering does not advance, so the comment box stays
  // reachable for the card that just failed the recallability test.
}

function go(d){
  save();
  cur = Math.min(CARDS.length-1, Math.max(0, cur+d));
  flipped = false; paint();
}

// The card index is a wrapped grid, so up/down move by a ROW rather than by one card:
// that is the difference between scanning a 72-card deck in four presses and in
// seventy. The row width is read from the DOM (comparing buttons' offsetTop), so it
// follows the window size instead of a hard-coded column count.
function rowStep(){
  const btns = Array.from(document.querySelectorAll('.idx button'));
  if (btns.length < 2) return 1;
  const first = btns[0].offsetTop;
  for (let i = 1; i < btns.length; i++) {
    if (btns[i].offsetTop > first) return i;
  }
  return btns.length;                      // everything fits on one row
}

function goRow(d){ go(d * rowStep()); }

function flip(){ flipped = !flipped; paint(); }

// Entering the comment box, from c / i / a. `append` is vim's `a`: text goes on the end.
function focusComment(append){
  const box = el('#comment');
  box.focus();
  if (append) { const n = box.value.length; box.setSelectionRange(n, n); }
}

// Clicking the card flips it -- that is what the pointer cursor and the tooltip promise.
// Two guards, because a click is not always a flip request: a click that finishes a text
// selection is the reader copying the answer, and a click on a link inside a card is a
// link. Both should do nothing to the card's state.
function sheetClick(e){
  if (e.target.closest('a')) return;
  const sel = window.getSelection();
  if (sel && !sel.isCollapsed) return;
  flip();
}

document.addEventListener('keydown', (e)=>{
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  // Escape always drops focus, from anywhere -- the universal way out.
  if (e.key === 'Escape') { document.activeElement.blur(); return; }
  if (typing) {
    // Enter (with or without ctrl) commits the comment and hands the keyboard back to
    // the card, so the next keystroke is a score rather than more comment text. Without
    // this the box kept focus and every 1-5 went into the comment. Shift+Enter is left
    // alone, so it still inserts a newline.
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      el('#comment').blur();      // its onblur writes the row -- one row, not two
    }
    return;
  }
  // Every command below is a bare keystroke. A modified one belongs to the browser --
  // alt+j is Firefox's Downloads, ctrl+j its console -- and claiming it meant those
  // shortcuts silently ran a card command instead. Returning here, without
  // preventDefault, is what hands the key back. Placed AFTER the typing block on
  // purpose: that block already returned, so ctrl+Enter still commits the comment.
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === ' ') { e.preventDefault(); flip(); }
  else if (RECALL && (e.key === 'y' || e.key === '1')) { answerRecall(true); }
  else if (RECALL && (e.key === 'n' || e.key === '2')) { answerRecall(false); }
  else if (!RECALL && e.key >= '1' && e.key <= '5') { score(Number(e.key)); }
  else if (e.key === 'ArrowRight') { go(1); }
  else if (e.key === 'ArrowLeft') { go(-1); }
  // Up/down move a whole row of the index, so a long deck is a handful of presses.
  else if (e.key === 'ArrowDown') { e.preventDefault(); goRow(1); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); goRow(-1); }
  else if (e.key === 'c') { e.preventDefault(); focusComment(false); }
  else if (e.key === 'd') { toggleTheme(); }
  // Vim motions, for the readers whose hands already know them. Same actions as the
  // arrows -- kept alongside them rather than replacing them -- and only reachable when
  // the caret is not in a text field, because of the typing guard above.
  else if (e.key === 'h') { go(-1); }
  else if (e.key === 'l') { go(1); }
  else if (e.key === 'k') { e.preventDefault(); goRow(-1); }
  else if (e.key === 'j') { e.preventDefault(); goRow(1); }
  // Insert / append: both enter the comment box, as vim's do. `a` also puts the caret at
  // the end, which is what append means; `i` leaves it where it is.
  else if (e.key === 'i') { e.preventDefault(); focusComment(false); }
  else if (e.key === 'a') { e.preventDefault(); focusComment(true); }
});

function finish(){
  save();
  el('#sum-body').innerHTML = RECALL ? recallSummary() : scaleSummary();
  el('#overlay').classList.add('on');
}

function scaleSummary(){
  const counts = {}, cuts = [], unscored = [];
  CARDS.forEach((c,i)=>{
    const r = STATE[cardKey(CARDS[i])] || {};
    if (r.score == null) unscored.push(c.n);
    else { counts[r.score] = (counts[r.score]||0)+1; if (r.score === 1) cuts.push(c.n); }
  });
  const LABEL = {1:'Easy',2:'Medium',3:'Hard',4:'Beyond me',5:'Reject'};
  let rows = '';
  [1,2,3,4,5].forEach(k=>{
    rows += '<tr><td class="n">'+k+'</td><td>'+LABEL[k]+'</td><td>'+(counts[k]||0)+'</td></tr>';
  });
  return '<table><tr><th></th><th>Score</th><th>Cards</th></tr>'+rows+'</table>' +
    (cuts.length ? '<p>Rescope candidates (scored Easy — merge, re-level, replace, or keep as anchor; no auto-cut):</p><ul>'
        + cuts.map(n=>'<li>card '+n+'</li>').join('') + '</ul>' : '') +
    (unscored.length ? '<p>Not scored ('+unscored.length+'): '+unscored.join(', ')+'</p>'
        : '<p>All cards scored.</p>');
}

function recallSummary(){
  const yes = [], no = [], un = [];
  CARDS.forEach((c,i)=>{
    const r = STATE[cardKey(CARDS[i])] || {};
    if (r.recall === true) yes.push(c.n);
    else if (r.recall === false) no.push(c.n);
    else un.push(c.n);
  });
  return '<table><tr><th></th><th>Answerable from memory, without working it out?</th>'
    + '<th>Cards</th></tr>'
    + '<tr><td class="n">1</td><td>Yes — recalled it directly</td><td>'+yes.length+'</td></tr>'
    + '<tr><td class="n">2</td><td>No — I would have had to work it out</td><td>'+no.length+'</td></tr>'
    + '</table>'
    + (no.length
        ? '<p>These fail rule 8: the front demands work, not recall. Rewrite them so the '
          + 'front asks about the concept, or cut them.</p><ul>'
          + no.map(n=>'<li>card '+n+'</li>').join('') + '</ul>'
        : '<p>No rule 8 failures in this set.</p>')
    + (un.length ? '<p>Not answered ('+un.length+'): '+un.join(', ')+'</p>'
                 : '<p>All cards answered.</p>');
}

function done(){
  // The deck-wide note rides along with the finish signal, so the agent gets one
  // generalisable instruction instead of N per-card verdicts.
  const note = (el('#decknote').value || '').trim();
  fetch('/finish', {method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({deck_note: note})}).catch(()=>{});

  el('#summary').innerHTML = `
    <div class="done" role="status">
      <div class="confetti" id="confetti"></div>
      <div class="done-check" aria-hidden="true">✓</div>
      <h3>You're done!</h3>
      <p>Go back to opencode and tell your agent: <b>done</b>.</p>
      <button onclick="tryClose()">Close tab</button>
      <p id="close-hint">The review is saved. This tab will close in a few seconds.</p>
    </div>`;
  confetti();
  // Give the reader a moment to see the message, then try to close the tab.
  // Browsers may refuse; the button and hint stay if they do.
  setTimeout(tryClose, 6000);
}

function confetti(){
  const box = el('#confetti');
  if (!box || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const colors = ['--red','--yellow','--blue','--green','--aqua','--orange'];
  for (let i=0; i<14; i++) {
    const bit = document.createElement('i');
    bit.style.left = (Math.random()*100) + '%';
    bit.style.background = 'var(' + colors[i % colors.length] + ')';
    bit.style.animationDelay = (Math.random()*0.4) + 's';
    bit.style.animationDuration = (1.2 + Math.random()*0.8) + 's';
    box.appendChild(bit);
  }
}

function tryClose(){
  // Browsers may refuse to close a tab they did not open. Say so if it stays open.
  window.close();
  setTimeout(()=>{
    if (window.closed) return;
    const hint = el('#close-hint');
    if (hint) {
      hint.textContent = 'The browser blocked the automatic close. '
        + 'Press Cmd+W on macOS or Ctrl+W to close this tab.';
    }
  }, 300);
}

// Light / dark. Starts on light every load and does NOT persist: a refresh should return
// to the page's own colours, not to whatever the last session ended on. Two things flip:
// the data-theme attribute drives every CSS variable in the dark block above, and the
// .night_mode class on <body> triggers the DECK's own night rules for the card itself --
// the same class Anki applies, so the preview stays faithful to what the deck will show.
let theme = 'light';
function applyTheme(){
  document.documentElement.dataset.theme = theme;
  document.body.classList.toggle('night_mode', theme === 'dark');
  // The icon swap is CSS (see .icon-moon / .icon-sun). Only the wording changes here,
  // and it names the destination -- the same thing the moon/sun shows.
  const want = (theme === 'dark') ? 'light' : 'dark';
  const btn = el('#themebtn');
  if (btn) {
    btn.title = 'Switch to ' + want + ' mode (d)';
    btn.setAttribute('aria-label', 'Switch to ' + want + ' mode');
  }
}
function toggleTheme(){
  theme = (theme === 'dark') ? 'light' : 'dark';
  applyTheme();
}

// Which question is on screen was decided by the server (--ask), so the panel that
// does not apply is hidden HERE, at startup. Both panels have to be in the template
// for the CSS to style them, and hiding the inapplicable one at render time is
// exactly what made the score buttons disappear entirely: they were marked hidden in
// the HTML and nothing ever unhid them in the mode that needs them.
el('#scale').hidden = RECALL;
el('#recallbox').hidden = !RECALL;

applyTheme();
buildIndex();
paint();
"""

PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- Two different signals, for two different jobs.

     darkreader-lock: Dark Reader's own opt-out tag. When present the extension removes
     itself from the page (darkreader/darkreader PR #9181; CONTRIBUTING.md, "Disabling
     Dark Reader on your site"). This is the one doing the work here, because the page is
     deliberately light and must not be inverted.

     color-scheme: light: the standard signal. Dark Reader reads it to spot a site that is
     natively DARK and skip inverting it, which is not our case; its real job here is to
     tell the BROWSER the page commits to a light appearance, so the textarea, scrollbars
     and form controls render light rather than following the OS dark preference (which
     would put dark widgets on cream). Set in CSS below too, since some browsers honour
     only the CSS property. (No double hyphens in this comment: HTML forbids them.) -->
<meta name="color-scheme" content="light dark">
<meta name="darkreader-lock">
<title>__TITLE__</title>
<style>
__DECK_CSS__
</style>
<style>
__APP_CSS__
</style>
<script>
window.MathJax = {
  tex: {inlineMath: [['\\\\(','\\\\)']], displayMath: [['\\\\[','\\\\]']]},
  options: {skipHtmlTags: ['script','noscript','style','textarea','pre','code']},
  startup: {typeset: false}
};
</script>
<!-- Vendored, and deliberately NOT async: a local 2 MB file parses in
     milliseconds, and loading it in document order means MathJax is defined
     before the page's first typeset call rather than racing it. -->
<script src="__MATHJAX_URL__"></script>
</head>
<body>

<aside>
  <div class="side-head">
    <h1>__TITLE__</h1>
    <div class="side-btns">
      <button class="hdrbtn" id="themebtn" onclick="toggleTheme()" title="Switch to dark mode (d)" aria-label="Switch to dark mode">
        <svg class="icon icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
        <svg class="icon icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>
      </button>
      <button class="hdrbtn" id="finish-review" onclick="finish()">Finish</button>
    </div>
    <div class="counts"><span id="cardno"></span><span class="sep">&middot;</span><span id="count"></span></div>
    <div class="version">anki-gen __VERSION__</div>
  </div>
  <div class="side-index">
    <h2>Cards</h2>
    <div class="idx" id="idx"></div>
  </div>
  <div class="side-keys">
    <h2>Keys</h2>
    <div class="keys">
__KEYS__
    </div>
  </div>
</aside>

<main>
  <div class="stage">
    <div class="sheet" id="sheetwrap" onclick="sheetClick(event)" title="Click the card to flip (space)">
      <div class="card" id="sheet"></div>
    </div>
  </div>
  <div class="controls">
    <div class="bar"><i id="barfill"></i></div>
__LEAD__
    <div class="scores" id="scale" hidden>
      <button data-k="1" onclick="score(1)"><b>1</b>Easy</button>
      <button data-k="2" onclick="score(2)"><b>2</b>Medium</button>
      <button data-k="3" onclick="score(3)"><b>3</b>Hard</button>
      <button data-k="4" onclick="score(4)"><b>4</b>Beyond me</button>
      <button data-k="5" onclick="score(5)"><b>5</b>Reject</button>
    </div>
    <!-- Recall mode. The question is deliberately about ANSWERING, not about
         difficulty: a card can be hard and still perfectly recallable, so the
         1-5 scale cannot see a front that quietly demands a computation. -->
    <div class="recall" id="recallbox" hidden>
      <button data-r="1" onclick="answerRecall(true)"><b>Y / 1</b>Yes — from memory, without working it out</button>
      <button data-r="0" onclick="answerRecall(false)"><b>N / 2</b>No — I would have to work it out</button>
    </div>
    <div class="comment">
      <textarea id="comment" placeholder="Comment (c) — optional. Enter or Esc leaves the box."
                onblur="save()"></textarea>
    </div>
    <div class="nav">
      <button onclick="go(-1)">&larr; Prev</button>
      <button onclick="flip()" title="Flip (space)">Flip</button>
      <button class="go" onclick="go(1)">Next &crarr;</button>
    </div>
  </div>
</main>

<div class="overlay" id="overlay">
  <div class="summary" id="summary">
    <h3>Review complete</h3>
    <p id="sum-lead">Answers are saved as you go, and nothing is applied to the deck until
       you tell the chat you are done.</p>
    <div id="sum-body"></div>
    <label class="decknote">Deck-wide rule
      <span>— one note here applies to every card, so you do not have to say the same
      thing card by card</span>
      <textarea id="decknote" placeholder="e.g. these fronts lean on labels I invented; use the course's own terms"></textarea>
    </label>
    <button id="save-close" onclick="done()">Save and close</button>
    <p id="close-hint"></p>
  </div>
</div>

<script>
const CARDS = __CARDS__;
const STATE = __STATE__;
const MODE = __MODE__;
</script>
<script>
__APP_JS__
</script>
</body></html>
"""


# The key list: one line per key, the form it had before a two-column table replaced it
# (a table spent a column restating what the buttons already say, and read as hand-holding).
# Shown always -- there is no key to hide it, since a help panel you can leave hidden by
# pressing the wrong key is worse than five lines of chrome.
KEYS_SCALE = """    <span class="k"><kbd>1</kbd>&ndash;<kbd>5</kbd></span><span class="l">score</span>
"""

KEYS_RECALL = """    <span class="k"><kbd>y</kbd>/<kbd>1</kbd></span><span class="l">yes</span>
    <span class="k"><kbd>n</kbd>/<kbd>2</kbd></span><span class="l">no</span>
"""

KEYS_REST = """    <span class="k"><kbd>space</kbd></span><span class="l">flip</span>
    <span class="k"><kbd>&larr;</kbd><kbd>&rarr;</kbd> <kbd>h</kbd><kbd>l</kbd></span><span class="l">prev / next</span>
    <span class="k"><kbd>&uarr;</kbd><kbd>&darr;</kbd> <kbd>k</kbd><kbd>j</kbd></span><span class="l">jump a row</span>
    <span class="k"><kbd>c</kbd> <kbd>i</kbd> <kbd>a</kbd></span><span class="l">comment</span>
    <span class="k"><kbd>&crarr;</kbd> <kbd>esc</kbd></span><span class="l">leave the box</span>
    <span class="k"><kbd>d</kbd></span><span class="l">light / dark</span>"""

# The prompt above the buttons. Only where the buttons cannot say it themselves: in
# recall mode the question IS the prompt. In scale mode the buttons are labelled and the
# key list says scoring stays put, so there is nothing to add -- an empty string, and the
# template leaves the line out entirely rather than reserving an empty row for it.
LEAD = {
    "scale": "",
    "recall": "Could you answer it from memory, without working it out?",
}


def build_page(cards_data: list[dict], state: dict, title: str,
               mode: str = "scale") -> bytes:
    def js(obj):
        # `</script>` inside a JSON string would end the script block early.
        return json.dumps(obj).replace("<", "\\u003c")

    keys = (KEYS_RECALL if mode == "recall" else KEYS_SCALE) + KEYS_REST
    lead = LEAD.get(mode, "")
    page = (PAGE
            .replace("__TITLE__", html.escape(title))
            .replace("__VERSION__", html.escape(SKILL_VERSION))
            .replace("__MATHJAX_URL__", MATHJAX_URL)
            .replace("__DECK_CSS__", CSS)
            .replace("__APP_CSS__", APP_CSS)
            .replace("__APP_JS__", APP_JS)
            .replace("__KEYS__", keys)
            .replace("__LEAD__", f'<p class="lead">{lead}</p>' if lead else "")
            .replace("__MODE__", json.dumps(mode))
            .replace("__CARDS__", js(cards_data))
            .replace("__STATE__", js(state)))
    return page.encode("utf-8")


# ------------------------------------------------------------------ server
class Handler(BaseHTTPRequestHandler):
    server_version = "anki-gen-review"

    def log_message(self, *a):        # keep the console quiet; the URL is the output
        pass

    def _send(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _touch(self):
        self.server.last_seen = time.monotonic()   # type: ignore[attr-defined]

    def _send_asset(self, url_path: str) -> None:
        """Serve a file from the skill's assets/ directory.

        The request path is attacker-controlled -- trivially so on localhost, and
        this server is reachable by anything else running on the machine. So the
        path is resolved and then verified to still be inside ASSETS_DIR; without
        that check a request for `/assets/../../.ssh/id_rsa` would be served.
        """
        rel = url_path[len("/assets/"):].split("?", 1)[0]
        target = (ASSETS_DIR / rel).resolve()
        try:
            target.relative_to(ASSETS_DIR.resolve())
        except ValueError:
            self._send(403, "text/plain", b"forbidden")
            return
        if not target.is_file():
            self._send(404, "text/plain", b"not found")
            return
        ctype = {
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".woff2": "font/woff2",
            ".map": "application/json",
        }.get(target.suffix, "application/octet-stream")
        self._send(200, ctype, target.read_bytes())

    def _serve_media(self, url_path: str) -> None:
        """Serve card media from the work tree, with the same traversal guard."""
        rel = unquote(url_path[len("/media/"):].split("?", 1)[0])
        try:
            target = media.resolve(self.server.media_root, rel)  # type: ignore[attr-defined]
        except ValueError:
            self._send(403, "text/plain", b"forbidden")
            return
        if not target.is_file():
            self._send(404, "text/plain", b"not found")
            return
        ctype = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif",
        }.get(target.suffix.lower())
        if not ctype:
            self._send(415, "text/plain", b"unsupported image type")
            return
        self._send(200, ctype, target.read_bytes())

    def do_GET(self):
        self._touch()
        if self.path in ("/", "/index.html"):
            st = self.server.store.state()          # type: ignore[attr-defined]
            self._send(200, "text/html; charset=utf-8",
                       build_page(self.server.cards, st, self.server.title,   # type: ignore[attr-defined]
                                  self.server.mode))                          # type: ignore[attr-defined]
        elif self.path == "/health":
            self._send(200, "text/plain", b"ok")
        elif self.path.startswith("/assets/"):
            self._send_asset(self.path)
        elif self.path.startswith("/media/"):
            self._serve_media(self.path)
        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        self._touch()
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:                 # local server, but don't buffer unbounded input
            self._send(413, "text/plain", b"too large")
            return
        raw = self.rfile.read(n)
        if self.path == "/feedback":
            try:
                row = json.loads(raw or b"{}")
                if isinstance(row.get("i"), int):
                    self.server.store.put(row)      # type: ignore[attr-defined]
            except json.JSONDecodeError:
                self._send(400, "text/plain", b"bad json")
                return
            self._send(200, "text/plain", b"ok")
        elif self.path == "/finish":
            try:
                payload = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                payload = {}
            note = str(payload.get("deck_note") or "").strip()
            done = self.server.done_file           # type: ignore[attr-defined]
            done.parent.mkdir(parents=True, exist_ok=True)
            done.write_text(json.dumps(
                {"finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "scored": len(self.server.store.state()),  # type: ignore[attr-defined]
                 "total": len(self.server.cards),           # type: ignore[attr-defined]
                 # A deck-wide instruction from the reviewer: one note meant to
                 # generalise to every card, so it gets its own field rather than
                 # being buried among the per-card comments.
                 "deck_note": note}, indent=2))
            self._send(200, "text/plain", b"ok")
            # shutdown() must not run on the handler thread or it deadlocks.
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._send(404, "text/plain", b"not found")


def _idle_watch(srv, timeout_s: float) -> None:
    while True:
        time.sleep(5)
        if time.monotonic() - getattr(srv, "last_seen", time.monotonic()) > timeout_s:
            print(f"[review] idle for {int(timeout_s)}s — shutting down", flush=True)
            srv.shutdown()
            return


def load_plan(plan_path: Path, cards: list[dict]) -> list[dict]:
    """Read a triage plan and verify it still describes THIS deck.

    A stale plan is worse than no plan: it would quietly put the wrong cards in
    front of the reviewer, or the right cards under the wrong numbers. So the
    hashes are checked, and a mismatch aborts rather than warning -- the fix is
    one command (`triage.py` again), and silently reviewing a deck that has moved
    since is unrecoverable.
    """
    plan = json.loads(plan_path.read_text())
    entries = list(plan.get("entries") or [])
    if not entries:
        print(f"{plan_path}: no entries — nothing to review", file=sys.stderr)
        raise SystemExit(2)

    stale = []
    for e in entries:
        i = e.get("i")
        if not isinstance(i, int) or not 1 <= i <= len(cards):
            stale.append(f"  card {i!r}: not a card number in this deck")
        elif card_hash(cards[i - 1]) != e.get("hash"):
            stale.append(f"  card {i}: the card has changed since the plan was written")
    if stale:
        print(f"{plan_path} is out of date for this cards.json ({len(cards)} cards):\n"
              + "\n".join(stale) +
              "\nRe-run triage.py to rebuild the plan.", file=sys.stderr)
        raise SystemExit(2)
    return entries


def main() -> int:
    ap = argparse.ArgumentParser(description="Local review surface for an anki-gen deck.")
    ap.add_argument("--cards", required=True, help="cards.json to review")
    ap.add_argument("--out", default=None,
                    help="feedback log (append-only); default review_feedback.jsonl, "
                         "or review_recall.jsonl with --ask recall")
    ap.add_argument("--port", type=int, default=0, help="0 picks a free port")
    ap.add_argument("--title", default="anki-gen review", help="shown in the header and tab")
    ap.add_argument("--done-file", default=None,
                    help="sentinel written on finish (default: beside the feedback log)")
    ap.add_argument("--idle-timeout", type=float, default=90,
                    help="minutes without a request before self-shutdown")
    ap.add_argument("--media-root", default=None,
                    help="root card media paths are relative to "
                         "(default: the directory holding cards.json)")
    ap.add_argument("--plan", default=None, metavar="PLAN",
                    help="review_plan.json from triage.py: review only the selected "
                         "cards, and show why each one was picked")
    ap.add_argument("--ask", choices=("scale", "recall"), default="scale",
                    help="'recall' replaces the 1-5 scale with the binary rule-9 "
                         "question: could you answer this from memory, without "
                         "working it out?")
    args = ap.parse_args()
    if args.out is None:
        args.out = ("review_recall.jsonl" if args.ask == "recall"
                    else "review_feedback.jsonl")

    media_root = args.media_root or str(Path(args.cards).resolve().parent)
    cards = load_cards(args.cards)
    if not isinstance(cards, list) or not cards:
        print("no cards to review", file=sys.stderr)
        return 2

    plan_entries = None
    plan_note = ""
    title = args.title
    if args.plan:
        plan_obj = json.loads(Path(args.plan).read_text())
        plan_entries = load_plan(Path(args.plan), cards)
        plan_note = str(plan_obj.get("note", ""))
        # A plan recorded against a different file is worth saying out loud: the
        # hash check above still protects the reviewer, but a plan built from
        # another cards.json usually means one of the two paths is a typo.
        cards_file = Path(args.cards).name
        plan_file = Path(str(plan_obj.get("cards_json") or "")).name
        if plan_file and plan_file != cards_file:
            print(f"[review] note: the plan was built from {plan_file!r}, "
                  f"this run is reading {cards_file!r}", flush=True)
        plan_total = len(cards)
        cards = [cards[e["i"] - 1] for e in plan_entries]
        title = f"{title} — triage {len(cards)} of {plan_total}"

    print(f"[review] anki-gen {SKILL_VERSION}", flush=True)
    print(f"[review] rendering {len(cards)} cards in {args.ask} mode…", flush=True)
    cards_data = render_cards(cards, plan_entries, media_root)

    if plan_note:
        print(f"[review] triage: {plan_note}", flush=True)

    # A missing bundle is not fatal -- the page still loads and scores fine, the
    # math just shows as raw TeX. Say so loudly, because "my cards look like
    # backslash soup" is otherwise very hard to diagnose from the browser.
    if not MATHJAX_PATH.is_file():
        print(f"[review] WARNING: MathJax is not vendored at {MATHJAX_PATH}\n"
              f"         Math will render as raw TeX. Fetch it with:\n"
              f"         curl -sL https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-svg.js"
              f" -o {MATHJAX_PATH}", flush=True)

    out = Path(args.out)
    store = Store(out)
    if store.rows:
        print(f"[review] resuming — {len(store.rows)} card(s) already answered", flush=True)

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    srv.cards = cards_data                                    # type: ignore[attr-defined]
    srv.store = store                                         # type: ignore[attr-defined]
    srv.title = title                                         # type: ignore[attr-defined]
    srv.mode = args.ask                                       # type: ignore[attr-defined]
    done_file = (Path(args.done_file) if args.done_file
                 else Path(args.out).parent / "review_done")
    srv.done_file = done_file                                 # type: ignore[attr-defined]
    srv.media_root = Path(media_root)                         # type: ignore[attr-defined]
    srv.last_seen = time.monotonic()                          # type: ignore[attr-defined]

    threading.Thread(target=_idle_watch, args=(srv, args.idle_timeout * 60),
                     daemon=True).start()

    host, port = srv.server_address[:2]
    # The URL is printed ALONE, with nothing before or after it on the line. It is
    # relayed to the user to paste into a browser, and a line like "[review] open
    # http://…" cannot be copied whole -- the reader has to select part of a line. The
    # prefixed lines around it are log detail, not something anyone pastes.
    print("", flush=True)
    print(f"http://{host}:{port}/", flush=True)
    print("", flush=True)
    print(f"[review] stop without pkill: curl -s -X POST http://{host}:{port}/finish",
          flush=True)
    print("[review] hand the user the URL: one short sentence saying what the page is "
          "and to come back when done, then the URL above alone on its own line", flush=True)
    print(f"[review] feedback -> {out.resolve()}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    print("[review] stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
