# ExamCraft — Technical Deep Dive

> A step-by-step walkthrough of every layer of the backend: how it is written, what each piece does, and why each decision was made.

**Author: Laxman Nimmagadda**
Contact: laxmanchowday159@gmail.com

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Technology Stack](#2-technology-stack)
3. [Application Boot Sequence](#3-application-boot-sequence)
4. [Security Layer](#4-security-layer)
5. [Error Reporting System](#5-error-reporting-system)
6. [Font and Style System](#6-font-and-style-system)
7. [LaTeX / Math Parser](#7-latex--math-parser)
8. [PDF Rendering Engine](#8-pdf-rendering-engine)
9. [AI Integration — Gemini with Dual-Key Fallback](#9-ai-integration)
10. [Prompt Engineering System](#10-prompt-engineering-system)
11. [Diagram Generation](#11-diagram-generation)
12. [Flask Routes](#12-flask-routes)
13. [Frontend Architecture](#13-frontend-architecture)
14. [Data Files](#14-data-files)
15. [Deployment (Vercel)](#15-deployment-vercel)
16. [Full Request Lifecycle](#16-full-request-lifecycle)

---

## 1. Project Structure

```
ExamCraft/
├── app.py                  ← Entire backend: Flask + AI + PDF (3100+ lines)
├── api/
│   └── index.py            ← Thin Vercel adapter that imports app.py
├── templates/
│   └── index.html          ← Single-page UI (plain HTML, no template language)
├── static/
│   ├── css/style.css       ← All styles (~520 lines, no framework)
│   ├── js/app.js           ← All frontend logic (~1380 lines, vanilla JS)
│   └── fonts/              ← DejaVu fonts for PDF math symbols
├── data/
│   ├── boards.json         ← Board names and metadata
│   ├── curriculum.json     ← Full subject/chapter tree per class
│   └── exam_patterns/
│       ├── ap_ts.json      ← AP/TS blueprint: question counts per section
│       └── competitive.json← NTSE/NSO/IMO/IJSO patterns
├── vercel.json             ← Serverless deployment config
└── requirements.txt        ← Python dependencies
```

The entire backend lives in a single `app.py`. This is intentional — it makes deployment to Vercel serverless functions trivial (one file = one function) and eliminates import path complexity.

---

## 2. Technology Stack

| Layer | Technology | Why chosen |
|---|---|---|
| Web framework | Flask 3.x | Lightweight, no ORM needed, simple routing |
| AI model | Google Gemini 2.5 Flash | Fast generation, long context (1M tokens), free tier available |
| AI orchestration | LangChain (optional) | Retry logic, prompt templating, output parsing. App works without it via direct REST |
| PDF rendering | ReportLab Platypus | Industry standard, full layout control, no browser dependency |
| Deployment | Vercel Serverless | Free tier, automatic HTTPS, global CDN |
| Frontend | Vanilla JS + CSS | No build step, no framework overhead, instant load |
| Animations | GSAP 3 | Spring animations and scroll-triggered entrance effects |
| Charts | Chart.js 4 | Lightweight doughnut/bar charts for the paper estimate panel |

---

## 3. Application Boot Sequence

When Python starts `app.py`, the following happens in order:

**Step 1 — Imports**
All standard library, ReportLab, Flask, and LangChain imports. LangChain is wrapped in `try/except ImportError` so the app still boots if LangChain is not installed (it falls back to direct Gemini REST calls).

**Step 2 — App object created**
```python
app = Flask(__name__, template_folder="templates",
            static_folder="static", static_url_path="/static")
```

**Step 3 — Security headers registered**
`@app.after_request` registers a hook that runs after every route handler. It intercepts the response object before it leaves the server and adds all security headers. Applied globally — no route can accidentally skip it.

**Step 4 — API keys read**
```python
GEMINI_KEY   = os.environ.get("GEMINI_API_KEY",   "").strip()
GEMINI_KEY_2 = os.environ.get("GEMINI_API_KEY_2", "").strip()
```
Both keys are read at startup. `GEMINI_KEY_2` is the automatic fallback.

**Step 5 — Email system configured**
SMTP credentials read from environment variables. Connection is not opened at boot — only when an error actually occurs.

**Step 6 — Font registration**
`register_fonts()` is called lazily (on first PDF generation), not at boot, to keep startup fast.

**Step 7 — Routes registered**
Python decorators `@app.route(...)` bind URL paths to handler functions.

**Step 8 — Server starts**
```python
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=False)
```
On Vercel, this block never executes — Vercel imports the `app` object directly via `api/index.py`.

---

## 4. Security Layer

**Location:** `app.py` — `apply_security_headers(response)`

Every HTTP response passes through this `@after_request` hook before leaving the server.

**Permissions-Policy** is the most important header for device safety. Each entry uses the syntax `api-name=()` where `()` means "no origin is allowed to use this API, not even self." The browser enforces this at the hardware level — even if JavaScript somehow tried to call `navigator.getUserMedia()`, the browser would block it before any prompt appeared.

**Content-Security-Policy** uses a whitelist model. The default is `default-src 'self'` which blocks everything not explicitly permitted. Specific CDNs are then whitelisted for GSAP and Chart.js. `connect-src 'self'` ensures all XHR/fetch calls must go to the same server — prevents data exfiltration even if an attacker injected script.

**Why `unsafe-inline` in scripts?** The app uses `onclick=` attributes in HTML for simplicity. In a higher-security environment, all inline handlers would be moved to JS event listeners and `unsafe-inline` removed. This is a documented trade-off.

---

## 5. Error Reporting System

**Location:** `app.py` — `send_error_email(...)`

When any route handler crashes, the error is:
1. Caught by the `try/except` in the route handler
2. Formatted into a structured HTML + plain-text email with full traceback, user choices, timestamp, server info
3. Sent to `laxmanchowday159@gmail.com` via SMTP (Gmail App Password, configured via env vars)
4. A clean JSON error response is returned to the browser — never a raw traceback

`_capture_user_choices(data)` snapshots exactly what the user submitted (board, subject, marks, etc.) and includes it in the error email so the developer can reproduce the exact paper that caused the crash.

The function is deliberately non-raising — an email failure must never cascade into a web response failure.

---

## 6. Font and Style System

**Location:** `app.py` — `register_fonts()` and `_styles()`

ReportLab has its own font system separate from CSS. PDF fonts must be embedded in the file to render correctly on any printer.

DejaVu Sans is used because it has excellent Unicode coverage: Greek letters (θ, φ, π), mathematical operators (√, ∑, ∫), and common symbols — all needed for Class 6–10 math and science papers.

`_styles()` returns a dictionary of named `ParagraphStyle` objects — analogous to named CSS classes. All styles are created once per PDF generation and passed through to every rendering function. There is no global mutable style state. Key styles:

| Style name | Use |
|---|---|
| `PTitle` | Paper title — white on navy, centered |
| `PMeta` | Board/class/marks sub-header |
| `Q` | Question body text — 9.5pt, justified |
| `QSub` | Sub-question (a), (b), (c) |
| `Opt` | MCQ option text |
| `SecBanner` | Section header label inside the navy banner |
| `KQ` | Answer key question number |
| `KStep` | Answer key solution step |

---

## 7. LaTeX / Math Parser

**Location:** `app.py` — `_latex_to_rl(expr)` and `_process(text)`

The AI generates math in a mix of formats. ReportLab's `Paragraph` class supports a subset of XML-like tags: `<b>`, `<i>`, `<super>`, `<sub>`. The parser bridges these two worlds.

**`_extract_braced(s, pos)`**
A recursive brace extractor. Given a string and position of `{`, it returns everything until the matching `}`, handling nested braces correctly. Needed to parse `\frac{a+b}{c}` where `a+b` is the numerator.

**`_latex_to_rl(expr)`** converts LaTeX fragments:
```
\sqrt{x+1}    →  √(x+1)
x^{2}         →  x<super>2</super>
x_{n}         →  x<sub>n</sub>
\frac{a}{b}   →  (a/b)
\theta        →  θ   (Unicode mapping)
\alpha, \beta →  α, β
```

**`_process(text)`** is the full text pipeline:
- Strips markdown: `**bold**` → `<b>bold</b>`
- Calls `_latex_to_rl` on detected math spans `$...$`
- Escapes raw `&`, `<`, `>` characters outside of tags
- Runs `_balance_xml_tags` to close any unclosed tags that would crash ReportLab's XML parser

---

## 8. PDF Rendering Engine

**Location:** `app.py` — `create_exam_pdf(...)`

This is the largest function. It takes the raw AI text and produces binary PDF bytes. Here is exactly what happens:

### 8.1 — Header construction

The header is a full-width navy (`#0f2149`) table with three layers:
1. **Title row** — subject name + chapter, white on navy
2. **Accent stripe** — 2pt bright blue line
3. **Meta row** — board name left, total marks right, pale blue-grey background

### 8.2 — ExamCanvas (custom page template)

```python
class ExamCanvas:
    def __call__(self, canvas, doc):
        # Draws: navy top rule, accent hairline, footer rule, page number
        # Called by ReportLab on every page including overflow pages
```

This is a ReportLab "canvas callback" — it runs after each page's content is placed, letting you draw elements on every page without including them in the main story list.

### 8.3 — Line-by-line text parser

The core of `create_exam_pdf` is a line-by-line parser. Each line is classified:

| Detector | Matches |
|---|---|
| `_is_sec_hdr(s)` | "Section I", "PART A", "Section IV" |
| `_is_table_row(s)` | Lines containing pipe characters |
| `_is_divider(s)` | Markdown separator rows `\|---\|---\|` |
| `_is_hrule(s)` | Decorative rules `---`, `===` |
| `_HDR_SKIP` regex | Duplicate metadata lines the AI emits |
| `_FIG_JUNK` regex | Stray figure description lines |

When a section header is detected, `_sec_banner()` creates a full-width coloured banner. When a question line is detected, options are collected and passed to `_opts_table()`.

### 8.4 — `_opts_table(opts, st, pw)`

MCQ options are laid out in a 2×2 table (2 columns, 2 rows) to save vertical space:
```
(a) option A    (c) option C
(b) option B    (d) option D
```

### 8.5 — `_pipe_table(rows, st, pw)`

For Match the Following and data tables, the AI outputs pipe-delimited rows. `_pipe_table` creates a proper ReportLab `Table` with:
- Navy background header row with white bold text
- Bright blue accent border under the header
- Alternating white/light-blue row backgrounds for data rows
- Full outer navy border and thin internal cell borders

### 8.6 — Diagram embedding

When a `[DIAGRAM: description]` tag is encountered, the SVG (pre-generated in parallel before PDF build) is passed to `svg_to_best_image()` which renders it at 88% of page width. If no SVG was generated, a styled placeholder box is inserted with a labelled navy header and a dotted inner drawing area.

### 8.7 — Answer key section

If `include_key=True`, the key text is parsed after a `PageBreak`. It gets its own navy banner header styled identically to the paper header.

---

## 9. AI Integration

**Location:** `app.py` — `_call_gemini_with_key()` and `call_gemini()`

### Model priority list

```python
_GEMINI_MODELS = [
    "gemini-2.5-flash-preview-05-20",   # Best quality, tried first
    "gemini-2.5-flash",                  # Stable alias
    "gemini-2.5-flash-lite-preview-06-17",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    # ... small/legacy models last
]
```

### `_call_gemini_with_key(prompt, api_key)` — single-key attempt

Tries the model list with one API key. Returns a 3-tuple: `(text, error_summary, rate_limited_bool)`.

The `rate_limited_bool` is the key addition: if **two or more models return HTTP 429**, the function stops immediately and returns `rate_limited=True`. This tells the caller to switch keys without wasting time trying 8 more models on an exhausted quota.

```python
elif resp.status_code == 429:
    rate_limit_count += 1
    all_errors[model_name] = "quota/rate-limit (429)"
    if rate_limit_count >= 2:
        # Signal caller to try backup key immediately
        return None, summary, True
    break
```

### `call_gemini(prompt)` — dual-key orchestrator

```python
def call_gemini(prompt):
    # 1. Try primary key
    text, err, rate_limited = _call_gemini_with_key(prompt, GEMINI_KEY)
    if text: return text, None

    # 2. If rate-limited OR fully exhausted, try backup key
    if GEMINI_KEY_2:
        text, err, _ = _call_gemini_with_key(prompt, GEMINI_KEY_2)
        if text: return text, None

    return None, combined_error
```

The LangChain path is tried first (top 4 capable models only — Gemma models are excluded as they don't produce structured exam output). If LangChain is unavailable or fails, direct REST calls are made to the same models.

---

## 10. Prompt Engineering System

**Location:** `app.py` — `build_prompt(...)` and helpers

Prompts are not static strings — they are programmatically assembled from multiple components.

### `_compute_structure(marks)` — exact mark allocation

Returns precise question counts per section. For 100 marks:
- Part A (20M): 10 MCQ + 5 Fill-in-Blank + Match the Following
- Section IV (16M): 8 × 2M Very Short Answer
- Section V (16M): give 6, attempt any 4 × 4M Short Answer
- Section VI (24M): give 6, attempt any 4 × 6M Long Answer (each with OR option)
- Section VII (20M): give 3, attempt any 2 × 10M Application

This mirrors the official AP/TS State Board blueprint. The AI is told exact counts — not asked to figure them out.

### `_difficulty_profile(difficulty)` — question type ratios

```
Easy:   25% recall · 45% single-step · 20% multi-step · 10% analysis
Medium: 10% recall · 30% application · 35% multi-step · 15% evaluation · 10% synthesis
Hard:    0% recall · 15% application · 40% deep analysis · 30% proof · 15% novel scenarios
```

### `_notation_rules(subject)` — subject-specific notation

Math subjects get: `$...$` for all expressions, `\frac{}{}` for fractions, `\sqrt{}`, `\theta`, SI units outside `$`. Science subjects additionally get diagram requirements (≥30% of written questions must have a `[DIAGRAM:]` tag).

### `_prompt_board(...)` — state board prompt

The full prompt for state board papers is ~80 lines and includes:
- Exact structure with question counts
- Quality rules (MCQ distractors must reflect real misconceptions, not random values)
- Notation rules for the subject
- An instruction to avoid AI preamble ("Sure! Here is...") — without this Gemini frequently adds commentary that breaks the parser
- Instruction to end with `ANSWER KEY` on its own line

### `split_key(text)` — separate paper from answer key

Finds the `ANSWER KEY` separator line the AI was instructed to include. If the separator is absent (occasional AI non-compliance), a heuristic scans line-by-line for "ANSWER KEY" or "ANSWERS" near the end of the text.

---

## 11. Diagram Generation

**Location:** `app.py` — `generate_diagram_svg()`, `svg_to_best_image()`, `svg_to_rl_drawing()`

### Pipeline

1. **Extract** — `re.findall(r'\[DIAGRAM:\s*([^\]]+)\]', full_text)` collects all diagram descriptions from paper + key
2. **Deduplicate** — same description appearing in both paper and key is only generated once
3. **Generate in parallel** — `ThreadPoolExecutor(max_workers=3)` generates all diagrams concurrently with a 25-second total timeout
4. **Embed** — each SVG is matched to its `[DIAGRAM:]` tag (exact match first, then fuzzy word-overlap match)

### `generate_diagram_svg(description)`

Calls Gemini with a ~30-line technical prompt specifying exact SVG requirements:
- `viewBox="0 0 500 320"` fixed canvas
- Background rect must be white
- Stroke colours, font families, font sizes — all specified
- Only basic elements allowed: `line`, `circle`, `rect`, `polygon`, `path`, `text`
- No `<image>`, no `<defs>`, no CSS, no JavaScript
- Every label must be placed without overlapping lines

### `svg_to_best_image(svg_str, width_pt)`

Priority chain:
1. High-quality PNG via `wkhtmltoimage` (if available — not available on Vercel)
2. Pure ReportLab SVG renderer (always available)

The ReportLab SVG renderer (`svg_to_rl_drawing`) parses the SVG XML and converts each element to a ReportLab `Drawing` shape. Coordinate system is flipped (SVG Y-axis is inverted vs ReportLab). Bezier curves are approximated by sampling 8 intermediate points.

Diagrams are rendered at **88% of page width** — wide enough to be clearly readable, with a subtle border frame and padding.

---

## 12. Flask Routes

**Location:** `app.py` — routes

### `GET /` → `index()`
Returns `render_template("index.html")`. No logic — just serves the page.

### `POST /generate` → `generate()`

Exact sequence:
1. Parse and sanitise JSON body (`.strip()` all string fields)
2. Resolve board name: `"Andhra Pradesh"` → `"Andhra Pradesh State Board"`
3. Call `build_prompt(...)` to assemble the prompt
4. Call `call_gemini(prompt)` — ~1–1.5 minutes of API latency
5. Call `split_key(result)` → `(paper_text, key_text)`
6. Extract `[DIAGRAM:]` tags, generate SVGs in parallel
7. Call `create_exam_pdf(paper_text, ...)` → PDF bytes
8. Base64-encode: `base64.b64encode(pdf_bytes).decode()`
9. Also build a second PDF with the answer key appended
10. Return JSON: `{"success": true, "pdf_b64": "...", "pdf_key_b64": "...", "paper": "...", "answer_key": "..."}`

The PDF is base64-encoded in the JSON response so the frontend triggers an immediate download without a second HTTP request. Client decodes: `atob(b64)` → `Uint8Array` → `Blob` → object URL → programmatic `<a>` click.

On any error, `send_error_email` is called and a clean `{"success": false, "error": "..."}` is returned — never a raw traceback.

### `POST /download-pdf` → `download_pdf()`

Re-renders a PDF from paper text stored in the client (used when re-downloading from history). Accepts `paper_text` and `answer_key` in the JSON body. Returns the binary PDF as an attachment via `send_file(BytesIO(...), as_attachment=True)`.

### `GET /health` → `health()`

Returns:
```json
{
  "status": "ok",
  "gemini": "configured",
  "gemini_backup_key": "set",
  "key_switching": "on-rate-limit (≥2 models return 429)",
  "models_available": [...]
}
```

### `GET /chapters` → `chapters()`

Returns curriculum JSON filtered by `?class=10`. The frontend calls this once on load and caches the result — no further server calls for subject/chapter changes.

---

## 13. Frontend Architecture

**Location:** `static/js/app.js` (~1380 lines)

The frontend is entirely vanilla JavaScript — no framework, no build step.

### Global state

```javascript
var curriculumData   = {};    // Cached curriculum JSON from /chapters
var currentPaper     = '';    // Last generated paper text
var currentAnswerKey = '';    // Last generated answer key
var currentMeta      = {};    // Board/subject/chapter/marks for re-download
var compScope  = 'topic';     // 'topic' | 'subject' | 'all'
var boardScope = 'single';    // 'single' | 'all'
```

`var` is used (not `let`/`const`) to be accessible from inline `onclick` handlers in the HTML — a deliberate trade-off for simplicity.

### Form visibility

`updateFormVisibility()` is called every time a major selection changes. It shows/hides cards by toggling the `collapsed` CSS class. All HTML is present simultaneously — no dynamic injection. The form is progressive: completing step I unlocks step II, etc.

### Loading stage timing

Five stages are defined with delays spread across the realistic 60–90 second generation window:
```javascript
const delays = [0, 6000, 22000, 50000, 78000];
```
Stage 1 fires instantly, stage 2 at 6s (questions being written), stage 3 at 22s, stage 4 at 50s, stage 5 at 78s. This keeps the UI feeling alive and informative throughout the full wait.

### PDF download mechanism

```javascript
function _b64Download(b64, fname) {
    const buf = new Uint8Array(atob(b64).split('').map(c => c.charCodeAt(0)));
    const url = URL.createObjectURL(new Blob([buf], {type:'application/pdf'}));
    Object.assign(document.createElement('a'), {href:url, download:fname}).click();
    setTimeout(() => URL.revokeObjectURL(url), 12000);
}
```

Standard browser-side technique: decode base64 → typed array → Blob → temporary object URL → programmatic anchor click → revoke URL after 12s to free memory.

### Theme system

6 themes defined as objects with 8 colour properties each. `applyAppTheme(idx, dark)` sets CSS custom properties on `:root`. All colours in CSS reference `var(--ac)`, `var(--ac2)` etc. — changing 5 variables instantly re-themes the entire UI without touching a single CSS rule. Theme preference is persisted to localStorage.

### History system

Metadata (board, subject, marks, difficulty, timestamp) stored in one localStorage key. Paper text and answer key stored separately per-item using ID-keyed keys (`ec_p_<id>`, `ec_k_<id>`). This split ensures metadata always survives even if large paper text hits quota. Last 10 papers kept; older ones pruned automatically.

### Trivia game

25 questions shuffled on game start. Answer options are also shuffled per question so the correct answer is never in a predictable position. Score and streak tracked. `_gameActive = false` is set when the modal closes — this flag prevents the `setTimeout(loadGameQuestion, 1800)` callbacks from firing after generation completes.

---

## 14. Data Files

### `curriculum.json`

```json
{
  "10": {
    "Mathematics": ["Real Numbers", "Polynomials", ...],
    "Science": ["Chemical Reactions", "Acids, Bases and Salts", ...],
    "Social Science": ["Development", ...]
  },
  "NTSE": { "MAT": ["Number Series", ...], "SAT Science": [...] }
}
```

Top-level keys are class numbers as strings (`"6"` through `"10"`) plus exam names. This dual-purpose structure allows the same `updateSubjects()` JavaScript function to handle both state board and competitive exams.

### `exam_patterns/ap_ts.json`

Official question pattern for AP/TS — section names, question counts, marks per question, total marks per section. Used by `_compute_structure()` to build the exact mark allocation for each prompt.

### `exam_patterns/competitive.json`

Per-exam structures for NTSE, NSO, IMO, IJSO — section names, question counts, marking schemes, and negative marking rules.

---

## 15. Deployment (Vercel)

### `vercel.json`

```json
{
  "version": 2,
  "builds": [{"src": "api/index.py", "use": "@vercel/python"}],
  "routes": [{"src": "/(.*)", "dest": "/api/index.py"}]
}
```

All HTTP requests go to `api/index.py`:
```python
from app import app
# Vercel imports `app` as a WSGI handler
```

Vercel's Python runtime runs the Flask app as a serverless function. Each request gets its own function instance. The function has a 300-second timeout — sufficient for the longest Gemini generation even with key-switching.

Static files (`/static/...`) are served by Vercel's CDN — they never hit the Python function.

**Important:** Vercel serverless functions are stateless. No in-memory cache, no file system persistence between requests. `curriculum.json` is read fresh each request if the `/chapters` route is hit. Client-side `curriculumData` caching means this only happens once per browser session.

---

## 16. Full Request Lifecycle

```
Browser
  │
  ├─ 1. onclick="generatePaper()"
  │       Validates form fields
  │       Shows loading modal, starts trivia game
  │       Stage 1 fires immediately (0s)
  │
  ├─ 2. POST /generate  { class, subject, chapter, board, marks, difficulty, ... }
  │
Server (app.py:generate)
  │
  ├─ 3.  Parse + sanitise JSON body
  ├─ 4.  Resolve board name
  ├─ 5.  _compute_structure(marks)  → exact question counts
  ├─ 6.  _difficulty_profile(diff)  → question type ratios
  ├─ 7.  _notation_rules(subject)   → subject notation string
  ├─ 8.  build_prompt(...)          → ~80-line prompt string
  │
  │      Stage 2 fires (6s) — "Writing the questions"
  │
  ├─ 9.  call_gemini(prompt)        → 60–90 seconds total
  │       ├─ Try GEMINI_KEY, top models via LangChain
  │       ├─ If 2+ models return 429 → switch to GEMINI_KEY_2 immediately
  │       ├─ If GEMINI_KEY_2 also fails → build_local_paper() fallback
  │       └─ Returns (paper+key text, error_or_None)
  │
  │      Stage 3 fires (22s) — "Writing the answer key"
  │      Stage 4 fires (50s) — "Laying out the paper"
  │
  ├─ 10. split_key(result)          → (paper_text, key_text)
  ├─ 11. Extract [DIAGRAM:...] tags
  ├─ 12. ThreadPoolExecutor: generate_diagram_svg(desc) × N  (parallel, 25s timeout)
  ├─ 13. register_fonts()            (no-op if already registered)
  ├─ 14. create_exam_pdf(paper, ...) → bytes
  │        ├─ Parse header (marks, board)
  │        ├─ Build 3-row navy header table
  │        ├─ Line-by-line parser: sections, questions, MCQ tables, pipe tables
  │        ├─ Embed diagrams at 88% page width with border frames
  │        └─ Append answer key section (if requested)
  │
  │      Stage 5 fires (78s) — "Creating the PDF"
  │
  ├─ 15. base64.b64encode(pdf_bytes)
  ├─ 16. Build second PDF with answer key appended
  ├─ 17. Return JSON {success, pdf_b64, pdf_key_b64, paper, answer_key}
  │
Browser
  │
  ├─ 18. Hide loading modal, stop trivia game, clear stage timers
  ├─ 19. _b64Download(pdf_b64, filename.pdf)  → immediate browser download
  ├─ 20. addToHistory(meta, paper, key)        → localStorage
  ├─ 21. showPaperReadyPopup()                 → "Your exam is ready" popup
  └─ 22. launchConfetti()                      → celebration canvas animation
```

Total elapsed time: approximately 60–90 seconds, of which 95%+ is Gemini API latency.

---

## Contact

Bugs, questions, code review requests:

**Laxman Nimmagadda** — laxmanchowday159@gmail.com

*ExamCraft 2026*