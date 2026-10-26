#!/usr/bin/env python3
r"""Convert card text (markdown + LaTeX) into HTML Anki will actually render.

WHY THIS EXISTS
---------------
Anki's bundled MathJax is configured for  \\( ... \\)  inline and  \\[ ... \\]  display.
The familiar  $...$ / $$...$$  form is NOT enabled, so it renders as literal
`$N_v/N = \exp(-Q_v/kT)$`. Every formula must be rewritten to Anki's delimiters.

Anki also renders NO markdown: `**bold**`, `*italic*`, `|tables|` and `- lists` all
appear literally, because a field is just HTML. So markdown must be converted.

The previous approach in this skill was LaTeX -> inline SVG via the `katex` PyPI
package. That is a dead end and was removed:
  * PyPI `katex` maxes out at 0.0.4 -- a Facebook *image* converter with no
    render_to_string(); the API this skill called does not exist.
  * `latex2svg` is not installed.
  * Even if it worked, embedding SVG as `data:image/svg+xml,<svg ...>` unencoded
    breaks on `>` and `#`, and yields unselectable images.

Native MathJax needs no dependency, gives selectable text, keeps the .apkg small,
and works offline. Requirements: nothing beyond the standard library.

SAFE AUTHORING
--------------
If you use the legacy Python authoring path, write LaTeX in RAW strings; the canonical cards.jsonl path uses JSON escapes. A non-raw
string silently corrupts LaTeX, because these are Python escapes:

    \\t  -> TAB      breaks \\text{}, \\times, \\theta
    \\f  -> formfeed breaks \\frac
    \\r  -> CR       breaks \\rho
    \\b  -> backspace breaks \\bar
    \\n  -> newline  breaks \\nu, \\neq
    \\v  -> vtab     breaks \\vert

`\\frac` becoming a formfeed is silent -- no exception, no warning you will read.
validate_cards.py checks for this.
"""
from __future__ import annotations

import re

# Placeholders are tagged D (display) or M (inline) so the markdown pass can tell a
# math-only paragraph from prose; the restore step runs after markdown conversion.
PH_D = "\x00D{}\x00"
PH_M = "\x00M{}\x00"
PH_S = "\x00S\x00"       # an escaped/literal dollar, restored after HTML escaping

# Inline math may wrap across a source line. Opening/closing dollars must not be
# escaped, and must not be whitespace-adjacent or followed by a digit. That keeps
# currency like $5 from swallowing the next real formula.
MATH_RE = re.compile(
    r"\$\$(.+?)\$\$|(?<!\\)\$(?!\s)([^$]+?)(?<!\s)\$(?!\d)",
    re.DOTALL)

# An inline code span. A card that explains the delimiter rules has to be able to
# write `$...$` -- or a bare `$` -- inside backticks, and the math pass must not
# run in there. It used to, which broke the field two ways: the span's own text was
# replaced by a math placeholder, and the '$' characters the pass left behind then
# paired with real math later in the same field, so `$x$` came out as \)x\( and a
# trailing '$' survived into the finished card. validate_cards reported that as the
# author's stray delimiter, which it was not.
CODE_RE = re.compile(r"`[^`]+?`", re.DOTALL)


# ------------------------------------------------------------------ math
def _clean_tex(tex: str) -> str:
    """Make a LaTeX body safe to drop into an HTML field."""
    tex = re.sub(r"\s+", " ", tex).strip()      # collapse source line wrapping
    return (tex.replace("<", r"\lt")
               .replace(">", r"\gt")
               .replace("&", "&amp;"))          # HTML entity: MathJax still sees the
                                                # alignment tab in bmatrix/array, while
                                                # \& would render a literal ampersand


def _extract_math(text: str):
    """Pull `$...$` / `$$...$$` out into placeholders, leaving code spans alone.

    Segmented on CODE_RE rather than run over the whole field: math inside
    backticks is a literal example, not math, and treating it as math corrupts
    both the span and every real math span after it (see CODE_RE above).

    `found` stays in document order because the segments are visited left to
    right, which is what _restore_math relies on.
    """
    found: list[tuple[str, bool]] = []

    def grab(m):
        display = m.group(1) is not None
        found.append((m.group(1) if display else m.group(2), display))
        return (PH_D if display else PH_M).format(len(found) - 1)

    def prose(segment: str) -> str:
        segment = MATH_RE.sub(grab, segment)
        segment = segment.replace("\\$", PH_S)
        # A doubled MathJax delimiter is an escaping artifact, not math. Collapse
        # one level outside math/code so MathJax sees \(...\) / \[...\].
        return re.sub(r"\\\\([()\[\]])", lambda m: "\\" + m.group(1), segment)

    parts, pos = [], 0
    for m in CODE_RE.finditer(text):
        parts.append(prose(text[pos:m.start()]))
        span = m.group(0)
        inner = span[1:-1].strip()
        if MATH_RE.fullmatch(inner):
            # Authors sometimes wrap a bare formula in backticks, which would
            # otherwise render as literal `$...$`. Treat a math-only code span as
            # math; genuine code spans with prose still stay literal.
            parts.append(MATH_RE.sub(grab, inner))
        else:
            parts.append(span)                   # the span itself, verbatim
        pos = m.end()
    parts.append(prose(text[pos:]))
    return "".join(parts), found


def _restore_math(html: str, found) -> str:
    for i, (tex, display) in enumerate(found):
        body = _clean_tex(tex)
        repl = (f'<div class="math-block">\\[{body}\\]</div>'
                if display else f"\\({body}\\)")
        html = html.replace(PH_D.format(i), repl).replace(PH_M.format(i), repl)
    return html


# -------------------------------------------------------------- escaping
def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# -------------------------------------------------------------- markdown
SECTION_LABELS = (
    "Why", "Glossary", "Symbols", "Next", "Trap", "Note", "Consequence",
    "Advantages", "Disadvantages", "Definition", "Example", "Warning",
    "Caveat", "Result", "Formula", "Takeaway",
)
_SECTION_SPLIT = re.compile(
    r"\s*(?=<b>(?:" + "|".join(SECTION_LABELS) + r"):</b>)", re.I)
_HTML_CODE = re.compile(r"<code>.*?</code>", re.S)


def _paragraph_sections(html: str) -> str:
    """Turn inline `**Why:**`/`**Glossary:**` labels into their own paragraphs.

    Cards are often authored with all sections on one line. The renderer
    normalizes that presentation while leaving genuine code spans untouched.
    """
    def split_paragraph(match):
        content = match.group(1)
        protected = []

        def hide(code):
            protected.append(code.group(0))
            return f"\x00H{len(protected) - 1}\x00"

        content = _HTML_CODE.sub(hide, content)
        parts = [part for part in _SECTION_SPLIT.split(content) if part.strip()]
        if len(parts) <= 1:
            content = parts[0] if parts else content
        else:
            content = "</p><p>".join(parts)
        for i, code in enumerate(protected):
            content = content.replace(f"\x00H{i}\x00", code)
        return f"<p>{content}</p>"

    return re.sub(r"<p>(.*?)</p>", split_paragraph, html, flags=re.S)


def _inline(md: str) -> str:
    md = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", md, flags=re.S)
    md = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", md)
    md = re.sub(r"`([^`]+?)`", r"<code>\1</code>", md, flags=re.S)
    return md


def _table(lines, i, out):
    def cells(row):
        return [c.strip() for c in row.strip().strip("|").split("|")]

    head = cells(lines[i])
    i += 1
    if i < len(lines) and re.fullmatch(r"[\s|:-]+", lines[i]):
        i += 1
    body = []
    while i < len(lines) and lines[i].strip().startswith("|"):
        body.append(cells(lines[i]))
        i += 1
    out.append("<table><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr>")
    for row in body:
        out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>")
    out.append("</table>")
    return i


def _item_body(lines, i: int) -> str:
    """Body of a list item: the marker line plus indented continuation lines.

    Without this, a wrapped item loses its tail -- which also breaks any `**bold**`
    or `$math$` that straddles the line break.
    """
    parts = [re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", lines[i])]
    j = i + 1
    while j < len(lines) and _is_item_cont(lines[j]):
        parts.append(lines[j].strip())
        j += 1
    return " ".join(p for p in parts if p)


def _skip_item(lines, i: int) -> int:
    """Index of the first line after the list item starting at i.

    Must step past continuation lines. Advancing by 1 instead emits the tail twice:
    once joined into the <li>, then again as a stray paragraph -- which also
    truncates any **bold** that straddles the wrap.
    """
    j = i + 1
    while j < len(lines) and _is_item_cont(lines[j]):
        j += 1
    return j


def _flow(lines) -> str:
    """Join wrapped source lines into one flowing paragraph.

    Line breaks in the authoring file are cosmetic, not semantic. Joining with
    <br> reproduced them in the card and split sentences mid-clause
    ("...is at / its minimum"). Join with a space.

    A line that ends in two spaces, or a trailing backslash, is the standard
    markdown "hard break" signal and IS honoured as <br>. That is how a card
    author asks for a deliberate line break inside a paragraph -- needed for
    one-fact-per-line fronts, where every blank must be visibly its own line.
    """
    out = []
    for ln in lines:
        if not ln.strip():
            continue
        hard = ln.endswith("  ") or ln.rstrip().endswith("\\")
        out.append(ln.strip().rstrip("\\").rstrip() + ("<br>" if hard else ""))
    return " ".join(out)


def _is_item_cont(ln: str) -> bool:
    return bool(ln.strip()) and not re.match(r"\s*(?:[-*+]\s|\d+[.)]\s|\||#{1,6}\s)", ln) \
        and not re.fullmatch(r"\s*(-{3,}|\*{3,}|_{3,})\s*", ln)


def _md_to_html(md: str) -> str:
    lines = md.split("\n")
    out: list[str] = []
    i, buf = 0, []

    while i < len(lines):
        ln = lines[i]

        if not ln.strip():
            if buf:
                out.append("<p>" + _inline(_flow(buf)) + "</p>")
                buf = []
            i += 1
            continue

        # display math is always its own top-level block: <div> is not valid
        # inside <p>, and browsers auto-close the <p> and lose the spacing.
        if "\x00D" in ln:
            if buf:
                out.append("<p>" + _inline(_flow(buf)) + "</p>")
                buf = []
            out.extend(re.findall(r"\x00D\d+\x00", ln))
            # Anything else sharing the line with the display block is prose that
            # belongs to it. Emitting only the placeholders (as this branch used to)
            # dropped that prose silently: no error, no warning, the words are just
            # not in the deck. Cards written one display block per line are
            # unaffected -- the remainder is empty and nothing is emitted.
            rest = re.sub(r"\x00D\d+\x00", " ", ln).strip()
            if rest:
                out.append("<p>" + _inline(_flow([rest])) + "</p>")
            i += 1
            continue

        if ln.strip().startswith("|"):
            if buf:
                out.append("<p>" + _inline(_flow(buf)) + "</p>")
                buf = []
            i = _table(lines, i, out)
            continue

        if re.fullmatch(r"\s*(-{3,}|\*{3,}|_{3,})\s*", ln):
            if buf:
                out.append("<p>" + _inline(_flow(buf)) + "</p>")
                buf = []
            out.append("<hr>")
            i += 1
            continue

        m = re.match(r"\s*(#{1,6})\s+(.*)", ln)
        if m:
            if buf:
                out.append("<p>" + _inline(_flow(buf)) + "</p>")
                buf = []
            lvl = min(len(m.group(1)) + 2, 6)
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            i += 1
            continue

        if re.match(r"\s*[-*+]\s+", ln):
            if buf:
                out.append("<p>" + _inline(_flow(buf)) + "</p>")
                buf = []
            out.append("<ul>")
            while i < len(lines) and re.match(r"\s*[-*+]\s+", lines[i]):
                out.append(f"<li>{_inline(_item_body(lines, i))}</li>")
                i = _skip_item(lines, i)
            out.append("</ul>")
            continue

        if re.match(r"\s*\d+[.)]\s+", ln):
            if buf:
                out.append("<p>" + _inline(_flow(buf)) + "</p>")
                buf = []
            out.append("<ol>")
            while i < len(lines) and re.match(r"\s*\d+[.)]\s+", lines[i]):
                out.append(f"<li>{_inline(_item_body(lines, i))}</li>")
                i = _skip_item(lines, i)
            out.append("</ol>")
            continue

        buf.append(ln)
        i += 1
        while i < len(lines) and _is_item_cont(lines[i]) and "\x00D" not in lines[i]:
            buf.append(lines[i])
            i += 1

    if buf:
        out.append("<p>" + _inline(_flow(buf)) + "</p>")
    return "\n".join(out)


# ------------------------------------------------------------------- api
def to_html(text: str) -> str:
    """Card text (markdown + $LaTeX$) -> HTML Anki renders correctly."""
    tmpl, found = _extract_math(text)
    tmpl = _esc(tmpl)              # escape prose only; math is placeholdered
    html = _paragraph_sections(_md_to_html(tmpl))
    return _restore_math(html, found).replace(PH_S, "&#36;")


DERIVED_SOURCES = {"derived", "universal"}


def with_source(back_html: str, source: str, source_url: str = "") -> str:
    """Append a provenance footer beneath a card's answer.

    The source stays readable; a video URL is a second, copyable plain-text line
    (not a hyperlink), so it works the same in Anki and the review page. A
    self-contained derivation uses `source: "derived"` and gets no footer.
    """
    if str(source or "").strip().lower() in DERIVED_SOURCES:
        source = ""
    if not source and not source_url:
        return back_html
    body = _esc(source)
    if source_url:
        body += f'<br><span class="src-url">{_esc(source_url)}</span>'
    return f'{back_html}<div class="src">{body}</div>'


# ------------------------------------------------------- shared constants
# The single source of truth for card CSS. build_native.py imports this rather
# than carrying its own copy -- the two had drifted, which meant the review
# preview could render a card differently from the deck it was previewing. If
# you change card styling, change it here and nowhere else.
CSS = """.card { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        font-size: 17px; line-height: 1.6; text-align: left; color: #1c1c1e;
        background: #fdfdfb; padding: 14px 16px; max-width: 46em; margin: 0 auto; }
.meta { font-size: 11px; color: #98989d; text-transform: uppercase;
        letter-spacing: .07em; margin-bottom: 12px; }
.objects { font-size: 11px; color: #98989d; letter-spacing: .04em;
           margin: -6px 0 12px; }
hr#answer { border: 0; border-top: 1px solid #dcdee0; margin: 18px 0 14px; }
.math-block { text-align: center; margin: 12px 0; }
.src { margin-top: 16px; padding-top: 8px; border-top: 1px dotted #d8dadd;
       font-size: 12px; color: #9a9aa0; }
.src-url { word-break: break-all; }
p { margin: .55em 0; }
table { border-collapse: collapse; margin: 10px 0; font-size: 15px; }
th, td { border: 1px solid #d1d3d4; padding: 5px 11px; text-align: left; }
th { background: #f1f2f3; color: #1c1c1e; font-weight: 600; }
code { background: #f1f2f3; color: #1c1c1e; padding: 1px 5px; border-radius: 3px;
       font-family: ui-monospace, Menlo, Consolas, monospace; font-size: .92em; }
ol, ul { padding-left: 22px; margin: .5em 0; }
li { margin-bottom: .3em; }
b { font-weight: 600; }
/* Every colour above is hard-coded for a light card, which is what keeps
   `code` and `th` from inheriting the host theme's (light-on-light, invisible)
   text colour. That leaves a bright slab on a dark screen, so override the
   palette when the host marks night mode. Both spellings are listed; if neither
   matches, the light rules stand and nothing is lost. */
.night_mode .card, .nightMode .card { background: #2b2b2e; color: #e8e8ea; }
.night_mode code, .nightMode code { background: #3a3a3d; color: #e8e8ea; }
.night_mode th, .nightMode th { background: #3a3a3d; color: #e8e8ea; }
.night_mode th, .nightMode th, .night_mode td, .nightMode td { border-color: #454548; }
.night_mode .src, .nightMode .src { color: #a0a0a6; border-top-color: #454548; }
.night_mode .meta, .nightMode .meta { color: #a0a0a6; }
.night_mode .objects, .nightMode .objects { color: #a0a0a6; }
.night_mode hr#answer, .nightMode hr#answer { border-top-color: #454548; }
.media img { max-width: 100%; height: auto; display: block; margin: 10px 0; border-radius: 4px; }
.media-caption { font-size: 12px; color: #7a7a80; margin: -4px 0 10px; }
.media-missing { padding: 8px 10px; border: 1px dashed #c0392b; color: #9d0006;
                 background: #fff3f3; font-size: 12px; border-radius: 4px; }
.night_mode .media-caption, .nightMode .media-caption { color: #a0a0a6; }
.night_mode .media-missing, .nightMode .media-missing { background: #3a2a2a;
                 border-color: #fb4934; color: #ffb3b3; }
"""
