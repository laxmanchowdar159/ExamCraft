# ExamCraft — Technical Deep Dive

> A step-by-step walkthrough of every layer of the backend: how it is written, what each piece does, and why each decision was made.

**Author: Laxman Nimmagadda**
Contact: laxmanchowday159@gmail.com

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Technology Stack](#2-technology-stack)
3. [Application Boot Sequence](#3-application-boot-sequence)
4. [Security Layer (app.py:50–140)](#4-security-layer)
5. [Error Reporting System (app.py:162–340)](#5-error-reporting-system)
6. [Font and Style System (app.py:364–555)](#6-font-and-style-system)
7. [LaTeX / Math Parser (app.py:476–625)](#7-latex--math-parser)
8. [PDF Rendering Engine (app.py:626–1415)](#8-pdf-rendering-engine)
9. [AI Integration — LangChain + Gemini (app.py:1416–1540)](#9-ai-integration)
10. [Prompt Engineering System (app.py:1645–2222)](#10-prompt-engineering-system)
11. [Diagram Generation (app.py:2287–2860)](#11-diagram-generation)
12. [Flask Routes (app.py:2860–3119)](#12-flask-routes)
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
│   └── index.html          ← Single-page UI (no template language, just HTML)
├── static/
│   ├── css/style.css       ← All styles (~520 lines, no framework)
│   ├── js/app.js           ← All frontend logic (~800 lines, vanilla JS)
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
| AI model | Google Gemini 2.5 Flash | Fast (1–3s/token), long context (1M tokens), free tier available |
| AI orchestration | LangChain | Retry logic, prompt templating, output parsing |
| PDF rendering | ReportLab Platypus | Industry standard, full layout control, no browser dependency |
| Deployment | Vercel Serverless | Free tier, automatic HTTPS, global CDN |
| Frontend | Vanilla JS + CSS | No build step, no framework overhead, instant load |
| Animations | GSAP 3 + Lenis | Butter-smooth scroll + spring animations, tiny JS bundle |
| Charts | Chart.js 4 | Lightweight, beautiful doughnut for mark distribution |

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
The Flask constructor is told where templates and static files live. `static_url_path="/static"` means the CSS/JS are served at `/static/css/...`.

**Step 3 — Security headers registered**
`@app.after_request` registers a function that runs after every route handler. This is a Flask "hook" — it intercepts the response object before it leaves the server and adds all the security headers described in the README. This approach means security is applied globally — no route can accidentally skip it.

**Step 4 — Email system configured**
SMTP credentials are read from environment variables. The email system is configured (not connected) at boot time.

**Step 5 — Font registration**
`register_fonts()` is called lazily (on first PDF generation), not at boot, to keep startup fast. DejaVu fonts that support Unicode math symbols (θ, √, π, etc.) are registered with ReportLab's font registry.

**Step 6 — Routes registered**
Python decorators `@app.route(...)` bind URL paths to handler functions.

**Step 7 — Server starts**
```python
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=False)
```
On Vercel, this block never executes — Vercel imports the `app` object directly via `api/index.py`.

---

## 4. Security Layer

**Location:** `app.py` lines 50–140 — `apply_security_headers(response)`

This is a Flask `@after_request` hook. Every HTTP response — HTML pages, JSON API responses, PDF downloads, health checks — passes through this function before leaving the server.

**How it works:**
```python
@app.after_request
def apply_security_headers(response):
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), ..."
    response.headers["Content-Security-Policy"] = "default-src 'self'; ..."
    # ... more headers
    response.headers.pop("Server", None)   # removes Flask/Werkzeug fingerprint
    return response
```

**Permissions-Policy** is the most important header for device safety. Each entry follows the syntax `api-name=()` where `()` means "no origin is allowed to use this API, not even self." The browser enforces this at the hardware level — even if JavaScript somehow tried to call `navigator.getUserMedia()`, the browser would block it before any prompt appeared.

**Content-Security-Policy** uses a "whitelist" model. The default is `default-src 'self'` which blocks everything not explicitly permitted. Then specific sources are whitelisted:
- `script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net` — allows GSAP, Chart.js, Lenis from their CDNs
- `connect-src 'self'` — all XHR/fetch calls must go to the same server. This prevents data exfiltration even if an attacker injected script.
- `frame-ancestors 'none'` — equivalent to X-Frame-Options but more precise

**Why `unsafe-inline` in scripts?** The app uses `onclick=` attributes in HTML for simplicity. In a higher-security environment, all inline handlers would be moved to JS event listeners and `unsafe-inline` removed. This is a documented trade-off.

---

## 5. Error Reporting System

**Location:** `app.py` lines 162–340

When any route handler crashes with an unhandled exception, the error is:
1. Caught by the `try/except` in the route handler
2. Formatted into a structured email with traceback, user choices, timestamp, and server info
3. Sent to `laxmanchowday159@gmail.com` via SMTP (Gmail App Password, configured via env vars)
4. A JSON error response is returned to the browser (never the raw traceback)

```python
def send_error_email(error_type, error_msg, traceback_str, user_choices, extra_context):
    # Builds a multipart MIME email with the full error context
    # SMTP connection is opened per-email (no persistent connection)
    # Uses smtplib.SMTP with STARTTLS (port 587) — never plain text
    ...
```

`_capture_user_choices(data)` is called at the start of each route to snapshot what the user submitted — board, subject, marks, etc. This is included in the error email so the developer can reproduce the exact paper that caused the crash.

The function is deliberately non-raising (`try/except Exception: pass` wraps the whole SMTP block) — an email failure must never make the web response fail. If the SMTP server is down, the user still gets their error response.

---

## 6. Font and Style System

**Location:** `app.py` lines 364–555

ReportLab has its own font system separate from CSS or the OS. PDF fonts must be embedded in the file to render correctly on any printer.

```python
def register_fonts():
    # Registers DejaVuSans family: Regular, Bold, Oblique
    # DejaVu is chosen because it has excellent Unicode coverage:
    # it includes Greek letters (θ, φ, π), mathematical operators (√, ∑, ∫),
    # and common symbols — all needed for school math/science papers
    pdfmetrics.registerFont(TTFont('DejaVuSans', FONTS_DIR / 'DejaVuSans.ttf'))
    ...
```

`_styles()` returns a dictionary of named `ParagraphStyle` objects. Think of these as named CSS classes but for ReportLab. Each style has font name, size, leading (line height), space-before, space-after, alignment, and colour. All styles are created once per PDF generation and passed through to every rendering function — there is no global mutable style state.

Key styles:
- `PTitle` — Paper title, Helvetica Bold 16pt, centered
- `PMeta` — Board/class/marks subtitle, 10pt, centered
- `QText` — Question body text, 11pt, left-aligned, 6pt space after
- `OptText` — MCQ option text, indented, 10pt
- `SecHead` — Section banner text, white on navy, 10pt bold
- `KeyAns` — Answer key answer, gold colour, 10pt bold

---

## 7. LaTeX / Math Parser

**Location:** `app.py` lines 476–625

The AI generates math in a mix of formats: `sqrt(x)`, `\sqrt{x}`, `x^2`, `x_1`, plain fractions like `(a/b)`. ReportLab's `Paragraph` class supports a subset of XML-like tags (`<b>`, `<i>`, `<super>`, `<sub>`). The parser bridges these two worlds.

**Step 1 — `_extract_braced(s, pos)`**
A recursive brace extractor. Given a string and position of `{`, it returns everything until the matching `}`, handling nested braces correctly. This is needed to parse `\frac{a+b}{c}` where `a+b` is the numerator.

**Step 2 — `_latex_to_rl(expr)`**
Converts LaTeX fragments to ReportLab XML markup:
```
\sqrt{x+1}       → √(x+1)
x^{2}            → x<super>2</super>
x_{n}            → x<sub>n</sub>
\frac{a}{b}      → (a/b)
\theta           → θ   (via Unicode mapping)
\alpha, \beta... → α, β...
```
The Unicode Greek letter mapping is a hard-coded dictionary of ~30 entries. The Greek alphabet and common math operators cover ~95% of Class 6–10 curriculum.

**Step 3 — `_process(text)`**
The main text pipeline that cleans up the AI's raw text before rendering:
- Strips markdown artifacts: `**bold**`, `*italic*`, `` `code` ``
- Removes HTML tags (the AI sometimes outputs `<br>`)
- Converts `\n` literal strings to actual newlines
- Calls `_latex_to_rl` on detected math spans
- Cleans up whitespace

---

## 8. PDF Rendering Engine

**Location:** `app.py` lines 626–1415 — `create_exam_pdf(text, subject, chapter, board, ...)`

This is the largest and most complex function. It takes the raw AI text (a multi-hundred-line string) and produces a binary PDF. Here is exactly what happens:

### 8.1 — Parse the Header

```python
h_marks = marks or _pull(r'Total\s*Marks\s*[:/]\s*(\d+)', "100")
h_time  = _pull(r'Time\s*(?:Allowed|:)\s*([^\n]+)', "3 Hours")
h_board = board or _pull(r'Board\s*[:/]\s*([^\n]+)', "")
```

`_pull(pattern, default)` is a tiny regex helper that extracts the first match group or returns the default. The marks are preferentially taken from the Python parameter (more reliable than parsing AI text), but the AI's header is used as a fallback.

### 8.2 — Build the Header Block

ReportLab's layout model is called **Platypus** ("Please Add Tags, Use Paragraphs, Let Us Sequence"). You build a list of `Flowable` objects (paragraphs, spacers, tables, rules) and call `doc.build(story)`. ReportLab handles pagination, line breaking, and overflow.

The header is a full-width navy (`#0f2149`) table:
```python
Table(
    [[logo_para, title_para, marks_para]],
    colWidths=[PW*0.15, PW*0.70, PW*0.15]
)
```
Three columns: logo glyph on the left, title in the center, marks on the right.

### 8.3 — ExamCanvas (Custom Page Template)

```python
class ExamCanvas:
    def __call__(self, canvas, doc):
        # Draws: page number, "ExamCraft" watermark, footer rule
        # Called by ReportLab on every page, including overflow pages
```

This is a ReportLab "canvas callback" — it runs after each page's content is placed, letting you draw elements that appear on every page (headers, footers, watermarks) without including them in the main story list.

### 8.4 — Text Parser / Section Recogniser

The core of `create_exam_pdf` is a line-by-line parser. The AI text is split into lines, then each line is classified:

```python
def _is_sec_hdr(s):  → True if line looks like "Section I", "PART A", "Section IV"
def _is_table_row(s):→ True if line contains " | " pipe characters
def _is_divider(s):  → True if line is "---" or "==="
def _is_hrule(s):    → True if line is decorative rule
```

When a section header is detected, `_sec_banner()` is called which creates a full-width coloured banner paragraph.

When a question line is detected (starts with a number like `1.` or `Q1.`), the question text is extracted, then the following option lines (`(a)`, `(b)`, `(c)`, `(d)`) are collected and passed to `_opts_table()`.

### 8.5 — `_opts_table(opts, st, pw)`

MCQ options are laid out in a 2×2 table (2 columns, 2 rows) to save vertical space:
```
(a) option A    (c) option C
(b) option B    (d) option D
```
Each cell is a `Paragraph`. The table has no visible borders. Column widths are 50% each. This is the most visually faithful layout to real AP/TS exam papers.

### 8.6 — `_pipe_table(rows, st, pw)`

For match-the-following questions, the AI outputs pipe-delimited rows:
```
Group A | Group B
16. Area of sector | (A) formula
```
`_pipe_table` splits on `|`, creates a styled ReportLab `Table` with alternating row backgrounds and a header row in a darker shade.

### 8.7 — Answer Key Section

If `include_key=True`, the answer key text (a separate string from the paper text) is parsed after a `PageBreak`. It gets its own gold-coloured banner header. Answer key parsing is simpler — it mainly renders numbered answers in `KeyAns` style (gold, bold).

---

## 9. AI Integration

**Location:** `app.py` lines 1416–1540

### `_get_lc_chain(model_name)` — Build a LangChain chain

```python
llm = ChatGoogleGenerativeAI(
    model=model_name,
    temperature=0.7,       # Some creativity for question variety
    max_output_tokens=8192,# Long enough for full paper + answer key
    google_api_key=GEMINI_KEY
)
chain = ChatPromptTemplate.from_messages([
    ("system", "{system}"),
    ("human", "{prompt}")
]) | llm | StrOutputParser()
```

A LangChain "chain" is a pipeline using the `|` operator (borrowed from Unix pipes). The prompt template is filled → passed to the LLM → the output is parsed to a plain string.

### `discover_models()` — Dynamic model list

Calls the Gemini models API to discover what models are available on this API key. This is used at startup to prefer the latest available Flash model.

### `call_gemini(prompt)` — The main generation function

```python
def call_gemini(prompt: str) -> str:
    models_to_try = ['gemini-2.5-flash', 'gemini-1.5-flash', 'gemini-1.5-pro']
    for model in models_to_try:
        try:
            chain = _get_lc_chain(model)
            result = chain.invoke({"system": SYSTEM_PROMPT, "prompt": prompt})
            if len(result.strip()) > 200:   # Basic quality gate
                return result
        except Exception:
            continue    # Try next model
    return build_local_paper(...)  # Ultimate fallback
```

The waterfall of models is the reliability guarantee. If Gemini 2.5 Flash is unavailable (quota, outage), 1.5 Flash is tried next, then Pro. `build_local_paper` is a template-based fallback that produces a minimal paper without AI if all API calls fail — ensuring the app never returns an empty result.

The 200-character quality gate rejects responses where the AI returned only a short error message or preamble. If the response is too short, it retries with the next model.

---

## 10. Prompt Engineering System

**Location:** `app.py` lines 1645–2222

This is the intelligence behind ExamCraft's paper quality. Prompts are not static strings — they are programmatically assembled from multiple components.

### `_compute_structure(marks)` — Mark allocation

```python
def _compute_structure(marks: int) -> dict:
    # Returns exact question counts per section based on total marks
    # For 100 marks:
    # Part A (20M): 10 MCQ (1M each) + 5 Fill (1M each) + Match (5M)
    # Section IV (16M): 8 × 2M Very Short
    # Section V (16M): 4 × 4M Short (choose 4 of 5)
    # Section VI (24M): 4 × 6M Long (choose 4 of 5, internal choice)
    # Section VII (20M): 2 × 10M Application (choose 2 of 3)
```

This mirrors the official AP/TS State Board blueprint exactly. The AI is told the exact counts, not asked to figure them out.

### `_difficulty_profile(difficulty)` — Mark distribution rules

```python
'Easy':   "60% recall/knowledge, 30% understanding, 10% application"
'Medium': "30% recall, 40% understanding, 20% application, 10% HOTS"
'Hard':   "15% recall, 30% understanding, 35% application, 20% HOTS"
```

These percentages are injected into the prompt so the AI calibrates question difficulty appropriately.

### `_notation_rules(subject)` — Subject-specific notation

```python
# Mathematics: "Use proper notation: √ for square root, θ for angles,
#               ∴ for therefore, ⟹ for implies"
# Chemistry:   "Use proper formulae: H₂O, CO₂, subscripts for atoms"
# Physics:     "Use SI units throughout. F for force (Newtons), ..."
```

Without these rules, the AI tends to use inconsistent notation — sometimes `sqrt(x)`, sometimes `root(x)`, sometimes the Unicode character. These rules pin it to the standard.

### `_prompt_board(subject, chap, board, cls, m, diff, notation, teacher)` — State board prompt

The full prompt for state board papers is ~80 lines and includes:
- Exact structure (section names, question counts, marks per section)
- Official AP/TS general instructions (verbatim — "Answer all questions under Part A...")
- Difficulty profile
- Subject notation rules
- Instruction to start with the header immediately (no AI preamble like "Sure! Here is...")
- Instruction to end with a full answer key separated by "=== ANSWER KEY ==="
- The chapter/topic to focus on

The instruction about avoiding AI preamble is critical. Without it, Gemini frequently starts with "Certainly! Here is the exam paper you requested for..." which breaks the parser.

### `_prompt_competitive(exam, subject, chap, cls, m, diff, notation, teacher)` — Competitive exam prompt

Competitive prompts are exam-specific:
- NTSE gets Stage 1 and Stage 2 marking scheme instructions (`+1/0` vs `+1/−⅓`)
- NSO gets Achiever's Section instructions (5 questions × 3 marks, higher-order thinking)
- IJSO gets `+3/−1` marking and integrated science instructions

### `split_key(text)` — Separate paper from answer key

The AI is instructed to separate the paper from the key with `=== ANSWER KEY ===`. This function finds that separator and returns `(paper_text, key_text)`. If the separator is not found, it uses a heuristic: look for "Answer Key" or "Answers" heading near the end of the text.

---

## 11. Diagram Generation

**Location:** `app.py` lines 2287–2860

The AI marks diagram positions with `[DIAGRAM: description]` tags. For example: `[DIAGRAM: Triangle ABC with altitude from A to BC, with labels]`.

### Step 1 — Extract descriptions

```python
diag_descs = re.findall(r'\[DIAGRAM:\s*([^\]]+)\]', full_text)
```

### Step 2 — Parallel generation

```python
with ThreadPoolExecutor(max_workers=4) as executor:
    futures = {executor.submit(generate_diagram_svg, desc): desc for desc in unique_descs}
```

Each diagram is generated in its own thread. For a paper with 4 diagrams, all 4 generate in ~parallel instead of 4× serial. `max_workers=4` avoids saturating the API rate limit.

### Step 3 — `generate_diagram_svg(description)`

Calls Gemini with a specialised prompt asking it to return only a valid SVG string (no commentary, no markdown fences). The prompt gives the AI explicit SVG guidelines: use `viewBox="0 0 400 300"`, keep paths simple, use only basic shapes, no custom fonts.

### Step 4 — SVG parsing and rendering

`svg_to_rl_drawing(svg_str)` converts SVG to a ReportLab `Drawing` object:
- Parses SVG XML with `xml.etree.ElementTree`
- Converts SVG elements to ReportLab shapes:
  - `<rect>` → `Rect`
  - `<circle>` → `Circle`
  - `<line>` → `Line`
  - `<path>` → `PolyLine` (simplified — complex paths are approximated)
  - `<text>` → `String`
- Applies coordinate transforms (SVG Y-axis is inverted vs ReportLab)
- Scales to fit the column width

If SVG parsing fails (malformed AI output), `svg_to_png_bytes` falls back to rasterising the SVG with a headless approach, or the diagram is silently skipped.

---

## 12. Flask Routes

**Location:** `app.py` lines 2860–3119

### `GET /` → `index()`
Returns `render_template("index.html")`. No logic — just serves the page. The security headers are applied by the after_request hook.

### `POST /generate` → `generate()`

The main route. Here is the exact sequence:

1. `request.get_json(force=True)` — parse the JSON body (force=True bypasses Content-Type check)
2. Sanitise all string fields with `.strip()` — no raw user input is used unsanitised
3. Resolve board name: `"Andhra Pradesh"` → `"Andhra Pradesh State Board"`
4. Call `build_prompt(...)` to assemble the full prompt string
5. Call `call_gemini(prompt)` — this is where the ~25–50 seconds is spent
6. Call `split_key(result)` to separate paper text from answer key
7. Call `create_exam_pdf(paper_text, ...)` to render the PDF bytes
8. Base64-encode the PDF bytes: `base64.b64encode(pdf_bytes).decode()`
9. Return JSON: `{"success": true, "paper": "...", "answer_key": "...", "pdf_b64": "..."}`

The PDF is base64-encoded and returned in the JSON response so the frontend can trigger an immediate browser download without a second HTTP request. The client decodes it: `atob(b64)` → `Uint8Array` → `Blob` → object URL → programmatic `<a>` click.

The generate route also includes error handling that calls `send_error_email` on failure, then returns `{"success": false, "error": "..."}` — never a 500 with a traceback.

### `POST /download-pdf` → `download_pdf()`

A secondary route used when re-downloading from history (where the PDF bytes were not cached client-side). Takes `paper_text` and `answer_key` in the JSON body and re-renders the PDF. Returns the binary PDF as an attachment using `send_file(BytesIO(...), as_attachment=True)`.

### `GET /health` → `health()`

Returns `{"status": "ok", "gemini": "configured"/"not configured"}`. Used by Vercel health checks and the developer for quick sanity checking.

### `GET /chapters` → `chapters()`

Returns the curriculum tree from `curriculum.json`. Optionally filtered by `?class=10` to return only the subjects and chapters for that class. The frontend calls this on page load and caches the result in `curriculumData` (a plain JS object) — subsequent subject/chapter changes use the cache without hitting the server.

---

## 13. Frontend Architecture

**Location:** `static/js/app.js` (~900 lines)

The frontend is entirely vanilla JavaScript — no framework. Here is how the key systems work:

### State variables (global)

```javascript
var curriculumData   = {};    // Cached curriculum JSON
var currentPaper     = '';    // Last generated paper text
var currentAnswerKey = '';    // Last generated answer key
var currentMeta      = {};    // Board/subject/chapter/marks for re-download
var compScope  = 'topic';     // 'topic' | 'subject' | 'all'
var boardScope = 'single';    // 'single' | 'all'
```

These are `var` (not `let`/`const`) to be accessible from inline `onclick` handlers in the HTML. This is a deliberate trade-off for simplicity over strict encapsulation.

### Form visibility logic

`updateFormVisibility()` is called every time a major selection changes. It shows/hides cards by toggling the `collapsed` CSS class (which sets `display:none`). This keeps all the HTML in the page simultaneously — there is no server-side templating or dynamic HTML injection. The form is progressive: completing step I unlocks step II, etc.

### Curriculum fetch and cache

```javascript
async function initCurriculum() {
    const res  = await fetch('/chapters');
    const json = await res.json();
    curriculumData = json.data;   // { "10": { "Mathematics": ["Real Numbers", ...], ... } }
}
```

When the user changes class or competitive exam, `updateSubjects()` populates the subject `<select>` from the cache. When subject changes, `updateChapters()` populates the chapter `<select>`. All synchronous after the initial fetch.

### PDF download mechanism

```javascript
function _b64Download(b64, fname) {
    const bin = atob(b64);
    const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    const url = URL.createObjectURL(new Blob([buf], {type:'application/pdf'}));
    const a   = Object.assign(document.createElement('a'), {href:url, download:fname});
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 12000);
}
```

This is the standard browser-side approach to triggering a download from a base64 string. The `URL.createObjectURL` creates a temporary blob URL that the browser treats as a file. The URL is revoked after 12 seconds to free memory.

### Theme system

6 themes defined as objects with `accent`, `a2`, `a3`, `glow`, `dim` colour properties. `applyAppTheme(idx, dark)` sets CSS custom properties on `:root` using `document.documentElement.style.setProperty`. All colours in CSS reference `var(--ac)`, `var(--ac2)` etc. — changing these 5 variables instantly re-themes the entire UI without touching a single CSS rule.

### Trivia game

25 questions in a `TRIVIA_QS` array. On loading modal open, `initGame()` shuffles the question order. `loadGameQuestion()` renders the current question and shuffles the 4 option positions (so `(a)` is not always the correct answer). `answerQ(btnIdx)` evaluates the answer, updates score/streak, adds CSS classes for correct/wrong visual feedback, and calls `setTimeout(loadGameQuestion, 1800)` for the next question. The game variable `_gameActive = false` is set when the modal closes, preventing the `setTimeout` callbacks from firing after paper generation completes.

---

## 14. Data Files

### `curriculum.json`

Structure:
```json
{
  "10": {
    "Mathematics": ["Real Numbers", "Polynomials", "Pair of Linear Equations", ...],
    "Science": ["Chemical Reactions", "Acids, Bases and Salts", ...],
    "Social Science": ["Development", "Sectors of Indian Economy", ...]
  },
  "9": { ... },
  "NTSE": { "MAT": ["Number Series", ...], "SAT Science": [...], ... }
}
```

The top-level keys are class numbers as strings (`"6"` through `"10"`) plus exam names (`"NTSE"`, `"NSO"`, `"IMO"`, `"IJSO"`). This dual-purpose structure allows the same `updateSubjects()` JavaScript function to handle both state board and competitive exams.

### `exam_patterns/ap_ts.json`

Defines the official question pattern:
```json
{
  "100": {
    "MCQ": {"count": 10, "marks": 1},
    "FillBlank": {"count": 5, "marks": 1},
    "Match": {"count": 1, "marks": 5},
    ...
  }
}
```

### `exam_patterns/competitive.json`

Per-exam structures for NTSE, NSO, IMO, IJSO — each with correct section names and mark allocations.

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

All HTTP requests go to `api/index.py`, which is:
```python
from app import app
# Vercel imports `app` as a WSGI handler
```

Vercel's Python runtime runs the Flask app as a serverless function. Each request spins up a new function instance. The function has a 300-second timeout (sufficient for the longest Gemini generation).

Static files (`/static/...`) are served by Vercel's CDN — they never hit the Python function.

**Important:** Vercel serverless functions are stateless. There is no in-memory cache, no file system persistence between requests. Every request reads `curriculum.json` fresh if needed. The `curriculumData` caching is client-side only.

---

## 16. Full Request Lifecycle

Here is every step from "click Generate" to "PDF downloaded":

```
Browser
  │
  ├─ 1. onclick="generatePaper()"
  │       Collects form values, validates required fields
  │       Shows loading modal, starts trivia game
  │       Populates recap panel with current selections
  │
  ├─ 2. POST /generate  { class, subject, chapter, board, marks, difficulty, ... }
  │
Server (app.py:generate)
  │
  ├─ 3. Parse + sanitise JSON body
  ├─ 4. Resolve board name ("Andhra Pradesh" → "Andhra Pradesh State Board")
  ├─ 5. _compute_structure(marks)  → section blueprint
  ├─ 6. _difficulty_profile(diff)  → question type ratios
  ├─ 7. _notation_rules(subject)   → subject-specific notation string
  ├─ 8. _prompt_board(...)         → assemble 80-line prompt string
  ├─ 9. call_gemini(prompt)        → ~25–50 seconds (Gemini API)
  │       └─ Waterfall: 2.5-flash → 1.5-flash → 1.5-pro → local fallback
  ├─ 10. split_key(result)         → (paper_text, key_text)
  ├─ 11. Extract [DIAGRAM:...] tags
  ├─ 12. generate_diagram_svg(desc) × N  (parallel ThreadPoolExecutor)
  ├─ 13. register_fonts()           (no-op if already registered)
  ├─ 14. create_exam_pdf(paper, ...) → bytes
  │        ├─ Parse header (marks, time, board)
  │        ├─ Build navy header table
  │        ├─ Line-by-line parser: sections, questions, MCQ tables, pipe tables
  │        ├─ Embed diagrams as ReportLab Drawings
  │        └─ Append answer key section (if requested)
  ├─ 15. base64.b64encode(pdf_bytes)
  ├─ 16. Return JSON {"success":true, "pdf_b64":"...", "paper":"...", "answer_key":"..."}
  │
Browser
  │
  ├─ 17. Hides loading modal, stops trivia game
  ├─ 18. _b64Download(pdf_b64, filename.pdf)  → immediate browser download
  ├─ 19. addToHistory(meta, paper, key)        → saved to localStorage
  ├─ 20. showSuccessPanel()                    → success bar appears
  └─ 21. launchConfetti()                      → celebration animation
```

Total elapsed time: approximately 25–55 seconds, of which 95% is Gemini API latency.

---

## Contact

Bugs, questions, code review requests:

**Laxman Nimmagadda** — laxmanchowday159@gmail.com

*ExamCraft 2026*
