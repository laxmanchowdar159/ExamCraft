# ExamCraft

**AI-powered exam paper generator for Indian school boards and competitive exams.**

Generate a complete, print-ready question paper — with mark allocations, sections, diagrams, and a full answer key — in under 90 seconds. Built for teachers who spend hours setting papers and students who need practice on demand.

> Built by **Laxman Nimmagadda** · laxmanchowdary159@gmail.com

---

## What It Does

You pick a board, class, subject, chapter, total marks, and difficulty. ExamCraft sends that to Google Gemini, which writes a board-accurate question paper following the official section structure and Bloom's taxonomy ratios. The result comes back as two downloadable PDFs: a clean question paper and the same paper with a complete answer key.

The entire interaction — from clicking Generate to the file appearing in your Downloads folder — takes 60–90 seconds.

---

## Supported Boards and Exams

| Type | Options |
|---|---|
| **State Boards** | Andhra Pradesh SSC, Telangana SSC |
| **Competitive** | NTSE (MAT + SAT), NSO, IMO, IJSO |
| **Classes** | VI through X |
| **Subjects** | Mathematics, Science, Physics, Chemistry, Biology, Social Studies, English, Telugu, Hindi |

---

## Features

### Board-Accurate Paper Structure

AP and Telangana State Board papers follow the official SSC blueprint exactly:

```
Section A  — Objective (20% of marks)
  Part I   · Multiple Choice Questions     [1 mark each]
  Part II  · Fill in the Blank             [1 mark each]
  Part III · Match the Following           [1 mark each]

Section B  — Very Short Answer  (all compulsory)    [2 marks each]
Section C  — Short Answer       (attempt any N/M)   [4 marks each]
Section D  — Long Answer + OR   (attempt any N/M)   [5–6 marks each]
```

Question counts are computed precisely so that totals always add up to exactly the requested marks — no rounding errors, no mark shortfalls.

### Difficulty Levels

| Level | Character |
|---|---|
| **Easy** | 25% recall · 45% single-step · 20% multi-step · 10% analysis |
| **Medium** | 10% recall · 30% application · 35% multi-step · 15% evaluation · 10% synthesis |
| **Hard** | 0% recall · 15% application · 40% deep analysis · 30% proof/evaluation · 15% novel scenarios |

Hard papers are set at distinction level. 80% of students should find them genuinely challenging.

### MCQ Quality

Wrong options are not random. They are engineered to target the specific misconceptions students actually hold for each topic. Every distractor should look plausible to a student who half-understands the concept.

### Math and Science Notation

All mathematical expressions are rendered in publication-quality notation:

- Fractions displayed as proper stacked numerator/denominator
- Square roots, powers, subscripts, superscripts
- Greek letters: θ, α, β, π, λ, σ, Ω and all standard symbols
- Trigonometric functions, set notation, chemical formulas, vectors
- Expressions are typeset inside the PDF — they do not appear as raw LaTeX

### AI-Generated Diagrams

For questions that require a visual — geometry proofs, coordinate problems, circuit diagrams, ray diagrams, biology labelling, chemistry apparatus — ExamCraft automatically generates accurate SVG diagrams and embeds them directly into the PDF.

Diagrams are only added where they genuinely help. Pure algebraic questions, probability problems, and numerical calculations do not receive unnecessary diagrams. Where generation fails or a question calls for a student to draw their own, a clearly labelled placeholder box is included instead.

### Paper History

The last 10 papers you generate are saved in your browser. Each one can be re-downloaded (question paper or paper with key) with a single click, without regenerating. History is stored entirely on your device — nothing is uploaded to the server.

---

## Competitive Exam Formats

| Exam | Structure |
|---|---|
| **NTSE MAT** | 100 questions · Verbal Analogy, Number Series, Coding-Decoding, Blood Relations, Direction Sense, Venn Diagrams, Pattern Completion |
| **NTSE SAT** | 100 questions · Science (Physics + Chemistry + Biology) + Social Science + Mathematics |
| **NSO** | 60 marks · Logical Reasoning (10Q) + Science (35Q) + Achiever's Section (5Q × 3M) |
| **IMO** | 60 marks · Logical Reasoning (10Q) + Mathematical Reasoning (25Q) + Everyday Maths (10Q) + Achiever's Section (5Q × 3M) |
| **IJSO** | 80 questions with +3/−1 marking · Physics (27Q) + Chemistry (27Q) + Biology (26Q) |

---

## PDF Output

- **A4 format** with 17 mm margins — matches official exam paper dimensions
- Navy and gold colour scheme, print-clean and professional
- Section banners with accent bars for clear visual structure
- Mark allocation displayed in the right margin of every question
- Page numbers in the footer
- Answer key on a separate page in the second PDF, clearly delineated from the question paper

---

## How to Use

**Step 1 — Choose paper type.** Select State Board or Competitive Exam.

**Step 2 — Select your board or exam.** AP State Board, Telangana State Board, NTSE, NSO, IMO, or IJSO.

**Step 3 — Select class and subject.** Available subjects are populated automatically for the chosen class.

**Step 4 — Select scope.** Specific chapter or Full Syllabus.

**Step 5 — Configure the paper.** Set total marks (10–100), difficulty level, and any special instructions for the AI (e.g. "include more application questions", "focus on Chapter 3 theorems").

**Step 6 — Generate.** Click the button. Both PDFs download automatically when ready.

---

## Self-Hosting

```bash
git clone <repo>
cd ExamCraft
pip install -r requirements.txt

export GEMINI_API_KEY=your_key_here
python app.py
# Open http://localhost:3000
```

For production, deploy to Vercel with `git push`. Set environment variables in the Vercel dashboard.

---

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | **Yes** | Primary Google Gemini API key |
| `GEMINI_API_KEY_2` | Recommended | Second key — used when key 1 hits quota |
| `GEMINI_API_KEY_3` | Optional | Third key — used when keys 1 and 2 hit quota |
| `SMTP_EMAIL` | Optional | Gmail address for error alert emails |
| `SMTP_PASSWORD` | Optional | Gmail App Password (16-character, not account password) |
| `ALERT_EMAIL` | Optional | Address to receive error alert emails |

With three API keys configured, ExamCraft cycles through all available quota before giving up. Because keys are tried per model (not per key), the best available model is always used first.

---

## Privacy

ExamCraft does not know who you are. There is no account system, no login, no cookies beyond what the browser sets automatically.

**No tracking or analytics.** No page-view counters, no session recording, no third-party scripts that phone home.

**No data collection.** The form data you submit travels to the server, is used to generate your paper, and is immediately discarded. Nothing is stored on the server between requests.

**No device access.** Every response includes a `Permissions-Policy` header that explicitly denies camera, microphone, geolocation, gyroscope, accelerometer, USB, Bluetooth, NFC, payment, and 15 other device APIs at the browser level. These are not merely unused — they are actively blocked.

**History stays on your device.** The paper history panel reads and writes to your browser's `localStorage`. The data never leaves your machine. Clearing your browser data removes it permanently.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python · Flask 3 |
| AI | Google Gemini 2.5 Flash (with Gemma fallback) |
| AI SDK | LangChain + direct REST fallback |
| PDF generation | ReportLab Platypus |
| Frontend | Vanilla HTML · CSS · JavaScript (no framework) |
| Animations | GSAP 3 |
| Fonts | DejaVu Sans (full Unicode coverage for math symbols) |
| Deployment | Vercel Serverless |

---

## Support

For bugs, paper quality issues, or feature requests, email:

**Laxman Nimmagadda** · laxmanchowdary159@gmail.com

When reporting a paper quality issue, please include: board, class, subject, chapter, total marks, difficulty level, and the error or generated output that was incorrect.

---

*ExamCraft 2026*