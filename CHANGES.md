# What changed

## Bugs fixed
- `app.py` had a genuine Python **syntax error** on the truncation-check
  line (a malformed string literal). The old file could not even be
  imported.
- The offline fallback path called `_fallback_math()`, `_fallback_social()`
  and `_fallback_generic()` — none of which existed anywhere in the
  codebase. Any fallback paper for Maths, Social Studies, or a language
  subject crashed with `NameError`. Fixed with a single working
  `core/fallback.py` template that adapts to any subject.

## Speed: ~3 minutes → ~20-40 seconds
The old code tried every model (4-5) on every API key (up to 3) via
LangChain *and* a raw REST fallback, one attempt after another, each
with a **180-second** timeout — worst case ~20-30 sequential HTTP
calls. Diagrams then waited *another* 90 seconds, sequentially, after
the text was already done. Two PDFs were built one after another.

New behavior (see `core/config.py` for the actual numbers):
- `core/ai_text.py` fires a small batch of (model, key) attempts
  **concurrently** and takes the first success, each capped at a
  20-second timeout, inside one 22-second overall budget. No LangChain
  (it only duplicated every failed REST call).
- `core/ai_diagrams.py` generates all diagrams in **one shared
  12-second budget**, in parallel — a paper with 6 diagrams doesn't
  take 6x as long. Diagrams that don't finish in time are skipped
  (the PDF shows a placeholder) rather than blocking the whole request.
- `app.py` builds the "paper only" and "paper + answer key" PDFs on
  two threads at once instead of sequentially.
- If a response looks cut off, the paper is trimmed to the last
  complete question instead of paying for a second full generation
  call (that used to add another 60-90 seconds on its own).

Worst case is still bounded and graceful: if every model is rate
limited, you get a clear error (with a dev alert email) in the ~22s
text budget instead of waiting 3 minutes to find out.

## Backend restructure
`app.py` (3,479 lines, one file) is now a thin ~330-line routes file.
Everything else moved into `core/`:

| Module | Responsibility |
|---|---|
| `core/config.py` | env vars, paths, model list, time budgets |
| `core/prompts.py` | builds the generation prompt |
| `core/ai_text.py` | fast parallel Gemini call for paper text |
| `core/ai_diagrams.py` | fast parallel Gemini calls for SVG diagrams |
| `core/pdf_engine.py` | ReportLab PDF layout |
| `core/svg_render.py` | SVG → PDF-embeddable image |
| `core/fonts.py` | DejaVu font registration |
| `core/fallback.py` | offline template (used only if Gemini is unreachable) |
| `core/splitter.py` | splits raw AI output into paper / answer key |
| `core/mailer.py` | optional error-alert emails |

`requirements.txt` dropped `langchain`, `langchain-core`, and
`langchain-google-genai` — fewer dependencies, faster cold starts on
serverless, one less place for a silent failure to hide.

## Frontend rewrite
Removed: particle canvas, five blurred background orbs, a
mesh/grid/noise/lines decoration layer, a trivia mini-game shown during
loading, 6 cycling color themes × light/dark, a font cycler, and the
GSAP/ScrollTrigger dependency — all of which were the source of the
jank on lower-end devices.

New concept: the generator form is laid out like the exam paper it
produces — a masthead, numbered "Part A/B/C/D" sections, a live marks
box, section banners that mirror the PDF's own styling, and a small
stamp animation when a paper finishes. All motion is plain CSS
transitions/keyframes (respects `prefers-reduced-motion`); there is no
animation library and no canvas.

`templates/index.html` (638 lines) → 210 lines.
`static/css/style.css` (1,205 lines) → ~330 lines.
`static/js/app.js` (1,383 lines) → ~430 lines, same functional
coverage (state board + competitive flows, curriculum-driven
subject/chapter selects, marks/difficulty, direct + server-rendered
PDF download, localStorage history) with the decorative code removed.

## Testing done in this environment
No live Gemini key is available here, so the AI call paths themselves
weren't exercised against the real API — but everything else was:
Flask app import, `/`, `/health`, `/chapters`, `/generate` (fallback
mode, tested across Math/Science/Social/English subjects — including
the ones that used to crash), `/download-pdf`, PDF byte output, and
JS/HTML syntax validation all pass.
