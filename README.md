# ExamCraft — AI-Powered Exam Paper Generator

> Curriculum-aligned exam papers for AP/TS State Board and national competitive exams, delivered as a polished PDF in 1–1.5 minutes.

**Built by Laxman Nimmagadda**
Issues or feedback: laxmanchowday159@gmail.com

---

## What ExamCraft Does

ExamCraft is a Flask web application that lets teachers, tutors, and students generate complete, print-ready examination papers using Google Gemini 2.5 Flash AI. Configure the board, class, subject, chapter, marks, and difficulty — the AI writes a full paper in the correct official format and you download a beautifully rendered PDF in one click.

---

## What ExamCraft Excels In

### Security — Zero Device Access, Zero Tracking

ExamCraft is built on a strict privacy-first foundation. The server sends security headers with every single response:

| Header | What it does |
|---|---|
| Permissions-Policy | Denies camera, microphone, geolocation, gyroscope, accelerometer, USB, Bluetooth, NFC, payment, serial, HID, and 10+ other device APIs |
| Content-Security-Policy | Scripts, styles, and fonts may only load from self or named trusted CDNs. No eval, no inline injection |
| X-Frame-Options: DENY | Page cannot be embedded in any iframe — prevents clickjacking |
| X-Content-Type-Options: nosniff | Prevents MIME-type confusion attacks |
| X-XSS-Protection | Activates XSS filters in legacy browsers |
| Referrer-Policy | Only the origin is sent with cross-origin requests |
| Strict-Transport-Security | Forces HTTPS for a full year in production |

The site never asks for your location. Never activates camera or microphone. Never embeds tracking pixels or ads. All API calls go to the same server — nothing is sent to third parties from the backend. The server fingerprint header is removed entirely.

Client-side storage is limited to theme preference and a short paper history (max 10 entries) in localStorage on your own browser. Nothing is uploaded or shared.

---

### AI Quality — Gemini 2.5 Flash with Automatic Fallback

- Uses Google Gemini 2.5 Flash — the same model family powering Google's educational tools
- Prompts are engineered per board and exam type — AP/TS papers follow the 5-section blueprint, competitive papers match NTSE/NSO/IMO/IJSO marking schemes exactly
- Explicit instructions about notation, difficulty calibration, mark distribution, and question types are baked into every prompt
- **Dual API key support with smart switching** — if the primary key hits a rate limit (two or more models return 429), the system immediately switches to the backup key (`GEMINI_API_KEY_2`) without waiting to exhaust all models. Falls back to a template paper only if both keys fail entirely
- The answer key is generated in the same pass for accuracy

---

### PDF Generation — Professional Print Quality

- Rendered with ReportLab (used for government and legal documents)
- Correct A4 layout with 17mm margins matching official exam paper dimensions
- Section banners with navy/accent colour scheme, rule lines, marks in the right-hand column
- Full pipe tables with bordered cells, navy header rows, and alternating row backgrounds — used for Match the Following and data tables
- LaTeX-style math expressions parsed and rendered inline (fractions, square roots, Greek letters, subscripts, superscripts)
- AI-generated SVG diagrams rendered at near full page width and embedded directly into the paper
- Diagram placeholder boxes styled with a labelled header and dotted drawing area for questions where no diagram was auto-generated
- File streamed directly to browser — no file stored on server

---

### User Experience

- Six-step guided workflow with live progress tracker in the sidebar
- Current Selection panel updates in real-time as you fill each field
- Paper history with one-click re-download, board badge, marks, and difficulty tags (last 10 papers)
- Paper Estimate panel shows predicted question count, exam time, and section breakdown
- Loading screen trivia game with 25 academic questions during the wait — score and streak tracked
- Five loading stages with accurate timing spread across the real 1–1.5 minute generation window
- Six colour themes — Gold, Copper, Silver, Crimson, Jade, Ink
- Full mobile support with slide-in sidebar
- Custom cursor with spring-follow ring animation on desktop

---

### Performance

- No React, no Vue — plain HTML + CSS + vanilla JS, no build step
- PDF generation runs server-side; browser only receives the final binary
- Parallel diagram generation using ThreadPoolExecutor (up to 3 diagrams at once)
- Full paper validated before PDF is built — no partial renders

---

### Curriculum Coverage

| Exam | Scope |
|---|---|
| AP State Board (SSC) | Classes VI–X, all subjects, per-chapter or full syllabus |
| Telangana State Board (SSC) | Classes VI–X, all subjects, per-chapter or full syllabus |
| NTSE | MAT (Mental Ability) + SAT (Science, Social Studies, Maths) |
| NSO | Logical Reasoning + Science + Achiever's Section |
| IMO | Logical Reasoning + Maths + Everyday Maths + Achiever's Section |
| IJSO | Integrated Physics + Chemistry + Biology |

---

## Environment Variables

| Variable | Required | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Primary Google Gemini API key |
| `GEMINI_API_KEY_2` | Optional | Backup key — used automatically when primary key is rate-limited |
| `SMTP_EMAIL` | Optional | Gmail address for error alert emails |
| `SMTP_PASSWORD` | Optional | Gmail App Password (16-char) for error alerts |
| `ALERT_EMAIL` | Optional | Recipient for error emails (defaults to laxmanchowday159@gmail.com) |

---

## Contact

Issues, bugs, or feature requests:
Laxman Nimmagadda — laxmanchowday159@gmail.com

Please include what you were generating (board, subject, chapter) and the error message if any.

ExamCraft 2026 — Flask · Gemini 2.5 Flash · ReportLab · GSAP · Chart.js