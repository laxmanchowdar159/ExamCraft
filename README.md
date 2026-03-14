# ExamCraft — AI Exam Paper Generator

> Generate complete, print-ready examination papers for AP/TS State Board and national competitive exams in under 90 seconds.

**Built by Laxman Nimmagadda** · laxmanchowdary159@gmail.com

---

## What is ExamCraft?

ExamCraft is a web application that turns a few form selections into a fully formatted, board-accurate examination paper — with questions, mark allocations, section banners, diagrams, and a complete answer key — all rendered to a professional PDF you can print directly.

Teachers set papers in minutes instead of hours. Students get practice papers on demand. Tutors generate targeted chapter tests for any difficulty level.

---

## Features at a Glance

| Feature | Detail |
|---|---|
| **Boards** | Andhra Pradesh SSC, Telangana SSC |
| **Competitive exams** | NTSE (MAT + SAT), NSO, IMO, IJSO |
| **Classes** | VI through X |
| **Subjects** | Mathematics, Science, Physics, Chemistry, Biology, Social Studies, English, Telugu, Hindi |
| **Difficulty levels** | Easy · Medium · Hard |
| **Marks range** | Any total from 10 to 100 |
| **Output** | Two PDFs — Question Paper + Question Paper with Answer Key |
| **Diagrams** | AI-generated SVG diagrams embedded in the PDF |
| **History** | Last 10 papers saved in browser, one-click re-download |

---

## How to Use

**Step 1 — Choose exam type**
Select State Board or Competitive Exam.

**Step 2 — Select your board or exam**
AP State Board, Telangana State Board, NTSE, NSO, IMO, or IJSO.

**Step 3 — Select class**
Class 6 through 10.

**Step 4 — Select subject**
All subjects available for the chosen class are listed automatically.

**Step 5 — Select chapter**
Pick a specific chapter or choose Full Syllabus.

**Step 6 — Configure paper**
Set total marks, difficulty, and any special instructions.

**Generate**
Click Generate Paper. Your PDF downloads automatically in 60–90 seconds.

---

## Paper Quality

### Official AP/TS Blueprint

AP and Telangana State Board papers follow the exact official SSC blueprint:

```
PART A — OBJECTIVE  (20% of marks)
  Section I   — Multiple Choice Questions        [1 mark each]
  Section II  — Fill in the Blank                [1 mark each]
  Section III — Match the Following              [1 mark each]

PART B — WRITTEN  (80% of marks)
  Section IV  — Very Short Answer  (ALL compulsory)     [2 marks each]
  Section V   — Short Answer       (attempt any N of M)  [4 marks each]
  Section VI  — Long Answer + OR   (attempt any N of M)  [6 marks each]
  Section VII — Application/Problem(attempt any N of M)  [10 marks each]
```

Question counts per section are computed precisely so totals always match the requested marks exactly.

### Difficulty Calibration

| Level | Character |
|---|---|
| **Easy** | 25% recall · 45% single-step · 20% multi-step · 10% analysis |
| **Medium** | 10% recall · 30% application · 35% multi-step · 15% evaluation · 10% synthesis |
| **Hard** | 0% recall · 15% application · 40% deep analysis · 30% proof/evaluation · 15% novel scenarios |

Hard papers are set at distinction level — 80%+ of students should find them challenging.

### MCQ Quality

Wrong options are engineered to target specific misconceptions students actually hold, not random distractors. Every MCQ has exactly four options: one correct and three plausible wrong answers.

### Math Notation

All expressions are rendered using LaTeX-style notation converted for print:
- Fractions: displayed as proper numerator/denominator
- Square roots, powers, subscripts, superscripts
- Greek letters: θ, α, β, π, λ, σ, Ω and all standard symbols
- Trig functions, set notation, vectors

### Diagrams

For geometry, coordinate geometry, physics circuits, ray diagrams, biology cell diagrams, and similar questions, ExamCraft automatically generates accurate SVG diagrams and embeds them directly into the PDF. Where diagrams could not be generated, a clearly labelled placeholder box is included for students to draw.

---

## PDF Appearance

- **A4 format** with 17mm margins matching official exam paper dimensions
- Navy and gold colour scheme — professional, print-clean
- Section banners with accent bars for clear paper structure
- Marks shown in the right column of every question
- Page numbers in the footer
- Separate Answer Key section on its own page (in the with-key PDF)

---

## Competitive Exam Formats

| Exam | Structure |
|---|---|
| **NTSE MAT** | 100 questions: Verbal Analogy, Number Series, Coding-Decoding, Blood Relations, Direction, Venn Diagrams, Pattern Completion |
| **NTSE SAT** | 100 questions: Science (Physics + Chemistry + Biology) + Social Science + Mathematics |
| **NSO** | 60 marks: Logical Reasoning (10Q) + Science (35Q) + Achiever's Section (5Q × 3M) |
| **IMO** | 60 marks: Logical Reasoning (10Q) + Mathematical Reasoning (25Q) + Everyday Maths (10Q) + Achiever's (5Q × 3M) |
| **IJSO** | 80 questions × +3/−1: Physics (27Q) + Chemistry (27Q) + Biology (26Q) |

---

## Privacy and Security

ExamCraft is built on a strict privacy-first foundation.

**No tracking, no ads, no data collection.** The app does not know who you are. It stores nothing on the server. No account, no login, no cookies beyond what the browser sets itself.

**No device access.** The server sends a `Permissions-Policy` header with every response that explicitly denies camera, microphone, geolocation, gyroscope, accelerometer, USB, Bluetooth, NFC, payment, and 15 other device APIs at the browser level. Not just unused — actively blocked.

**No third-party data.** All API calls go to the same server. Nothing from your request is forwarded to any analytics, advertising, or telemetry service.

**Paper history stays on your device.** The last 10 papers are saved in your own browser's localStorage. They are never uploaded anywhere. Clearing browser data removes them permanently.

---

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Primary Google Gemini API key |
| `GEMINI_API_KEY_2` | Recommended | Second key — used when key 1 hits quota |
| `GEMINI_API_KEY_3` | Optional | Third key — used when keys 1 and 2 hit quota |
| `SMTP_EMAIL` | Optional | Gmail address for error alert emails |
| `SMTP_PASSWORD` | Optional | Gmail App Password (16-char) |
| `ALERT_EMAIL` | Optional | Error email recipient |

With three API keys configured, ExamCraft cycles through all available quota before failing. Each model is tried on all three keys in order before moving to the next model.

---

## Self-Hosting

```bash
git clone <repo>
cd ExamCraft
pip install -r requirements.txt

export GEMINI_API_KEY=your_key_here
python app.py
# Visit http://localhost:3000
```

For production, deploy to Vercel (see `vercel.json`) or any WSGI host. Set the env variables in your hosting platform's dashboard.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python · Flask 3 |
| AI | Google Gemini (via LangChain + direct REST fallback) |
| PDF | ReportLab Platypus |
| Frontend | Vanilla HTML · CSS · JavaScript |
| Animations | GSAP 3 |
| Deployment | Vercel Serverless |

---

## Support

Bugs, paper quality issues, or feature requests:

**Laxman Nimmagadda** · laxmanchowdary159@gmail.com

Please include: board, class, subject, chapter, marks, difficulty, and the error message if any.

---

*ExamCraft 2026*