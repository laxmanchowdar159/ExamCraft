# ExamCraft — Technical Reference

A complete walkthrough of every system, algorithm, and architectural decision in ExamCraft. This document is intended for developers who want to understand, extend, or debug the codebase.

> **Author:** Laxman Nimmagadda · laxmanchowdary159@gmail.com

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Technology Stack and Rationale](#2-technology-stack-and-rationale)
3. [Application Boot Sequence](#3-application-boot-sequence)
4. [Security Architecture](#4-security-architecture)
5. [Error Reporting System](#5-error-reporting-system)
6. [LaTeX and Math Rendering Pipeline](#6-latex-and-math-rendering-pipeline)
7. [PDF Rendering Engine](#7-pdf-rendering-engine)
8. [AI Integration — Multi-Key Round-Robin Failover](#8-ai-integration--multi-key-round-robin-failover)
9. [Prompt Engineering System](#9-prompt-engineering-system)
10. [Diagram Generation Pipeline](#10-diagram-generation-pipeline)
11. [Flask Routes and Request Lifecycle](#11-flask-routes-and-request-lifecycle)
12. [Frontend Architecture](#12-frontend-architecture)
13. [Data Layer](#13-data-layer)
14. [Deployment on Vercel Serverless](#14-deployment-on-vercel-serverless)
15. [Complete Request Trace](#15-complete-request-trace)

---

## 1. Project Structure

```
ExamCraft/
├── app.py                       ← Entire backend (~3,900 lines)
│                                  Flask app · AI chain · PDF engine
│                                  Diagram generator · Email alerter
├── api/
│   └── index.py                 ← Vercel WSGI adapter (2 lines)
├── templates/
│   └── index.html               ← Single-page UI (~640 lines)
├── static/
│   ├── css/style.css            ← All styles, no framework (~740 lines)
│   ├── js/app.js                ← All frontend logic, vanilla JS (~1,400 lines)
│   └── fonts/
│       ├── DejaVuSans.ttf
│       ├── DejaVuSans-Bold.ttf
│       └── DejaVuSans-Oblique.ttf
├── data/
│   ├── curriculum.json          ← Subject/chapter tree for classes 6–10
│   ├── boards.json              ← Board names and metadata
│   └── exam_patterns/
│       ├── ap_ts.json           ← Official AP/TS SSC blueprint
│       └── competitive.json     ← NTSE/NSO/IMO/IJSO formats
├── vercel.json                  ← Serverless deployment configuration
└── requirements.txt
```

**Why a single `app.py`?**

Vercel's Python runtime expects a single WSGI entry point. Keeping everything in one file eliminates relative import complexity, makes deployment a single `git push`, and keeps the entire backend greppable without jumping between modules. The cost is file length, mitigated by `# ═══` section delimiters used throughout that make navigation fast.

---

## 2. Technology Stack and Rationale

| Layer | Technology | Why |
|---|---|---|
| Web framework | **Flask 3** | Minimal overhead. No ORM or template engine needed beyond `render_template`. `@app.route` keeps routing readable. |
| AI model | **Google Gemini 2.5 Flash** | Free-tier quota sufficient for development. 1M-token context window handles full exam prompts. 30–60s inference for a complete paper. |
| AI fallback models | **Gemini 2.5 Flash Lite, Gemma 3** | Different quota pools — round-robin across models means one exhausted quota doesn't block generation. |
| AI SDK | **LangChain + direct REST** | LangChain provides `ChatPromptTemplate` with system/human separation and structured chaining. Direct `requests.post` is the fallback when LangChain is unavailable or returns a non-retryable error. |
| PDF engine | **ReportLab Platypus** | Industry-grade layout engine used in legal, financial, and government document systems. Full typographic control: custom fonts, complex tables, multi-column layouts, page templates. No browser dependency — PDF generation is 100% server-side Python. |
| Fonts | **DejaVu Sans** (TTF) | Comprehensive Unicode coverage for Greek letters (θ, α, β, π, Ω), mathematical operators (√, ∑, ∫, ≤, ≥, ≠), and subscript/superscript characters required for STEM exam papers. Embedded directly in the PDF for portability. |
| Diagrams | **SVG via Gemini API** | Gemini generates raw SVG from a structured technical prompt. SVG is then parsed and converted to ReportLab native shapes for embedding in the PDF. |
| Frontend | **Vanilla HTML/CSS/JS** | No build step, no bundler, no Node dependency at runtime. Page loads in under 100ms. Both CSS and JS fit in two files. |
| Animations | **GSAP 3** | Spring animations and entrance effects. Loaded from CDN — not bundled into the repository. |
| Deployment | **Vercel Serverless** | Free tier, automatic HTTPS, global CDN for static assets, 300s function timeout. Zero server administration. |

---

## 3. Application Boot Sequence

The following executes at module level when Python loads `app.py`:

```
1.  Standard library imports
    os, re, json, time, base64, io, platform, smtplib,
    pathlib, xml.etree, concurrent.futures

2.  ReportLab imports
    SimpleDocTemplate, Paragraph, Table, TableStyle,
    PageBreak, Spacer, HRFlowable, Drawing shapes...

3.  Flask app object created
    app = Flask(__name__, template_folder="templates",
                          static_folder="static")

4.  LangChain imported inside try/except ImportError
    LANGCHAIN_AVAILABLE = True/False
    (graceful degradation — app works without it via REST)

5.  @app.after_request hook registered
    apply_security_headers(response) — runs on EVERY response

6.  API keys read from environment
    GEMINI_KEY   = os.environ.get("GEMINI_API_KEY",   "").strip()
    GEMINI_KEY_2 = os.environ.get("GEMINI_API_KEY_2", "").strip()
    GEMINI_KEY_3 = os.environ.get("GEMINI_API_KEY_3", "").strip()

7.  SMTP config read from environment
    Connection is NOT opened at boot — only when an error occurs.

8.  Curriculum and exam pattern JSON files loaded into module-level dicts
    _CURRICULUM, _PATTERN_AP_TS, _PATTERN_COMP

9.  Font registration flag initialised
    _fonts_registered = False
    (Registration is lazy — happens on the first PDF call)

10. @app.route decorators register all routes

11. if __name__ == "__main__":
        port = int(os.environ.get("PORT", 3000))
        app.run(host="0.0.0.0", port=port, debug=False)
    (Never executes on Vercel — Vercel imports the app object directly)
```

---

## 4. Security Architecture

**Location:** `apply_security_headers(response)` — the `@app.after_request` hook

Every HTTP response — regardless of route, status code, or content type — passes through this function before leaving the server. No route can opt out.

### Permissions-Policy

```http
Permissions-Policy: camera=(), microphone=(), geolocation=(),
  gyroscope=(), accelerometer=(), magnetometer=(), usb=(),
  midi=(), payment=(), display-capture=(), bluetooth=(),
  serial=(), nfc=(), hid=(), ambient-light-sensor=(), ...
```

The `=()` syntax means no origin is allowed — not even the page itself. The browser enforces this at the hardware API level. JavaScript calling `navigator.getUserMedia()` is denied before any permission prompt ever appears. This is defence-in-depth: even a cross-site script injection cannot request device access.

### Content-Security-Policy

```http
Content-Security-Policy:
  default-src 'self';
  script-src  'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net;
  style-src   'self' 'unsafe-inline' https://fonts.googleapis.com;
  connect-src 'self';
  img-src     'self' data:;
  frame-src   'none';
  object-src  'none';
```

`connect-src 'self'` is the critical data-exfiltration guard. All `fetch()` and `XMLHttpRequest` calls must target the same origin. A compromised CDN script could not send data to a third party.

`'unsafe-inline'` is present for scripts because the UI uses `onclick=` attributes on HTML elements. This is an accepted trade-off for simplicity. In a stricter deployment, all inline event handlers would migrate to JS listeners and `'unsafe-inline'` could be removed.

### Other Headers

| Header | Value | Purpose |
|---|---|---|
| `X-Frame-Options` | `DENY` | Prevents clickjacking via iframe embedding |
| `X-Content-Type-Options` | `nosniff` | Prevents MIME-type confusion attacks |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | Forces HTTPS for all requests for 1 year |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limits referrer information on cross-origin navigation |
| `Server` | *(removed)* | Removes framework fingerprint from responses |

---

## 5. Error Reporting System

**Location:** `send_error_email(error_type, error_msg, user_choices, extra_context)`

When generation or PDF rendering fails, the app emails a detailed diagnostic report to the configured `ALERT_EMAIL` address. This function has four design principles:

**Never raises.** The entire body is wrapped in `try/except Exception`. An email failure must never cascade into a web response failure or 500 error for the user.

**Dual MIME format.** Sends both `text/plain` and `text/html` parts in a `MIMEMultipart("alternative")` message. Email clients display whichever format they handle best.

**Zero information loss.** `_capture_user_choices(data)` snapshots every field the user submitted: board, subject, chapter, class, marks, difficulty, scope, and special instructions. Any bug is fully reproducible from the email alone without guessing at inputs.

**Context-rich diagnostics.** Each email includes which AI models were tried, which API keys were configured, LangChain availability status, prompt length, the first 100 characters of the prompt (for debugging prompt assembly issues), and the full Python traceback.

```python
# SMTP mechanism — STARTTLS on Gmail port 587
with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
    server.ehlo()
    server.starttls()          # Upgrade to TLS before transmitting credentials
    server.login(email, password)
    server.sendmail(email, alert_email, msg.as_string())
```

Triggered by: AI generation returning empty after all models and keys are exhausted; any unhandled exception in `POST /generate`; PDF rendering failure in `POST /download-pdf`.

---

## 6. LaTeX and Math Rendering Pipeline

**Location:** `_latex_to_rl(expr)`, `_process(text)`, `_balance_xml_tags(text)`

ReportLab's `Paragraph` renders a subset of XML: `<b>`, `<i>`, `<super>`, `<sub>`, `<font>`. The AI writes mathematical expressions in LaTeX notation (`$\frac{a}{b}$`). A custom parser bridges the two.

### `_extract_braced(s, pos)` — Nested Brace Extractor

```python
def _extract_braced(s, pos):
    if s[pos] != '{':
        return (s[pos], pos + 1)
    depth, i = 0, pos
    while i < len(s):
        if s[i] == '{':   depth += 1
        elif s[i] == '}': depth -= 1
        if depth == 0:
            return s[pos+1:i], i+1
        i += 1
```

Correctly handles nested braces like `\frac{a+b}{c+d}`, extracting `a+b` and `c+d` as separate groups. A regex cannot count brackets — this is the reason for the character-by-character approach.

### `_latex_to_rl(expr)` — Conversion Table

| LaTeX input | ReportLab XML output |
|---|---|
| `\frac{a}{b}` | `(a/b)` |
| `\sqrt{x+1}` | `√(x+1)` |
| `x^{2}` | `x<super>2</super>` |
| `x_{n}` | `x<sub>n</sub>` |
| `\theta`, `\alpha`, `\pi`, `\Omega` | `θ`, `α`, `π`, `Ω` (Unicode) |
| `\leq`, `\geq`, `\neq` | `≤`, `≥`, `≠` |
| `\mathbb{R}`, `\mathbb{Z}` | `ℝ`, `ℤ` |
| `\in`, `\cup`, `\cap`, `\subset` | `∈`, `∪`, `∩`, `⊂` |
| `\therefore`, `\because` | `∴`, `∵` |

The parser is character-by-character, not regex-based, so it handles concatenated expressions like `x^{2}+y^{2}=r^{2}` without lookahead confusion.

### `_process(text)` — Full Conversion Pipeline

1. Strip escape sequences (`\_` → `_`, `\-` → `-`)
2. Guard fill-in-blank underscores inside `$...$` spans (prevents them becoming empty `<sub>` tags)
3. Apply `_latex_to_rl` to all `$...$` and `$$...$$` spans
4. Escape raw `&`, `<`, `>` that appear outside converted tags
5. Allow already-converted XML entities through unchanged
6. Convert `**bold**` → `<b>bold</b>` and `*italic*` → `<i>italic</i>`
7. Run `_balance_xml_tags` to repair any unclosed tags

### `_balance_xml_tags(text)` — XML Auto-Repair

ReportLab's `Paragraph` raises an exception on malformed XML like `<b>text<super>`. This function maintains a tag stack as it walks the text:

- Opening tag → push to stack, emit the tag
- Closing tag found in stack → close all tags opened after it, close the matched tag, reopen the inner ones
- Closing tag not in stack → silently discard (stray)
- End of text → close all uncovered tags in reverse stack order
- Unknown tags (anything not in `{b, i, u, sub, super, font}`) → strip entirely

This transforms potentially crash-inducing AI output into always-valid XML.

### `_safe_para(text, style)` — Last-Resort Fallback

Even after XML repair, edge cases in deeply malformed AI output can still fail. `_safe_para` wraps `Paragraph(text, style)` in `try/except` and falls back to stripping all markup and rendering as plain escaped text. Returns `None` only if even that fails — preventing a single broken question from crashing the entire PDF.

---

## 7. PDF Rendering Engine

**Location:** `create_exam_pdf(text, subject, chapter, board, answer_key, include_key, diagrams, marks)`

This is the largest function in the codebase. It takes raw AI text and produces binary PDF bytes. ReportLab's Platypus "story" API is used: content is described as a list of flowables (Paragraphs, Tables, Spacers, PageBreaks) that the engine flows across pages automatically.

### 7.1 — Page Setup

```python
LM = BM = 17 * mm     # 17mm left/bottom margins — matches official AP/TS exam format
RM = 17 * mm
TM = 13 * mm
PW = A4[0] - LM - RM  # usable page width
doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=LM, rightMargin=RM, ...)
```

### 7.2 — ExamCanvas (Per-Page Decoration)

```python
class ExamCanvas:
    def __call__(self, canvas, doc):
        # Top rule: 1.2pt navy line + 0.5pt blue accent hairline
        # Footer: 0.4pt rule + centred page number
```

ReportLab calls this function after laying out content on each page. The `canvas` object provides raw drawing access, allowing headers and footers to be painted on top of content — ensuring they appear on every page including overflow pages, without being part of the story list. This is the standard ReportLab pattern for recurring page furniture.

### 7.3 — Three-Layer Paper Header

```
┌─────────────────────────────────────────────────┐  ← Navy (#0f2149) fill
│  MATHEMATICS  ·  SETS                      ●   │  White bold text + blue dot
├─────────────────────────────────────────────────┤  ← 2pt blue accent stripe
│  Andhra Pradesh State Board    Total Marks: 100 │  ← Light blue-grey row
└─────────────────────────────────────────────────┘
```

Built as a compound `Table` with explicit `TableStyle` commands. The accent stripe is a zero-height `Table` with a coloured background — ReportLab has no native horizontal rule with fill colour, so a thin coloured table achieves the same effect.

### 7.4 — Style System

`_styles()` returns a `getSampleStyleSheet()` extended with ~20 custom `ParagraphStyle` objects. All styles are created once per PDF and threaded through rendering functions via the `st` parameter — no global mutable state.

| Style name | Font | Size | Used for |
|---|---|---|---|
| `PTitle` | Bold | 12pt | Paper title — white text in navy header |
| `Q` | Regular | 9.5pt | Question text — justified, 22pt hanging indent |
| `QSub` | Regular | 9.5pt | Sub-questions (a), (b), (c) |
| `Opt` | Regular | 9pt | MCQ option text |
| `SecBanner` | Bold | 9.5pt | Section heading text inside banner |
| `KQ` | Bold | 9.5pt | Answer key question numbers |
| `KStep` | Regular | 9.5pt | Answer key solution steps |

### 7.5 — Section Banners

`_sec_banner(text, st, pw, is_key)` builds a compound table:

```
[ 6pt accent bar | "Section C — Short Answer"  text ]
```

The left cell is a 6-point-wide `Table([[""]])` with `C_ACCENT` background — this renders the vertical coloured accent bar. The right cell holds the section label as a `Paragraph`. The outer table has a light background and navy border lines. For answer key banners, the colour scheme inverts to full navy with white text.

### 7.6 — MCQ Option Layout

MCQ options are rendered in a 2-column table to reduce vertical space:

```
(a) First option text         (c) Third option text
(b) Second option text        (d) Fourth option text
```

`_opts_table(opts, st, pw)` groups options in pairs `[(a,c), (b,d)]` and builds a `Table` with `colWidths=[pw/2, pw/2]`. Options are buffered in `pending_opts[]` and flushed when all four are collected or when the next question begins.

### 7.7 — Pipe Table Rendering

`_pipe_table(rows, st, pw)` converts markdown pipe-table rows (used by the AI for Match the Following and data tables) into a styled `Table`:

- Header row: navy background, white bold text, blue accent bottom border
- Data rows: alternating white and light blue (`#f4f6fb`) backgrounds
- Full navy outer border, thin grey internal borders
- Column widths distributed evenly across page width
- `repeatRows=1` so the header row repeats automatically on overflow pages

### 7.8 — Line-by-Line Parser

The core parser is a `while` loop over the lines of the AI output. Each line is classified by a cascade of checks in priority order:

```
if line is a pipe-table row       → buffer into tbl_rows[]
elif we were building a table     → flush_table(), continue parsing
if line is blank                  → Spacer(1, 4)
if line matches _HDR_SKIP         → skip (duplicate AI-generated metadata)
if line matches _FIG_JUNK         → skip (stray figure description text)
if line is a horizontal rule      → HRFlowable
if line starts with [DIAGRAM:     → embed diagram or render placeholder box
if line is a general instruction  → skip (instruction block already in PDF header)
if line matches a section header  → _sec_banner()
if line is an MCQ option          → buffer into pending_opts[]
if line matches a question number → Paragraph with Q style
if line matches a sub-question    → Paragraph with QSub style
else                              → Paragraph with QCont (continuation) style
```

This handles all structural variations in AI output without requiring the AI to produce perfectly formatted text every time.

### 7.9 — AI Noise Stripping

Two pre-processing passes run before the line-by-line parser:

**`_strip_ai_noise(text)`** removes AI preamble ("Sure! Here's your paper...") and closing remarks ("I hope this helps! Please let me know...") by scanning the first 25 and last 10 lines against a compiled pattern of known phrases.

**`_strip_leading_metadata(text, subject, board)`** removes duplicate header lines the AI emits — bare subject names, pipe-formatted board/class/marks rows. These duplicate the PDF header table already built programmatically and must not appear as question text in the paper body.

---

## 8. AI Integration — Multi-Key Round-Robin Failover

**Location:** `_try_one()`, `call_gemini()`

### 8.1 — Model List

Only models with confirmed non-zero daily quota are listed:

```python
_GEMINI_MODELS = [
    "gemini-2.5-flash",                       # Best quality, primary choice
    "gemini-2.5-flash-lite",                  # Faster, lower latency
    "gemini-2.5-flash-lite-preview-06-17",    # Preview alias, same quota pool
    "gemma-3-4b-it",                          # 60 RPD — solid structured output
    "gemma-3-1b-it",                          # 92 RPD — highest raw throughput
]
```

Models with 0 quota (including all `gemini-2.0-flash` and `gemini-1.5-*` variants) were removed after observing consistent 404 and 429 failures in production. Five models with real quota beat eleven models where most return errors immediately.

### 8.2 — `_try_one(model, api_key, prompt)` — Single Attempt

Each `(model, key)` pair is tried here. The function:

1. **Attempts via LangChain first** (structured output, built-in retry logic):
   - Builds a `ChatGoogleGenerativeAI` chain via `_get_lc_chain(model, api_key)`
   - Gemma models use a single human message — Gemma does not support a `system` role via the API
   - Gemini models use `system` + `human` message separation
   - Returns `(text, False, False)` on success
   - Returns `(None, True, False)` on 429 rate-limit
   - Returns `(None, False, True)` on 404 — signals the model is unavailable on all keys

2. **Falls back to direct REST** if LangChain fails for any non-quota reason:
   - `requests.post` to `generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
   - Gemma: `maxOutputTokens: 8192`; Gemini: `maxOutputTokens: 16384`
   - Same return semantics as the LangChain path

### 8.3 — `call_gemini(prompt)` — Round-Robin Orchestrator

The strategy iterates **per model across all keys**, not per key across all models:

```python
active_keys  = [k for k in [GEMINI_KEY, GEMINI_KEY_2, GEMINI_KEY_3] if k]
rate_limited = set()    # (model_name, key_idx) tuples
not_found    = set()    # model_names that returned 404

for model_name in _GEMINI_MODELS:
    for ki, api_key in enumerate(active_keys):
        if model_name in not_found:
            break                              # Skip all keys for this dead model
        if (model_name, ki) in rate_limited:
            continue                           # Skip this (model, key) combo

        text, is_rl, is_nf = _try_one(model_name, api_key, prompt)

        if text:
            return text, None                  # Success — return immediately
        if is_rl:
            rate_limited.add((model_name, ki))
        if is_nf:
            not_found.add(model_name)
            break
```

This maximises the chance of using the best model. `gemini-2.5-flash` is tried on all three keys before falling back to `gemini-2.5-flash-lite`. Gemma models are only used after all Gemini quota is exhausted across all keys.

### 8.4 — Gemma Compatibility

Gemma models require two adjustments compared to Gemini:

```python
is_gemma = 'gemma' in model_name.lower()

# Gemma: no system role — prepend to the human message
if is_gemma:
    prompt_tpl = ChatPromptTemplate.from_messages([
        ("human", system_msg + "\n\n{prompt}"),
    ])
else:
    prompt_tpl = ChatPromptTemplate.from_messages([
        ("system", system_msg),
        ("human", "{prompt}"),
    ])

# Gemma max tokens is 8192 (practical), not 16384
max_tokens = 8192 if is_gemma else 16384
```

---

## 9. Prompt Engineering System

**Location:** `build_prompt()`, `_prompt_board()`, `_prompt_competitive()`, and helpers

Prompts are assembled programmatically from composable components, never hardcoded as monolithic strings.

### 9.1 — `_compute_structure(marks)` — Exact Blueprint Calculator

Returns a dictionary with precise question counts per section. Mark totals always add up exactly to the requested marks — no floating-point rounding errors.

**Preset table for common mark totals** (20 presets, from 10 to 100 marks):

```python
PRESET = {
    20:  (10, 3, 1, 0, 0),   # Section A:10×1=10, B:3×2=6, C:1×4=4 → total 20
    40:  (10, 5, 3, 1, 8),   # Section A:10, B:10, C:12, D:8       → total 40
    100: (20, 10, 10, 4, 5), # Section A:20, B:20, C:40, D:20      → total 100
}
```

For mark totals not in the preset, a dynamic algorithm distributes marks using percentage ratios (20% objective, 25% VSQ, 20% SA, 30% LA, remainder absorbed into VSQ).

### 9.2 — `_difficulty_profile(difficulty)` — Bloom's Taxonomy Weights

Each level is described as a percentage distribution across cognitive levels, with explicit qualitative guidance:

```
Easy:
  25% straightforward recall
  45% single-step application
  20% multi-step application
  10% analysis
  "Avoid trivial questions. Every MCQ must have a plausible wrong option."

Medium:
  10% recall · 30% application · 35% multi-step analysis
  15% evaluation · 10% synthesis/proof
  "At least 40% of questions must challenge above-average students."

Hard:
  0% pure recall · 15% non-trivial application · 40% deep analysis
  30% evaluation and proof · 15% synthesis and novel scenarios
  "80%+ of students should find this challenging.
   Every calculation should involve ≥3 steps. Include edge cases."
```

### 9.3 — `_notation_rules(subject)` — Subject-Specific Constraints

Detects subject type from the subject name string and returns a matching constraint block.

**For all STEM subjects**, the math notation block specifies:

```
• All expressions inside $...$: $x^{2}$  $\frac{a}{b}$  $\sqrt{b^2-4ac}$
• Chemical formulas: $H_2O$  $CO_2$  $H_2SO_4$
• Powers/subscripts: $a^{3}$  $v_0$  — never write as plain a3 or v0
• Units outside $: write '5 cm', '$F = ma$ where F is in newtons'
• Fill blanks: __________ (ten underscores, always outside $...$)
```

**For each subject type**, a diagram constraint block is added. The key design principle is accuracy over quantity:

```
GOLDEN RULE: Only add [DIAGRAM:] when the question REQUIRES a visual
to be understood or answered.

NEVER add a diagram to:
  - Pure algebraic questions (solve for x, find the value of k)
  - Number theory (HCF, LCM, prime factorisation)
  - Probability (coin tosses, ball-in-bag)
  - Trigonometric identity proofs
  - Arithmetic/AP/GP sequences

ALWAYS add a diagram to:
  - Geometry questions (triangles, circles, BPT proof)
  - Coordinate geometry (plot points, find area on grid)
  - Heights and distances / angles of elevation/depression
  - Circuit diagrams, ray diagrams, optics
  - Biology labelling (cell, heart, flower, digestive system)
  - Chemistry apparatus setups
```

This constraint prevents the hallucination problem where the AI forces a diagram onto every question, including algebraic ones where it either invents an irrelevant figure or repeats the same generic diagram multiple times.

### 9.4 — Assembled Prompt Structure

The final prompt is built in sections, totalling approximately 90 lines:

```
1.  Role definition
    "You are a senior AP State Board Class 10 Mathematics paper setter..."

2.  Paper metadata
    Subject · Chapter · Board · Class · Total Marks · Time limit · Difficulty

3.  Section structure
    Exact question counts: "Section A: 10 MCQ, 5 fill-blank, 5 match.
    Section B: 5 × 2M. Section C: 9 questions, attempt any 7, each 4M..."

4.  Content quality rules
    MCQ distractor policy · Fill-blank format · OR requirement for long answers

5.  Diagram rules (from _notation_rules)
    When to include [DIAGRAM:] · When never to include it

6.  Notation rules (from _notation_rules)
    LaTeX-style math notation requirements

7.  Answer key format
    Section A: letter answers · Section B/C/D: full worked solutions

8.  Output format priming
    First two lines the AI must output — dramatically reduces preamble generation
```

### 9.5 — `split_key(text)` — Paper/Key Separator

After generation, the AI output is split into question paper and answer key. The function tries eight regex patterns with decreasing specificity, then falls back to line-by-line scanning:

```python
patterns = [
    r'\nANSWER KEY\n',
    r'\n---\s*ANSWER KEY\s*---\n',
    r'(?i)\nANSWER KEY:?\s*\n',
    r'(?i)\n\*+\s*ANSWER KEY\s*\*+\s*\n',
    r'(?i)\n#{1,3}\s*ANSWER KEY\s*\n',
    r'(?i)\nANSWER\s+KEY\s+(?:&|AND)\s+SOLUTIONS?\s*\n',
    r'(?i)\nSOLUTIONS?\s*(?:&\s*ANSWER\s*KEY)?\s*\n',
]
```

The line scanner normalises lines to uppercase and strips all non-alphabetic characters before comparing against a list of known separator patterns. The answer key portion must have more than 30 characters to pass the sanity check — preventing false-positive splits on short decorative lines.

---

## 10. Diagram Generation Pipeline

**Location:** `generate_diagram_svg()`, `_get_diag_context()`, `svg_to_rl_drawing()`

### 10.1 — Tag Extraction

```python
full_text = paper_text + "\n" + (answer_key or "")
diag_descs_raw = re.findall(
    r'\[DIAGRAM:\s*([^\]]+)\]', full_text, re.IGNORECASE
)
# dict.fromkeys preserves insertion order while deduplicating
unique_descs = list(dict.fromkeys(d.strip() for d in diag_descs_raw if d.strip()))
```

The same description appearing in both the question paper and the answer key is generated only once, then reused for both.

### 10.2 — Parallel Generation

```python
max_w = max(1, min(6, len(unique_descs)))
with ThreadPoolExecutor(max_workers=max_w) as ex:
    futures = {ex.submit(generate_diagram_svg, d): d for d in unique_descs}
    try:
        for future in as_completed(futures, timeout=150):    # 150s wall clock
            svg = future.result(timeout=100)                 # 100s per diagram
    except TimeoutError:
        pass  # Use whichever diagrams completed in time
```

Up to 6 workers run concurrently. The wall-clock timeout is 150 seconds and the per-diagram timeout is 100 seconds. This is a deliberate balance: too short and diagrams silently fail; too long and the response risks hitting Vercel's 300-second function timeout.

### 10.3 — `_get_diag_context(description)` — Type Recognition

Matches the description string against a priority-ordered list of phrases to select the appropriate drawing instruction set:

```python
priority_keys = [
    ("tangent from external", "tangent"),
    ("basic proportionality", "bpt"),
    ("thales", "bpt"),
    ("circuit", "circuit"),
    ("convex lens", "lens"),
    ("velocity-time", "motion"),
    ("free body", "force"),
    ("human heart", "heart"),
    ("bohr model", "atom"),
    ("ogive", "ogive"),
    ("venn diagram", "venn"),
    # ... 40+ phrases
]
```

Longer, more specific phrases are tested first to avoid false matches. "tangent" alone could match many circle questions; "tangent from external" specifically targets the tangent-from-external-point theorem.

Each matched key maps to a detailed drawing instruction in `_DIAG_CONTEXT` — specifying exact pixel coordinates, element placement, label positions, line styles, and colour fills for that diagram type.

### 10.4 — SVG Generation Prompt

`generate_diagram_svg(description)` calls `_call_gemini_for_svg(prompt)` with a structured 30-line technical prompt:

```
DIAGRAM REQUIRED: "{description}"

DRAWING INSTRUCTIONS FOR THIS TYPE:
{drawing_instructions from _get_diag_context}

MANDATORY SVG RULES:
• Output ONLY raw SVG — no markdown, no explanation
• viewBox="0 0 560 360" width="560" height="360"
• First element: <rect x="0" y="0" width="560" height="360" fill="white"/>
• Primary lines: stroke="#111111" stroke-width="2.5"
• Secondary lines: stroke="#333333" stroke-width="1.5"
• All labels: font-family="Arial,Helvetica,sans-serif" font-size="14" font-weight="bold"
• EVERY vertex, component, angle, measurement must be labelled
• Labels must never overlap lines or other labels — offset ≥12px
• Right angles: mark with a 7×7 square
• Equal sides: tick marks across midpoint
• Arrowheads: filled polygon triangles, fill="#111111"
• Permitted elements: svg, g, line, circle, ellipse, rect, polygon,
                      polyline, path, text, tspan
• FORBIDDEN: image, use, defs, symbol, clipPath, filter, style blocks, JavaScript
```

The generation model uses `temperature=0.4` and `maxOutputTokens=8192`. The higher temperature (compared to paper generation at 0.15) encourages varied, well-proportioned layouts rather than reusing a single rectangular arrangement for all diagrams.

### 10.5 — SVG to ReportLab Conversion

`svg_to_rl_drawing(svg_str, width_pt)` parses the SVG XML tree and converts each element to a ReportLab `Drawing` shape:

| SVG element | ReportLab shape | Notes |
|---|---|---|
| `<line>` | `Line` | Direct attribute mapping |
| `<circle>` | `Circle` | cx, cy, r |
| `<ellipse>` | 36-point `Polygon` | Approximated — ReportLab has no native ellipse |
| `<rect>` | `Rect` | With optional rx for rounded corners |
| `<polygon>`, `<polyline>` | `Polygon`, `PolyLine` | Points parsed from space/comma string |
| `<path d="...">` | `PolyLine` or `Polygon` | Parsed via `_parse_path_d()` |
| `<text>` | `String` | Font family and size from SVG attributes |
| `<g>` | Group transform applied | All children processed recursively |

**Coordinate flip:** SVG Y-axis increases downward; ReportLab's Y-axis increases upward. Every coordinate is transformed:

```python
def ty(y):
    return height_pt - float(y) * scale_x
```

**Bezier curve approximation:** Cubic Bezier segments (`C`/`c` path commands) are sampled at 8 intermediate points using the standard parametric formula `B(t) = (1-t)³P₀ + 3(1-t)²tP₁ + 3(1-t)t²P₂ + t³P₃` for `t` in `{0, 1/7, 2/7, ... 1}`. This gives sufficient visual accuracy for smooth curves in exam diagrams without implementing a full vector renderer.

**SVG arc conversion:** Arc commands (`A`/`a`) use the SVG arc-to-centre-parameterisation algorithm to find the centre point and angular sweep, then sample `max(12, int(sweep * scale))` points proportional to arc length.

### 10.6 — Fuzzy Diagram Matching

When the parser encounters a `[DIAGRAM: description]` tag, it looks up the pre-generated SVG dictionary:

```python
# 1. Exact string match
if desc in diagrams:
    use diagrams[desc]

# 2. Fuzzy word-overlap match (handles slight rewording)
desc_words = set(re.findall(r'\w+', desc.lower()))
best_key   = max(diagrams, key=lambda k:
    len(desc_words & set(re.findall(r'\w+', k.lower()))))
if word_overlap_score >= 2:
    use diagrams[best_key]

# 3. Placeholder box if no match
render_placeholder(desc)
```

This handles the common case where the answer key repeats a diagram with slightly different wording than the original question paper.

---

## 11. Flask Routes and Request Lifecycle

### `POST /generate` — Main Generation Endpoint

```
1.  Parse JSON body; sanitise all string fields with .strip()
2.  Resolve board: "Andhra Pradesh" → "Andhra Pradesh State Board"
3.  _compute_structure(marks)       → exact question counts per section
4.  _difficulty_profile(difficulty) → Bloom's taxonomy ratios string
5.  _notation_rules(subject)        → math notation + diagram constraint block
6.  build_prompt(...)               → ~90-line assembled prompt string
7.  call_gemini(prompt)             → 60–90 seconds (round-robin across models/keys)
8.  split_key(generated_text)       → (paper_text, answer_key_text)
9.  re.findall('[DIAGRAM:...]')     → unique_descs[]
10. ThreadPoolExecutor(max_workers=6)
       → generate_diagram_svg(desc) × N in parallel
       → call_gemini(svg_prompt) per diagram
       → extract SVG, validate minimum length
       → collect into diagrams{} dict (150s wall-clock timeout)
11. register_fonts() — no-op if already registered
12. create_exam_pdf(paper_text, ..., diagrams=diagrams)
       → strip AI noise, strip duplicate metadata
       → build 3-layer navy header table
       → line-by-line parser: banners, MCQs, tables, diagrams, questions
       → ExamCanvas: page rules and footer on every page
       → BytesIO → bytes
13. base64.b64encode(pdf_bytes)     → pdf_b64
14. create_exam_pdf(..., include_key=True) → PDF with answer key appended
15. base64.b64encode(key_pdf_bytes) → pdf_key_b64
16. return jsonify({
        success: true,
        pdf_b64: ...,
        pdf_key_b64: ...,
        paper: paper_text,
        answer_key: answer_key_text,
        board: ..., subject: ..., ...
    })
```

**Why base64 in JSON?** The alternative is a two-request pattern where the first call generates and stores the PDF server-side, and the second call downloads it. Single-response design eliminates server-side storage entirely — which is impossible on stateless serverless anyway — and allows the frontend to trigger a browser download immediately.

### `POST /download-pdf` — History Re-Download

Accepts `paper_text` and `answer_key` from browser-stored history and re-renders the PDF on demand, without involving the AI. Returns a binary `send_file(...)` response with `as_attachment=True` — a direct file download, not JSON.

### `GET /health`

Returns the current configuration: which keys are set, model list, LangChain availability. Used for monitoring quota issues and debugging deployment problems.

### `GET /chapters`

Returns `curriculum.json` filtered by `?class=X`. Called once on page load and cached in `curriculumData` — no server hit for subsequent subject or chapter changes within the same session.

---

## 12. Frontend Architecture

**Location:** `static/js/app.js` (~1,400 lines, vanilla JavaScript)

### Global State

```javascript
var curriculumData   = {};  // Curriculum JSON, fetched once from /chapters
var currentPaper     = '';  // Last generated question paper text
var currentAnswerKey = '';  // Last generated answer key text
var currentMeta      = {};  // {board, subject, chapter, marks, difficulty}
```

`var` (not `const`/`let`) is intentional for global state. `var` declarations are accessible from `onclick=` attributes in HTML without explicit exposure. `let`/`const` are used inside function bodies where appropriate.

### Progressive Form Reveal

`updateFormVisibility()` shows and hides the six form cards by toggling the CSS class `collapsed`. All HTML is in the DOM at all times — no dynamic injection. The pattern:

```javascript
function updateFormVisibility() {
    const hasClass   = !!classEl.value;
    const hasSubject = !!subjectEl.value;
    const hasChapter = !!chapterEl.value;

    card2.classList.toggle('collapsed', !hasType);
    card3.classList.toggle('collapsed', !hasBoard);
    card4.classList.toggle('collapsed', !hasClass);
    // ...
}
```

Called on every `change` event across all form controls. Simpler than a state machine and sufficient for a strictly linear six-step form.

### Loading Stage System

Five stages are mapped to calibrated delays tuned against the actual generation timeline:

```javascript
const STAGES = [
    { label: 'Reading your selections',    pct: 8  },
    { label: 'Writing the questions',      pct: 38 },
    { label: 'Writing the answer key',     pct: 62 },
    { label: 'Laying out the paper',       pct: 82 },
    { label: 'Creating the PDF',           pct: 96 },
];

// Delays match the actual generation timeline empirically
const delays = [0, 6000, 22000, 50000, 78000];
```

Stage 1 fires at 0ms. Stage 5 fires at 78s — just before the typical 80–90s response arrives. All stage timers are stored in `_loadStepTimers[]` and cleared immediately when the response arrives, preventing stages from advancing after completion.

### PDF Download Mechanism

```javascript
function _b64Download(b64, filename) {
    const binary = atob(b64);
    const buffer = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        buffer[i] = binary.charCodeAt(i);
    }
    const blob = new Blob([buffer], { type: 'application/pdf' });
    const url  = URL.createObjectURL(blob);
    const a    = Object.assign(document.createElement('a'),
                               { href: url, download: filename });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
}
```

`atob()` decodes base64 to a binary string. `charCodeAt` extracts each byte value into a `Uint8Array`. The `Blob` is typed `application/pdf` so the browser treats it as a file download rather than navigation. The object URL is revoked after 60 seconds — long enough for slow file systems to complete writing before the memory is released.

### Theme System

All colour usage in `style.css` references CSS custom properties (`var(--ac)`, `var(--ink)`, etc.). Changing eight properties on `:root` instantly re-themes every element without touching a single CSS rule:

```javascript
function applyAppTheme(themeIndex, isDark) {
    const t = THEMES[themeIndex];
    const root = document.documentElement;
    root.style.setProperty('--ac',   t.ac);
    root.style.setProperty('--ac2',  t.ac2);
    root.style.setProperty('--acg',  t.acg);
    root.style.setProperty('--acd',  t.acd);
    // ... 8 properties total
    root.setAttribute('data-theme', isDark ? 'dark' : '');
}
```

### History Storage Architecture

Paper history is split across two `localStorage` key patterns to avoid hitting the browser's 5MB quota:

```javascript
// Metadata array (small, always loaded)
localStorage.setItem('ec_history', JSON.stringify([
    { id, board, subject, marks, difficulty, timestamp, hasKey },
    // up to 10 entries
]));

// Paper text stored separately per item (can be large)
localStorage.setItem(`ec_p_${id}`, paperText);
localStorage.setItem(`ec_k_${id}`, keyText);
```

When the history list exceeds 10 items, both the metadata entry and the corresponding per-item keys are pruned. This ensures storage does not grow unboundedly regardless of how many papers a user generates.

---

## 13. Data Layer

### `curriculum.json` — Dual-Mode Subject Tree

```json
{
  "6": {
    "Mathematics": ["Knowing Our Numbers", "Whole Numbers", "Playing with Numbers", ...],
    "Science": ["Food: Where Does it Come From?", "Components of Food", ...],
    "Social Studies": ["What, Where, How and When?", ...]
  },
  "10": {
    "Mathematics": ["Real Numbers", "Polynomials", "Pair of Linear Equations", ...],
    "Science": ["Chemical Reactions and Equations", "Acids, Bases and Salts", ...]
  },
  "NTSE": {
    "MAT": ["Number Series", "Verbal Analogy", "Coding-Decoding", ...],
    "SAT Science": ["Physics", "Chemistry", "Biology"],
    "SAT Social Science": ["History", "Geography", "Political Science", "Economics"]
  }
}
```

Top-level keys are class numbers as strings and exam names as strings. The same `updateSubjects()` / `updateChapters()` JavaScript functions serve both board and competitive exam modes — the lookup path `curriculumData[selectedClass][selectedSubject]` is identical.

### `exam_patterns/ap_ts.json`

Encodes the official AP/TS SSC blueprint: section names, question counts, marks per question, and section totals. Used primarily for the Paper Estimate panel displayed in the sidebar. Actual question counts sent to the AI are computed dynamically by `_compute_structure()`, which adapts to any requested mark total rather than being constrained to the fixed presets in this file.

---

## 14. Deployment on Vercel Serverless

### `vercel.json`

```json
{
  "version": 2,
  "builds": [{ "src": "api/index.py", "use": "@vercel/python" }],
  "routes": [{ "src": "/(.*)", "dest": "/api/index.py" }]
}
```

All HTTP traffic routes to the Python function. Static files under `/static/` are automatically served by Vercel's CDN edge network before the request reaches the function — no explicit static routing needed.

### `api/index.py`

```python
from app import app

handler = app
```

Two lines. Vercel's Python runtime expects a WSGI `app` object named `handler`. This thin adapter imports the Flask application from `app.py` and exposes it.

### Serverless Constraints and Mitigations

| Constraint | Impact | Mitigation |
|---|---|---|
| No persistent memory between requests | `_fonts_registered` flag resets on cold start | `register_fonts()` checks the flag and is idempotent — safe to call on every request |
| No writable file system | PDFs cannot be written to disk between requests | PDFs are encoded as base64 and returned in the JSON response body |
| 300-second function timeout | Long Gemini calls plus diagram generation could exceed the limit | Diagram concurrency capped at 6 workers; wall-clock timeout capped at 150s, leaving 150s headroom |
| Cold starts (3–5s extra) | First request after inactivity is slower | Acceptable for a generation tool with an 80s baseline; no mitigation needed |
| No background threads after response | Cannot do async work post-response | `ThreadPoolExecutor` completes within the request — all threads finish before `return jsonify(...)` |

### Environment Variables (Vercel Dashboard)

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Primary Gemini API key |
| `GEMINI_API_KEY_2` | Recommended | Second key for round-robin failover |
| `GEMINI_API_KEY_3` | Optional | Third key for round-robin failover |
| `SMTP_EMAIL` | Optional | Gmail address for error alert emails |
| `SMTP_PASSWORD` | Optional | Gmail App Password (16 characters) |
| `ALERT_EMAIL` | Optional | Error alert recipient address |

---

## 15. Complete Request Trace

A single click of the Generate button triggers the following sequence across browser, network, and server:

```
Browser
│
├─ onclick="generatePaper()"
│   Validate all 6 form fields — return early if any empty
│   showLoading(true) — modal appears, trivia game starts
│   Stage 1 fires immediately: "Reading your selections"
│   fetch('/generate', {
│       method: 'POST',
│       body: JSON.stringify({ board, class, subject, chapter,
│                              marks, difficulty, instructions })
│   })
│
│   ← Stage 2 fires at  6s: "Writing the questions"
│   ← Stage 3 fires at 22s: "Writing the answer key"
│   ← Stage 4 fires at 50s: "Laying out the paper"
│   ← Stage 5 fires at 78s: "Creating the PDF"
│
Server: POST /generate
│
├─ JSON body parsed, strings stripped
├─ board resolved to full name
├─ _compute_structure(marks)       → exact section counts
├─ _difficulty_profile(difficulty) → Bloom's ratio string
├─ _notation_rules(subject)        → notation + diagram constraint block
├─ build_prompt(...)               → ~90-line prompt assembled
│
├─ call_gemini(prompt)
│   for model in [gemini-2.5-flash, gemini-2.5-flash-lite, gemma-3-4b-it, ...]:
│       for ki, key in enumerate([key1, key2, key3]):
│           _try_one(model, key, prompt)
│               → LangChain attempt  (system + human message)
│               → REST fallback      (direct POST to Gemini API)
│           if success:   return text immediately
│           if 429:       mark (model, ki) as rate-limited
│           if 404:       mark model as unavailable, skip remaining keys
│
├─ split_key(generated_text)       → (paper_text, key_text)
│
├─ re.findall('[DIAGRAM:...]')     → 4–8 unique diagram descriptions
│
├─ ThreadPoolExecutor(max_workers=6)
│   for each description, in parallel:
│       generate_diagram_svg(description)
│           _get_diag_context(desc) → detailed drawing instructions
│           build 30-line SVG prompt
│           _call_gemini_for_svg(prompt) → round-robin across models/keys
│           extract SVG block from response
│           validate: length > 300 chars, contains <svg>
│           return SVG string
│   collect into diagrams{} dict
│   (150s wall-clock timeout — partial results are used if full timeout hit)
│
├─ register_fonts() — no-op if already registered this cold-start
│
├─ create_exam_pdf(paper_text, subject, ..., diagrams=diagrams)
│   _strip_ai_noise(text)
│   _strip_leading_metadata(text, subject, board)
│   Build 3-layer navy header table
│   ExamCanvas registered as page callback
│   Line-by-line parser loop:
│       Pipe table rows → _pipe_table() → styled Table
│       Section headers  → _sec_banner() → coloured banner
│       MCQ options      → buffer → _opts_table() when all 4 collected
│       [DIAGRAM:...]   → svg_to_rl_drawing() or placeholder box
│       Questions        → _safe_para() with _process() for math
│   doc.build(story) → ReportLab flows content, calls ExamCanvas per page
│   BytesIO → binary bytes
│
├─ base64.b64encode(pdf_bytes)     → pdf_b64
│
├─ create_exam_pdf(..., include_key=True)
│   Same as above, plus:
│       PageBreak after questions
│       Answer key header banner
│       Answer key lines parsed with KQ / KStep styles
│   → key_pdf_bytes → pdf_key_b64
│
└─ return jsonify({
       success: true,
       pdf_b64: "...",        ← question paper only
       pdf_key_b64: "...",    ← paper with answer key
       paper: "...",          ← raw text (stored in browser history)
       answer_key: "...",     ← raw text (stored in browser history)
       board: "...",
       subject: "...",
   })

Browser
│
├─ showLoading(false) — modal hides, trivia game stops, stage timers cleared
├─ _b64Download(pdf_b64, "AP_Maths_Sets_20M_Hard.pdf")
│   atob(b64) → binary string → Uint8Array → Blob → object URL
│   Create <a>, click, remove — browser saves file
│   setTimeout(revokeObjectURL, 60000)
├─ addToHistory(meta, paper_text, key_text)
│   Push to ec_history array in localStorage
│   localStorage.setItem('ec_p_{id}', paper_text)
│   localStorage.setItem('ec_k_{id}', key_text)
│   Trim to 10 items if over limit
├─ showPaperReadyPopup()   — "Your exam is ready" success popup
└─ launchConfetti()        — canvas particle animation
```

**Total elapsed time:** 60–90 seconds, of which approximately 95% is Gemini API latency for paper generation and diagram generation combined.

---

*ExamCraft 2026 — Flask · Google Gemini · ReportLab · LangChain · Vercel*