# ExamCraft — Technical Deep Dive

> A complete walkthrough of every architectural decision, algorithm, and technique used in ExamCraft — from prompt engineering to PDF rendering to multi-key AI failover.

**Author:** Laxman Nimmagadda · laxmanchowdary159@gmail.com

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Technology Stack & Rationale](#2-technology-stack--rationale)
3. [Boot Sequence](#3-boot-sequence)
4. [Security Architecture](#4-security-architecture)
5. [Error Reporting System](#5-error-reporting-system)
6. [LaTeX / Math Parser](#6-latex--math-parser)
7. [PDF Rendering Engine](#7-pdf-rendering-engine)
8. [AI Integration — Three-Key Round-Robin Failover](#8-ai-integration--three-key-round-robin-failover)
9. [Prompt Engineering System](#9-prompt-engineering-system)
10. [Diagram Generation Pipeline](#10-diagram-generation-pipeline)
11. [Flask Routes & Request Lifecycle](#11-flask-routes--request-lifecycle)
12. [Frontend Architecture](#12-frontend-architecture)
13. [Data Layer](#13-data-layer)
14. [Deployment on Vercel Serverless](#14-deployment-on-vercel-serverless)

---

## 1. Project Structure

```
ExamCraft/
├── app.py                    ← Entire backend: 3500+ lines
│                               Flask + AI + PDF + Diagrams + Email
├── api/
│   └── index.py              ← Thin Vercel WSGI adapter (2 lines)
├── templates/
│   └── index.html            ← Single-page UI (~1100 lines)
├── static/
│   ├── css/style.css         ← All styles, no framework (~800 lines)
│   ├── js/app.js             ← All frontend logic, vanilla JS (~1400 lines)
│   └── fonts/                ← DejaVu TTF fonts for PDF math symbols
├── data/
│   ├── curriculum.json       ← Subject/chapter tree for classes 6–10 + competitive
│   ├── boards.json           ← Board names and metadata
│   └── exam_patterns/
│       ├── ap_ts.json        ← Official AP/TS SSC blueprint
│       └── competitive.json  ← NTSE/NSO/IMO/IJSO patterns
├── vercel.json               ← Serverless deployment config
└── requirements.txt
```

**Why a single `app.py`?** Vercel's Python serverless runtime expects a single WSGI entry point. Keeping everything in one file eliminates relative import complexity, makes deployment a single `git push`, and makes the entire backend greppable without jumping between files. The cost is file length — mitigated by clear section headings and `# ═══` delimiters throughout.

---

## 2. Technology Stack & Rationale

| Layer | Technology | Why |
|---|---|---|
| Web framework | **Flask 3** | Minimal overhead. No ORM, no template engine needed beyond `render_template`. Simple `@app.route` decoration. |
| AI model | **Google Gemini** (2.5 Flash, 2.0 Flash, Gemma) | Free tier with meaningful daily quota. 1M token context. Fast inference (~30–60s for a full exam paper). |
| AI SDK | **LangChain + ChatGoogleGenerativeAI** | Retry logic, structured `ChatPromptTemplate` with system/human separation, `StrOutputParser` chaining. Falls back to direct `requests.post` if unavailable. |
| PDF | **ReportLab Platypus** | Industry-grade layout engine used for legal, government, and financial documents. Full control over typography, tables, page templates, fonts. No browser dependency. |
| Fonts | **DejaVu Sans** (TTF) | Excellent Unicode coverage for Greek letters (θ, α, π), math operators (√, ∑, ∫), and subscript/superscript characters needed in STEM papers. |
| Deployment | **Vercel Serverless** | Free tier, automatic HTTPS, global CDN for static assets, 300s function timeout. |
| Frontend | **Vanilla JS + CSS** | No build step, no bundler, no framework overhead. Sub-100ms page load. Entire UI in two files. |
| Animations | **GSAP 3** | Professional-grade spring animations and scroll-triggered entrance effects. Loaded from CDN — not bundled. |

---

## 3. Boot Sequence

When Python starts `app.py`, the following executes at module level in order:

```
1. Imports
   ├── Standard library: os, re, json, time, base64, xml.etree, pathlib, io
   ├── ReportLab: SimpleDocTemplate, Paragraph, Table, TableStyle, PageBreak...
   ├── Flask
   └── LangChain (wrapped in try/except ImportError → graceful degradation)

2. Flask app object created
   app = Flask(__name__, template_folder="templates", static_folder="static")

3. @after_request security header hook registered
   (applies to ALL routes globally — no route can skip it)

4. API keys read from environment
   GEMINI_KEY   = os.environ.get("GEMINI_API_KEY",   "").strip()
   GEMINI_KEY_2 = os.environ.get("GEMINI_API_KEY_2", "").strip()
   GEMINI_KEY_3 = os.environ.get("GEMINI_API_KEY_3", "").strip()

5. SMTP email config read from environment
   (connection NOT opened at boot — only when an error occurs)

6. Curriculum and exam pattern JSON files loaded into module-level dicts
   _PATTERN_AP_TS, _PATTERN_COMP, _CURRICULUM

7. Font registration deferred
   _fonts_registered = False  (registered lazily on first PDF call)

8. Routes registered via @app.route decorators

9. if __name__ == "__main__": app.run(...)
   (never executes on Vercel — Vercel imports the app object directly)
```

---

## 4. Security Architecture

**Location:** `apply_security_headers(response)` — `@app.after_request` hook

Every HTTP response — regardless of route — passes through this function before leaving the server.

### Permissions-Policy (most important)

```http
Permissions-Policy: camera=(), microphone=(), geolocation=(), gyroscope=(),
  accelerometer=(), magnetometer=(), usb=(), midi=(), payment=(),
  display-capture=(), bluetooth=(), serial=(), nfc=(), hid=(), ...
```

The `=()` syntax means **no origin is allowed**, including `self`. The browser enforces this at the hardware API level — JavaScript calling `navigator.getUserMedia()` is blocked before any permission prompt ever appears. This is a hardened defense-in-depth measure: even if an attacker injected script into the page, device access would be denied.

### Content-Security-Policy

```http
Content-Security-Policy:
  default-src 'self';
  script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net;
  style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
  connect-src 'self';
  img-src 'self' data:;
  frame-src 'none';
  object-src 'none';
```

`connect-src 'self'` is the critical data-exfiltration guard: all `fetch()` and `XMLHttpRequest` calls must go to the same origin. A compromised CDN script could not phone home.

`'unsafe-inline'` is present for scripts because the UI uses `onclick=` attributes. This is a documented trade-off for simplicity. In a hardened production environment, all inline handlers would migrate to JS event listeners and `'unsafe-inline'` removed.

### Other headers

| Header | Value | Purpose |
|---|---|---|
| `X-Frame-Options` | `DENY` | Prevents clickjacking via iframe embedding |
| `X-Content-Type-Options` | `nosniff` | Prevents MIME confusion attacks |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | Forces HTTPS for 1 year |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limits referrer leakage |
| `Server` | *(removed)* | Removes server fingerprint |

---

## 5. Error Reporting System

**Location:** `send_error_email(error_type, error_msg, traceback_str, user_choices, extra_context)`

### Design principles

1. **Never raises.** An email failure must not cascade into a web response failure. The entire function is wrapped in `try/except Exception`.
2. **Dual format.** Sends both `text/plain` and `text/html` parts in a `MIMEMultipart("alternative")`. Email clients choose the best rendering.
3. **Zero information loss.** The `_capture_user_choices(data)` helper snapshots every field the user submitted — board, subject, marks, difficulty, scope — so any bug is 100% reproducible from the email alone.
4. **Context-rich.** Extra context includes which models were tried, which key was set, LangChain availability, prompt length, and a 100-char prompt preview.

### Triggered by

- `POST /generate` — AI generation returned empty after all models and keys exhausted
- `POST /generate` — any unhandled exception in the route handler
- `POST /download-pdf` — PDF rendering failure

### SMTP mechanism

```python
with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as server:
    server.ehlo()
    server.starttls()           # Upgrade to TLS before credentials
    server.login(email, password)
    server.sendmail(...)
```

Uses Gmail STARTTLS on port 587. Requires a Gmail App Password (16-char), not the account password.

---

## 6. LaTeX / Math Parser

**Location:** `_latex_to_rl(expr)`, `_process(text)`, `_balance_xml_tags(text)`

ReportLab's `Paragraph` renders a subset of XML: `<b>`, `<i>`, `<super>`, `<sub>`, `<font>`. The AI generates math in LaTeX notation (`$\frac{a}{b}$`). The parser bridges these two worlds.

### `_extract_braced(s, pos)` — brace extractor

```python
def _extract_braced(s, pos):
    if s[pos] != '{': return (s[pos], pos + 1)
    depth, i = 0, pos
    while i < len(s):
        if s[i] == '{': depth += 1
        elif s[i] == '}': depth -= 1
        if depth == 0: return s[pos+1:i], i+1
        i += 1
```

Correctly handles nested braces: `\frac{a+b}{c+d}` extracts `a+b` and `c+d` separately. Needed because regex cannot count nested brackets.

### `_latex_to_rl(expr)` — conversion rules

| LaTeX input | ReportLab XML output |
|---|---|
| `\frac{a}{b}` | `(a/b)` |
| `\sqrt{x+1}` | `√(x+1)` |
| `x^{2}` | `x<super>2</super>` |
| `x_{n}` | `x<sub>n</sub>` |
| `\theta` | `θ` (Unicode lookup) |
| `\leq` | `≤` |
| `\mathbb{R}` | `ℝ` |
| `\in` | `∈` |
| `\cup`, `\cap` | `∪`, `∩` |

The parser is character-by-character (not regex-based) so it handles concatenated expressions like `x^{2}+y^{2}=r^{2}` without lookahead confusion.

### `_process(text)` — full pipeline

1. Strip escape sequences: `\_` → `_`, `\-` → `-`
2. Guard fill-in-blank underscores inside `$...$` (prevents them becoming empty `<sub>` tags)
3. Apply `_latex_to_rl` to all `$...$` and `$$...$$` spans
4. Escape raw `&`, `<`, `>` outside of converted tags
5. Re-allow already-converted entities: `&amp;(amp|lt|gt|...)` → unchanged
6. Convert `**bold**` → `<b>bold</b>` and `*italic*` → `<i>italic</i>`
7. Run `_balance_xml_tags` to close any unclosed tags

### `_balance_xml_tags(text)` — XML repair

ReportLab's `Paragraph` crashes if it receives malformed XML like `<b>text<super>`. This function walks the text character-by-character, maintaining a tag stack:

- Opening tag → push to stack, emit tag
- Closing tag found in stack → close all tags opened after it, close it, reopen them
- Closing tag not in stack (stray) → ignore
- End of text → close all unclosed tags in reverse stack order
- Unknown tags (not in `{b, i, u, sub, super, font}`) → strip entirely

This transforms potentially crash-inducing AI output into always-valid XML.

### `_safe_para(text, style)` — last resort

Even after `_balance_xml_tags`, edge cases can still fail. `_safe_para` wraps `Paragraph(text, style)` in try/except and falls back to stripping all tags and escaping as plain text. Returns `None` only if even plain text fails — preventing a single broken question from crashing the entire PDF.

---

## 7. PDF Rendering Engine

**Location:** `create_exam_pdf(text, subject, chapter, board, answer_key, include_key, diagrams, marks)`

This function is the largest in the codebase. It takes raw AI text and produces binary PDF bytes. ReportLab's `Platypus` layout engine is used — a high-level "story" API where content is specified as a list of flowables (Paragraphs, Tables, Spacers, PageBreaks) that the engine flows across pages automatically.

### 7.1 — Page Setup

```python
LM = BM = 17 * mm     # 17mm left/bottom margin — matches official exam format
RM = 17 * mm
TM = 13 * mm          # 13mm top margin
PW = A4[0] - LM - RM  # usable page width
doc = SimpleDocTemplate(buf, pagesize=A4, ...)
```

### 7.2 — ExamCanvas (Page Template)

```python
class ExamCanvas:
    def __call__(self, canvas, doc):
        # Top rule: 1.2pt navy line + 0.5pt blue accent hairline
        # Footer: 0.4pt rule + centered page number
        # Called by ReportLab after EVERY page including overflow pages
```

This is a ReportLab canvas callback pattern. The canvas object gives raw drawing access to the current page after content is placed. Using it for headers/footers ensures they appear on every page including multi-page papers without being part of the story list.

### 7.3 — Three-Layer Header

```
┌─────────────────────────────────────────────┐  ← Navy (#0f2149) fill
│   MATHEMATICS  ·  SETS             ●        │  White bold text + blue dot
├─────────────────────────────────────────────┤  ← 2pt blue accent stripe
│  Andhra Pradesh State Board        Total Marks: 20  │  ← Light blue-grey row
└─────────────────────────────────────────────┘
```

Built as a compound `Table([[title_cell, dot_cell]])` with explicit TableStyle commands. The accent stripe is a 2pt-height Table with `C_ACCENT` background — ReportLab doesn't have a native "horizontal rule with colour" element so a zero-height coloured table achieves the same visual.

### 7.4 — Font and Style System

`_styles()` returns a `getSampleStyleSheet()` extended with ~20 custom `ParagraphStyle` objects. All styles are created once per PDF and passed through every rendering function via the `st` parameter — no global mutable style state.

Key styles and their purpose:

| Style | Font | Size | Use |
|---|---|---|---|
| `PTitle` | Bold | 12pt | Paper title — white text |
| `Q` | Regular | 9.5pt | Question text — JUSTIFY alignment, 22pt hanging indent |
| `QSub` | Regular | 9.5pt | Sub-questions (a), (b), (c) |
| `Opt` | Regular | 9pt | MCQ option text |
| `SecBanner` | Bold | 9.5pt | Section heading text inside banner |
| `KQ` | Bold | 9.5pt | Answer key question number |
| `KStep` | Regular | 9.5pt | Answer key solution steps |

### 7.5 — Section Banners

`_sec_banner(text, st, pw, is_key)` builds a compound table:

```
[ 6pt blue accent bar ] [ "Section IV — Very Short Answer" text ]
```

The left column is a 6-point-wide `Table([[""]])` with `C_ACCENT` background — creates the vertical accent bar. The right column holds the section label `Paragraph`. The outer table has `C_LIGHT` background and `C_NAVY2` border lines. For answer key banners, the background flips to full navy with white text.

### 7.6 — MCQ Option Layout

MCQ options are laid out in a 2-column table to save vertical space:

```
(a) First option text         (c) Third option text
(b) Second option text        (d) Fourth option text
```

`_opts_table(opts, st, pw)` takes a list of `(letter, text)` pairs, groups them in pairs `[(a,c), (b,d)]`, and builds a `Table` with `colWidths=[pw/2, pw/2]`. Options are buffered in `pending_opts` and flushed when all 4 are collected or the next question begins.

### 7.7 — Pipe Table Rendering

`_pipe_table(rows, st, pw)` converts markdown pipe-table rows (from Match the Following and data questions) into a proper `Table`:

- Header row: navy (`#0f2149`) background, white bold text, blue accent bottom border
- Data rows: alternating white / light blue (`#f4f6fb`) backgrounds
- Full navy outer border, thin grey internal borders
- Column widths distributed evenly across page width
- `repeatRows=1` so the header repeats on overflow pages

### 7.8 — Line-by-Line Parser

The core parser is a while loop over `lines`. Each line is classified by a cascade of detectors:

```python
if _is_table_row(line):   → buffer into tbl_rows[]
elif in_table:            → flush_table()
if not s:                 → Spacer(1, 4)
if _HDR_SKIP.match(s):    → skip (duplicate AI metadata)
if _FIG_JUNK.match(s):    → skip (stray figure labels)
if _is_hrule(line):       → HRFlowable
if s.startswith('[DIAGRAM:'): → diagram embedding
if _is_general_instr(s):  → skip (general instructions block)
if _is_sec_hdr(line):     → _sec_banner()
if _is_instr_line(s):     → skip (numbered instruction lines)
if opt_m (MCQ option):    → buffer into pending_opts[]
if q_m (question):        → Paragraph with Q style
if sub_m (sub-question):  → Paragraph with QSub style
else:                     → Paragraph with QCont style
```

This handles all structural variations in AI output without requiring the AI to produce perfectly structured text.

### 7.9 — AI Noise Stripping

Two pre-processing passes run before parsing:

**`_strip_ai_noise(text)`** removes AI preamble ("Sure! Here is your paper...") and closing remarks ("I hope this helps! Let me know...") by scanning the first 25 and last 10 lines against known patterns.

**`_strip_leading_metadata(text, subject, board)`** removes duplicate header lines the AI emits (bare subject name, pipe-formatted board/class/marks row). These duplicate the PDF header table already built programmatically, so they must not appear as question text in the paper body.

---

## 8. AI Integration — Three-Key Round-Robin Failover

**Location:** `_try_one()`, `call_gemini()`

### 8.1 — Model List

Only models with confirmed non-zero daily quota are listed:

```python
_GEMINI_MODELS = [
    "gemini-2.5-flash",                    # Best quality, 32 RPD
    "gemini-2.5-flash-lite",               # Fast, 30 RPD
    "gemini-2.5-flash-lite-preview-06-17", # Preview alias
    "gemma-3-4b-it",                       # 60 RPD — solid structured output
    "gemma-3-1b-it",                       # 92 RPD — highest throughput
]
```

Models with 0/0/0 quota (including all `gemini-2.0-flash`, `gemini-1.5-*` variants) were removed after observing 404 and 429 failures in production. The list is intentionally short — 5 models with real quota beats 11 models most of which error immediately.

### 8.2 — `_try_one(model, api_key, prompt, all_errors)` — Atomic Attempt

Each `(model, key)` combination is tried in this function. It:

1. **LangChain attempt first** (better structured output, retry logic built in):
   - Builds a `ChatGoogleGenerativeAI` chain via `_get_lc_chain(model, api_key)`
   - Gemma models use a human-only message (no `system` role — not supported by Gemma via the API)
   - Gemini models use `system` + `human` separation
   - Returns `(text, False, False)` on success
   - Returns `(None, True, False)` on 429
   - Returns `(None, False, True)` on 404 — signals model is dead everywhere

2. **Plain REST fallback** if LangChain fails for any non-quota reason:
   - Direct `requests.post` to `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
   - Gemma gets `maxOutputTokens: 8192` (Gemma's practical limit); Gemini gets `16384`
   - Same return code semantics as LangChain path

### 8.3 — `call_gemini(prompt)` — Round-Robin Orchestrator

The calling strategy iterates **per model across all keys**, not per key across all models:

```
For each model in [gemini-2.5-flash, gemini-2.5-flash-lite, gemma-3-4b-it, gemma-3-1b-it]:
    Try key1  →  Try key2  →  Try key3
    ↓ success: return immediately
    ↓ 429: mark (model, key_idx) as rate-limited, try next key
    ↓ 404: mark model as dead, skip all remaining keys for this model
```

This maximises the chance of using the best available model. `gemini-2.5-flash` on all 3 keys is exhausted before falling back to `gemini-2.5-flash-lite`. Gemma is only used if all Gemini quota is gone on all keys.

```python
active_keys   = [k for k in [GEMINI_KEY, GEMINI_KEY_2, GEMINI_KEY_3] if k]
rate_limited  = set()    # (model_name, key_idx) tuples
not_found     = set()    # model_names that 404'd

for model_name in _GEMINI_MODELS:
    for ki, api_key in enumerate(active_keys):
        if model_name in not_found: break
        if (model_name, ki) in rate_limited: continue

        text, is_rl, is_nf = _try_one(model_name, api_key, prompt, all_errors)
        if text: return text, None
        if is_rl: rate_limited.add((model_name, ki))
        if is_nf: not_found.add(model_name); break
```

### 8.4 — Gemma Compatibility

Gemma models (`gemma-3-*`) require special handling:

```python
is_gemma = 'gemma' in model_name.lower()

# Gemma: no system role — prepend to human message
if is_gemma:
    prompt_tpl = ChatPromptTemplate.from_messages([
        ("human", system_msg + "\n\n{prompt}"),
    ])
else:
    prompt_tpl = ChatPromptTemplate.from_messages([
        ("system", system_msg),
        ("human", "{prompt}"),
    ])
```

Also: `max_output_tokens=8192` for Gemma (vs 16384 for Gemini), and `top_p=0.9` to slightly widen the output distribution since Gemma is more conservative.

---

## 9. Prompt Engineering System

**Location:** `build_prompt()`, `_prompt_board()`, `_prompt_competitive()`, helpers

Prompts are assembled programmatically from reusable components — never hardcoded strings.

### 9.1 — `_compute_structure(marks)` — Exact Blueprint

Returns a dictionary with precise question counts per section. The mark totals always sum exactly to the requested marks.

For **full papers (≥40M)**:
```
partA = round(marks × 0.20)     # Objective section
  n_mcq   = round(partA × 0.50)
  n_fill  = round(partA × 0.25)
  n_match = partA - n_mcq - n_fill

partB = marks - partA
  vsq_budget = round(partB × 0.25) → n_vsq = budget ÷ 2
  sa_budget  = round(partB × 0.20) → n_sa  = budget ÷ 4
  la_budget  = round(partB × 0.30) → n_la  = budget ÷ 6
  app_budget = remaining           → n_app = budget ÷ 10
```

Remainder after integer division is absorbed into VSQ (simplest question type) to guarantee the grand total is always exactly `marks`. The AI is given the final counts — it does not calculate them.

### 9.2 — `_difficulty_profile(difficulty)` — Bloom's Taxonomy Ratios

```
Easy:
  25% straightforward recall
  45% single-step application
  20% multi-step application
  10% analysis
  "Avoid trivial questions. Every MCQ should have a plausible wrong option."

Medium:
  10% recall · 30% application · 35% multi-step analysis
  15% evaluation · 10% synthesis/proof
  "At least 40% of questions should challenge above-average students."

Hard:
  0% pure recall · 15% non-trivial application · 40% deep analysis
  30% evaluation & proof · 15% synthesis & novel scenarios
  "80%+ of students should find this challenging.
   Every calculation should involve ≥3 steps. Include edge cases."
```

### 9.3 — `_notation_rules(subject)` — Subject-Specific Instructions

Detects whether the subject is math/science:

**Math subjects** receive:
```
• ALL expressions inside $…$: $x^{2}$  $\frac{a}{b}$  $\sqrt{b^2-4ac}$
• Chemical formulas: $H_2O$  $CO_2$
• Powers/subscripts: $a^{3}$  $v_0$  — never write as plain a3 or v0
• Units OUTSIDE $: write '5 cm', '$F = ma$ where F is in newtons'
• Fill blanks: __________ (ten underscores, ALWAYS outside $…$)
```

**Science subjects** additionally receive diagram requirements:
```
• Include [DIAGRAM: detailed description] in ≥30% of written-answer questions
• Examples of required diagram tags: [DIAGRAM: labelled circuit diagram...]
• ⛔ NEVER output [DIAGRAM: Not applicable] — omit the tag entirely if no diagram needed
```

### 9.4 — Prompt Structure for Board Papers

The final prompt passed to Gemini is ~90 lines:

```
1. Role statement: "You are a senior AP State Board Class 10 question-paper setter..."
2. Paper metadata: Subject, Chapter, Board, Class, Total Marks, Time, Difficulty
3. Mandatory structure: exact question counts per section
4. Content quality rules: MCQ distractor policy, fill-blank format, OR requirement for LA
5. Diagram rules: when to include [DIAGRAM:] tags
6. Notation rules: math notation block
7. Answer key rules: format of answers per section type
8. Output format: exact header structure to start with
```

The prompt ends with the literal first two lines the AI should output — this "few-shot priming" dramatically reduces preamble generation.

### 9.5 — `split_key(text)` — Paper/Key Separator

Tries 8 regex patterns to find the `ANSWER KEY` separator line, handling all AI formatting variations:

```python
patterns = [
    r'\nANSWER KEY\n',
    r'\n---\s*ANSWER KEY\s*---\n',
    r'(?i)\nANSWER KEY:?\s*\n',
    r'(?i)\n\*+\s*ANSWER KEY\s*\*+\s*\n',
    r'(?i)\n#{1,3}\s*ANSWER KEY\s*\n',
    r'(?i)\nANSWER\s+KEY\s+(?:&|AND)\s+SOLUTIONS?\s*\n',
    # ... plus line-by-line fallbacks
]
```

Falls back to scanning lines for `"ANSWER KEY"` text normalized by stripping punctuation and case. The key must have >30 characters to pass the sanity check — prevents false-positive splits on short matches.

---

## 10. Diagram Generation Pipeline

**Location:** `generate_diagram_svg()`, `svg_to_best_image()`, `svg_to_rl_drawing()`

### 10.1 — Extraction

```python
diag_descs_raw = re.findall(r'\[DIAGRAM:\s*([^\]]+)\]', full_text, re.IGNORECASE)
unique_descs = list(dict.fromkeys(d.strip() for d in diag_descs_raw if d.strip()))
```

`dict.fromkeys` preserves insertion order while deduplicating — same description appearing in both paper and answer key is generated only once.

### 10.2 — Parallel Generation

```python
with ThreadPoolExecutor(max_workers=4) as ex:
    futures = {ex.submit(generate_diagram_svg, d): d for d in unique_descs}
    try:
        for future in as_completed(futures, timeout=90):   # 90s wall clock
            svg = future.result(timeout=80)                # 80s per diagram
    except TimeoutError:
        pass  # Use whatever diagrams completed in time
```

4 workers run concurrently. Total wall clock is 90 seconds, individual diagram timeout is 80 seconds. This is a hard-won balance: too short and diagrams silently fail; too long and the response blocks Vercel's 300s function timeout.

### 10.3 — `generate_diagram_svg(description)` — Gemini SVG Prompt

Calls `call_gemini()` (full round-robin failover) with a ~40-line technical prompt specifying:

- Fixed `viewBox="0 0 500 320"` canvas
- Mandatory white background rect as first element
- Stroke colours, stroke-widths, font-family, font-size per element type
- Only these elements allowed: `line`, `circle`, `ellipse`, `rect`, `polygon`, `polyline`, `path`, `text`, `tspan`, `g`
- No `<image>`, `<defs>`, `<clipPath>`, `<filter>`, `<foreignObject>`, no CSS, no JavaScript
- Right angles marked with 6×6 squares, angle arcs with labels
- Subject-context injected via `_get_diag_context(description)`:
  ```python
  "triangle" → "clean geometric figure with labelled vertices A B C, altitude or median as required"
  "circuit"  → "electric circuit schematic using standard symbols: battery, resistor, ammeter..."
  "cell"     → "animal/plant cell with organelles: nucleus, mitochondria, chloroplast... labelled"
  ```

### 10.4 — SVG Embedding in PDF

`svg_to_best_image(svg_str, width_pt)`:

1. **wkhtmltoimage path** (high quality PNG, not available on Vercel)
2. **Pure ReportLab SVG renderer** (always available) — `svg_to_rl_drawing()`

`svg_to_rl_drawing()` parses the SVG XML tree and converts each element to ReportLab `Drawing` shapes:

| SVG element | ReportLab shape |
|---|---|
| `<line>` | `Line` |
| `<circle>` | `Circle` |
| `<ellipse>` | Polygon (36-point approximation) |
| `<rect>` | `Rect` |
| `<polygon>`, `<polyline>` | `Polygon`, `PolyLine` |
| `<path d="...">` | Parsed via `_parse_path_d()` → `PolyLine` or `Polygon` |
| `<text>` | `String` |

**Coordinate flip:** SVG Y-axis increases downward; ReportLab Y-axis increases upward. Every `y` coordinate is flipped: `ty(y) = height_pt - float(y) * scale_x`.

**Bezier approximation:** Cubic Bezier curves (`C`/`c` path commands) are approximated by sampling 8 intermediate points along the curve — sufficient visual accuracy for exam diagrams without implementing a full Bezier renderer.

**Arc approximation:** SVG arc commands (`A`/`a`) are converted using the SVG arc-to-center-parameterization algorithm, then sampled at `max(12, steps)` points proportional to arc length and scale.

### 10.5 — Fuzzy Diagram Matching

When a `[DIAGRAM: desc]` tag is encountered in the paper, the pre-generated SVG dictionary is searched:

```python
# 1. Exact key match
if desc in diagrams: ...

# 2. Fuzzy word-overlap match
desc_words = set(re.findall(r'\w+', desc.lower()))
best_key = max(diagrams, key=lambda k:
    len(desc_words & set(re.findall(r'\w+', k.lower()))))
if best_score >= 2: use best_key
```

This handles cases where the answer key repeats a diagram tag with slightly different wording than the question paper used.

---

## 11. Flask Routes & Request Lifecycle

### `POST /generate`

Complete sequence:

```
1.  Parse JSON body, sanitise all string fields with .strip()
2.  Resolve board: "Andhra Pradesh" → "Andhra Pradesh State Board"
3.  _compute_structure(marks)      → exact question counts per section
4.  _difficulty_profile(difficulty) → Bloom's taxonomy ratios
5.  _notation_rules(subject)        → math/science notation block
6.  build_prompt(...)               → ~90-line assembled prompt string
7.  call_gemini(prompt)             → 60–90 seconds (round-robin failover)
8.  split_key(result)               → (paper_text, key_text)
9.  Extract [DIAGRAM:] tags         → unique_descs[]
10. ThreadPoolExecutor × 4 workers  → diagrams{} dict (90s timeout)
11. create_exam_pdf(paper, ...)     → question-only PDF bytes
12. base64.b64encode(pdf_bytes)     → pdf_b64 string
13. create_exam_pdf(..., include_key=True) → full PDF with answer key
14. base64.b64encode(key_pdf_bytes) → pdf_key_b64 string
15. Return JSON: {success, pdf_b64, pdf_key_b64, paper, answer_key, ...}
```

**Why base64 in JSON response?** The alternative is a two-request pattern (first call generates, second call downloads). Single-response eliminates the need to store PDFs server-side between requests (which is impossible on stateless serverless anyway) and allows the frontend to immediately trigger a browser download with `_b64Download()`.

### `POST /download-pdf`

Used for re-downloading from paper history. Accepts `paper_text` + `answer_key` from browser-stored history and re-renders the PDF on demand. Returns binary PDF as `send_file(..., as_attachment=True)` — a direct file download response, not JSON.

### `GET /health`

Returns current configuration state: which keys are set, model list, key strategy. Used for monitoring and debugging quota issues.

### `GET /chapters`

Returns `curriculum.json` filtered by `?class=X`. Called once on page load and cached in `curriculumData` — no server hit for subsequent subject/chapter changes in the same session.

---

## 12. Frontend Architecture

**Location:** `static/js/app.js` (~1400 lines, vanilla JavaScript)

### State Management

```javascript
var curriculumData   = {};   // Curriculum JSON (cached from /chapters)
var currentPaper     = '';   // Last generated paper text
var currentAnswerKey = '';   // Last generated answer key
var currentMeta      = {};   // Board/subject/chapter/marks/difficulty
```

`var` (not `const`/`let`) is used intentionally for global state — `var` declarations are accessible from `onclick=` attributes in HTML. `let`/`const` inside functions are used where appropriate.

### Progressive Form Reveal

`updateFormVisibility()` shows/hides form cards by toggling CSS class `collapsed`. All HTML is in the DOM simultaneously — no dynamic injection. The pattern is:

```javascript
function updateFormVisibility() {
    const hasClass = !!classEl.value;
    const hasSubject = !!subjectEl.value;
    // ...
    card2.classList.toggle('collapsed', !hasClass);
    card3.classList.toggle('collapsed', !hasSubject);
    // ...
}
```

Called on every `change` event. This is simpler than a state machine and sufficient for a linear 6-step form.

### Loading Stage System

Five stages defined with timestamps tuned to the real generation window:

```javascript
const STAGES = [
    { num:'1', line1:'Parsing',     line2:'requirements',       pct: 8  },
    { num:'2', line1:'Generating',  line2:'questions with AI',  pct: 38 },
    { num:'3', line1:'Writing the', line2:'answer key',         pct: 62 },
    { num:'4', line1:'Formatting',  line2:'paper layout',       pct: 82 },
    { num:'5', line1:'Building',    line2:'PDF',                pct: 96 },
];

const delays = [0, 6000, 22000, 50000, 78000]; // milliseconds
delays.forEach((delay, i) => {
    timers.push(setTimeout(() => _setLoaderStage(i), delay));
});
```

Stage 1 fires instantly (0s). Stage 5 fires at 78s — just before the typical 80–90s response arrives. All stage timers are stored in `_loadStepTimers[]` and cleared immediately when the response arrives.

### PDF Download Mechanism

```javascript
function _b64Download(b64, fname) {
    const bin = atob(b64);
    const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([buf], {type:'application/pdf'}));
    const a = Object.assign(document.createElement('a'), {href:url, download:fname});
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000); // 60s to allow slow saves
}
```

`atob()` decodes base64 to a binary string. `charCodeAt` converts each character to a byte value into a `Uint8Array`. The `Blob` is typed as `application/pdf` so the browser handles it as a file download rather than navigation. The object URL is revoked after 60 seconds — long enough for slow file systems to complete writing.

### Theme System

```javascript
const THEMES = [
    { name:'Gold',    ac:'#C8A96E', ac2:'#E0C07E', ac3:'#F4E4BE', ... },
    { name:'Copper',  ac:'#B87333', ... },
    { name:'Silver',  ac:'#A8B8C8', ... },
    // 6 themes total
];

function applyAppTheme(idx, dark) {
    const t = THEMES[idx];
    document.documentElement.style.setProperty('--ac',  t.ac);
    document.documentElement.style.setProperty('--ac2', t.ac2);
    // ... 8 CSS variables set
}
```

All colour usage in `style.css` references `var(--ac)`, `var(--ink)`, `var(--surf)` etc. Changing 8 CSS custom properties on `:root` instantly re-themes every element without touching a single CSS rule.

### History Storage Architecture

Paper history is split across two localStorage key patterns to avoid hitting the 5MB localStorage quota:

```javascript
// Metadata array (always small)
localStorage.setItem('ec_history', JSON.stringify([
    { id, board, subject, marks, difficulty, ts, hasKey },
    ...
]));

// Paper text stored separately per item
localStorage.setItem(`ec_p_${id}`, paperText);
localStorage.setItem(`ec_k_${id}`, keyText);
```

On history trim (max 10 items), both the metadata entry AND the individual paper/key items are pruned. This ensures localStorage doesn't grow unboundedly even for users who generate dozens of papers.

---

## 13. Data Layer

### `curriculum.json` — Dual-Purpose Structure

```json
{
  "6":  { "Mathematics": ["Knowing Our Numbers", "Whole Numbers", ...], "Science": [...] },
  "10": { "Mathematics": ["Real Numbers", "Polynomials", ...], "Science": [...] },
  "NTSE": { "MAT": ["Number Series", ...], "SAT Science": [...] }
}
```

Top-level keys are class numbers as strings AND exam names. The same `updateSubjects()`/`updateChapters()` JavaScript functions work for both board and competitive exam modes — the curriculum lookup is identical: `curriculumData[selectedClass][selectedSubject]`.

### `exam_patterns/ap_ts.json`

Encodes the official AP/TS SSC paper blueprint: section names, question counts, marks per question, and total marks per section. Used primarily for UI display (Paper Estimate panel); actual question counts for the AI prompt are computed dynamically by `_compute_structure()` which adapts to any requested mark total.

---

## 14. Deployment on Vercel Serverless

### `vercel.json`

```json
{
  "version": 2,
  "builds": [{"src": "api/index.py", "use": "@vercel/python"}],
  "routes": [{"src": "/(.*)", "dest": "/api/index.py"}]
}
```

All HTTP traffic routes to the Python function. Static files under `/static/` are served by Vercel's CDN edge network before the request reaches the function.

### `api/index.py`

```python
from app import app
handler = app
```

Two lines. Vercel's Python runtime expects a WSGI `app` object. This thin adapter imports the Flask application from `app.py`.

### Serverless Constraints and Mitigations

| Constraint | Impact | Mitigation |
|---|---|---|
| No persistent memory | `_fonts_registered` flag resets per cold start | `register_fonts()` is idempotent — safe to re-register |
| No file system writes | PDFs cannot be stored between requests | PDFs base64-encoded and sent in response JSON |
| 300s function timeout | Long Gemini calls could time out | 3-key round-robin minimises per-key latency; diagram timeout capped at 90s |
| Cold starts | First request after inactivity takes 3–5s extra | Acceptable for a generation tool; no mitigation needed |
| No background threads | Diagram thread pool runs synchronously within request | `ThreadPoolExecutor` is valid inside a Vercel function — threads complete before response |

### Environment Variables (Vercel Dashboard)

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Primary Gemini key (required) |
| `GEMINI_API_KEY_2` | Second key for round-robin (recommended) |
| `GEMINI_API_KEY_3` | Third key for round-robin (optional) |
| `SMTP_EMAIL` | Gmail sender address for error alerts |
| `SMTP_PASSWORD` | Gmail App Password (not account password) |
| `ALERT_EMAIL` | Error alert recipient |

---

## Full Request Trace

```
Browser
│
├─ onclick="generatePaper()"
│   Validates all 6 form fields
│   showLoading(true) → loading modal appears, trivia game starts
│   Stage 1 fires immediately (0ms)
│   fetch('/generate', {method:'POST', body:JSON.stringify(payload)})
│
│   ←── ~60–90 seconds of network + server processing ──→
│
│   Stage 2 fires (6s)  — "Generating questions with AI"
│   Stage 3 fires (22s) — "Writing the answer key"
│   Stage 4 fires (50s) — "Formatting paper layout"
│   Stage 5 fires (78s) — "Building PDF"
│
Server: POST /generate (app.py)
│
├─ 1.  JSON body parsed, all strings .strip()'d
├─ 2.  Board resolved: "Andhra Pradesh" → "Andhra Pradesh State Board"
├─ 3.  _compute_structure(20) → {n_mcq:2, n_fill:1, n_match:1, n_vsq:4 ...}
├─ 4.  _difficulty_profile("Hard") → Bloom's ratios string
├─ 5.  _notation_rules("Mathematics") → LaTeX notation block
├─ 6.  _prompt_board(...) → 90-line prompt assembled
│
├─ 7.  call_gemini(prompt)
│       active_keys = [key1, key2, key3]
│       for model in [gemini-2.5-flash, gemini-2.5-flash-lite, gemma-3-4b-it, gemma-3-1b-it]:
│           for ki, key in enumerate(active_keys):
│               _try_one(model, key, prompt, errors)
│               → LangChain attempt → REST fallback
│               if text: return immediately
│               if 429: rate_limited.add((model, ki))
│               if 404: not_found.add(model); break key loop
│
├─ 8.  split_key(result) → (paper_text, key_text)
│
├─ 9.  re.findall(r'\[DIAGRAM:...', paper + key) → 6 unique descriptions
│
├─ 10. ThreadPoolExecutor(max_workers=4)
│       → generate_diagram_svg(desc) × 6 in parallel
│       → call_gemini(svg_prompt) per diagram
│       → extract SVG from response
│       → collect into diagrams{} dict
│       90s wall clock, 80s per diagram
│
├─ 11. register_fonts() (no-op if already registered)
│
├─ 12. create_exam_pdf(paper_text, ..., diagrams=diagrams)
│       → _strip_ai_noise() + _strip_leading_metadata()
│       → Build 3-layer navy header table
│       → Line-by-line parser:
│           Section banners, MCQ option tables, pipe tables
│           Question paragraphs with math via _process()
│           Diagram embedding: svg_to_best_image() or placeholder box
│       → ExamCanvas for page rules/footer on every page
│       → BytesIO → bytes
│
├─ 13. base64.b64encode(pdf_bytes) → pdf_b64
├─ 14. create_exam_pdf(..., include_key=True) → pdf with answer key appended
├─ 15. base64.b64encode(key_pdf_bytes) → pdf_key_b64
│
├─ 16. return jsonify({success:True, pdf_b64, pdf_key_b64, paper, answer_key, ...})
│
Browser
│
├─ showLoading(false) → loading modal hides, trivia game stops, stage timers cleared
├─ _b64Download(pdf_b64, "AP_State_Board_Mathematics_Sets.pdf")
│   atob(b64) → Uint8Array → Blob → object URL → <a>.click() → file saved
├─ addToHistory(meta, paper, key) → localStorage
├─ showPaperReadyPopup() → "Your exam is ready" success popup
└─ launchConfetti() → canvas particle animation
```

Total elapsed: 60–90 seconds, of which ~95% is Gemini API latency.

---

*ExamCraft 2026 — Flask · Gemini · ReportLab · LangChain · Vercel*

**Laxman Nimmagadda** · laxmanchowdary159@gmail.com