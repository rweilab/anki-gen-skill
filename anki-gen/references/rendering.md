# Rendering

## Rendering: what Anki actually supports

**Math goes through Anki's bundled MathJax, using `\( ... \)` inline and `\[ ... \]` display.** The
`$...$` / `$$...$$` form is **not enabled by default** and renders literally. Always write `$...$`
in cards.jsonl; the builder converts to Anki's delimiters.

**Subscripts and superscripts are MathJax, not underscores.** Write `$P_{0}$`, `$v_{0y}$`,
`$A_{1}$`; use `\text{}` for descriptive words: `$\rho_{\text{oil}}$`, `$V_{\text{disp}}$`.
Bare `P_0`, `ρ_obj`, or `V_{sphere}` is a validator warning; concatenated names such as
`Vsphere` are a review defect. Code spans are exempt.

**Deliberate line breaks inside a paragraph: use the markdown hard-break signal.** `render.py`
re-flows wrapped source lines into single paragraphs; to force a break — needed for
one-fact-per-line cloze fronts — end the source line with **two spaces** (`  \n`) or a trailing
backslash (`\n`). Both are honoured as `<br>`:

    atoms/unit cell: {{c1::4}}  
    coordination number: {{c2::12}}  
    APF: {{c3::0.74}}  

Soft wraps re-flow; hard breaks are preserved. A literal `<br>` in `cards.jsonl` is a warning:
use a blank line for a paragraph or the two-space signal for a deliberate break. The built HTML
will contain `<br>` tags; that is the renderer's output, not source text.

**CSS night-mode guard.** Every element with a custom `background` MUST have an explicit `color`, or
it inherits the host theme's (light-on-light, invisible). Include a `.night_mode` / `.nightMode`
override block; if neither matches, the hardcoded light colours stand and nothing is lost.

**Anki renders no markdown.** A field is HTML: `**bold**`, `*italic*`, `|tables|`, `- lists` appear
literally unless converted. The builder handles it — write markdown in cards.jsonl, get HTML in the
deck. **Do not route math through SVG** (MathJax, not SVG): MathJax gives selectable text, keeps
the .apkg small, works offline.

**JSON escape traps.** In `cards.jsonl`, a single backslash starts a JSON escape. Write `\\frac`,
not `\frac`; the latter becomes a formfeed and corrupts the card:

| In JSON | Becomes | Breaks |
|---|---|---|
| `\t` | TAB | `\text{}`, `\times`, `\theta` |
| `\f` | formfeed | `\frac` |
| `\r` | CR | `\rho` |
| `\b` | backspace | `\bar` |
| `\n` | newline | `\nu`, `\neq` |
| `\v` | vtab | `\vert` |

`\frac` becoming a formfeed raises no error and no readable warning. `validate_cards.py` checks.
