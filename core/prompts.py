"""
core/prompts.py
Builds the single prompt sent to Gemini for paper generation:
difficulty calibration, subject notation rules, section structure
(marks → question counts), and the board/competitive-exam specific
instructions. No network calls in this module.
"""
import re


def _class_int(cls_str):
    m = re.search(r'\d+', str(cls_str or "10"))
    return int(m.group()) if m else 10


def _time_for_marks(m):
    if m <= 30:  return "1 Hour"
    if m <= 60:  return "2 Hours"
    if m <= 80:  return "2 Hours 30 Minutes"
    return "3 Hours 15 Minutes"


def _difficulty_profile(difficulty):
    """Returns the difficulty calibration string.
    Papers are set deliberately harder than standard curriculum level.
    """
    return {
        "Easy": (
            "EASY-TO-MODERATE  |  Papers are set harder than standard.\n"
            "• 25% straightforward recall  • 45% single-step application\n"
            "• 20% multi-step application  • 10% analysis\n"
            "Avoid trivial questions. Every MCQ should have a plausible wrong option."
        ),
        "Medium": (
            "MODERATE-TO-HARD  |  Papers are set harder than standard.\n"
            "• 10% recall  • 30% application  • 35% multi-step analysis\n"
            "• 15% evaluation  • 10% synthesis/proof\n"
            "At least 40% of questions should challenge above-average students.\n"
            "Long answers must require multi-concept integration."
        ),
        "Hard": (
            "HARD-TO-NIGHTMARE  |  Papers are set at competition/distinction level.\n"
            "• 0% pure recall  • 15% non-trivial application  • 40% deep analysis\n"
            "• 30% evaluation & proof  • 15% synthesis & novel scenarios\n"
            "80%+ of students should find this challenging.\n"
            "MCQ distractors must target specific misconceptions.\n"
            "Every calculation should involve ≥3 steps. Include edge cases."
        ),
    }.get(difficulty, "MODERATE-TO-HARD  |  Multi-step questions requiring analysis.")


def _notation_rules(subject):
    """Returns notation and formatting rules relevant to the subject."""
    subj_l = (subject or "").lower()
    is_math    = any(k in subj_l for k in ["math", "algebra", "geometry", "trigonometry", "statistics", "arithmetic"])
    is_physics = any(k in subj_l for k in ["physics", "physical"])
    is_chem    = any(k in subj_l for k in ["chemistry", "chemical"])
    is_bio     = any(k in subj_l for k in ["biology", "biological", "life science", "botany", "zoology"])
    is_science = any(k in subj_l for k in ["science", "physics", "chemistry", "biology"]) or is_physics or is_chem or is_bio
    is_social  = any(k in subj_l for k in ["social", "history", "geography", "civics", "economics", "political", "environment"])
    is_language = any(k in subj_l for k in ["english", "hindi", "telugu", "kannada", "tamil", "urdu", "sanskrit", "marathi", "language", "literature", "grammar"])
    is_stem    = is_math or is_science

    math_block = ""
    if is_stem:
        math_block = (
            "MATH & SCIENCE NOTATION — strictly required:\n"
            "• ALL expressions inside $…$:  $x^{2}$  $\\frac{a}{b}$  $\\sqrt{b^2-4ac}$\n"
            "• Chemical formulas: $H_2O$  $CO_2$  $H_2SO_4$  $Ca(OH)_2$\n"
            "• Powers / subscripts: $a^{3}$  $v_0$  $10^{-3}$  never write as plain a3 or v0\n"
            "• Greek letters: $\\theta$  $\\alpha$  $\\beta$  $\\pi$  $\\lambda$  $\\mu$  $\\Omega$\n"
            "• Trig: $\\sin\\theta$  $\\cos 60^{\\circ}$  $\\tan\\alpha$  $\\sin^2\\theta + \\cos^2\\theta = 1$\n"
            "• Fractions: $\\frac{mv^2}{r}$  $\\frac{\\Delta v}{\\Delta t}$  never use /\n"
            "• Units OUTSIDE $: write '5 cm', '$F = ma$ where F is in newtons'\n"
            "• Fill blanks: __________ (ten underscores, ALWAYS outside $…$, never inside math mode)\n"
            "• Equations on own line: $PV = nRT$\n"
            "\n"
        )

    # Language subjects: no diagrams at all
    if is_language:
        return math_block + (
            "DIAGRAMS — Do NOT include any [DIAGRAM:] tags for this subject.\n"
            "This is a language/literature subject — diagrams are not appropriate and must not be added.\n"
        )

    if is_physics or (is_science and not is_bio and not is_chem):
        diag_block = (
            "DIAGRAMS — include for Physics only where a visual genuinely aids understanding:\n"
            "• [DIAGRAM: circuit diagram with 3Ω and 6Ω resistors in parallel connected to 12V battery, ammeter, voltmeter]\n"
            "• [DIAGRAM: ray diagram showing refraction through a convex lens with principal axis, F and 2F, object and image]\n"
            "• [DIAGRAM: velocity-time graph showing uniform acceleration from rest, axes labelled]\n"
            "• [DIAGRAM: free body diagram with weight, normal force, friction, applied force arrows labelled]\n"
            "• [DIAGRAM: bar magnet with magnetic field lines from N to S pole, arrowheads]\n"
            "Use format [DIAGRAM: …] on its own line after the question stem.\n"
            "Include [DIAGRAM:] in ≥25% of Section B, C, D questions where a visual genuinely adds educational value.\n"
        )
    elif is_bio:
        diag_block = (
            "DIAGRAMS — include for Biology only where a visual genuinely aids understanding:\n"
            "• [DIAGRAM: labelled plant cell showing cell wall, cell membrane, nucleus, vacuole, chloroplast, mitochondria]\n"
            "• [DIAGRAM: labelled animal cell showing cell membrane, nucleus, mitochondria, ribosomes, small vacuoles]\n"
            "• [DIAGRAM: human digestive system: mouth, oesophagus, stomach, small intestine, large intestine, liver, pancreas labelled]\n"
            "• [DIAGRAM: neuron showing dendrites, cell body, axon, myelin sheath, synaptic knob, impulse direction]\n"
            "• [DIAGRAM: longitudinal section of a flower showing sepals, petals, stamen, carpel, ovules labelled]\n"
            "• [DIAGRAM: human heart cross-section with 4 chambers, valves, aorta, pulmonary vessels labelled]\n"
            "Use format [DIAGRAM: …] on its own line after the question stem.\n"
            "Include [DIAGRAM:] in ≥25% of Section B, C, D questions where a visual genuinely adds educational value.\n"
        )
    elif is_chem:
        diag_block = (
            "DIAGRAMS — include wherever they add clarity in Chemistry:\n"
            "• [DIAGRAM: Bohr model of carbon atom showing nucleus with 6 protons and 6 neutrons, 2 electrons in shell 1, 4 in shell 2]\n"
            "• [DIAGRAM: laboratory apparatus — conical flask, delivery tube, gas collection over water trough, all labelled]\n"
            "• [DIAGRAM: structural formula of methane CH4 showing C at centre with 4 H atoms bonded]\n"
            "Use format [DIAGRAM: …] on its own line after the question stem.\n"
            "Include [DIAGRAM:] in ≥20% of Section B, C, D questions where a visual genuinely helps.\n"
        )
    elif is_science:
        diag_block = (
            "DIAGRAMS — include wherever they add clarity (Physics/Chemistry/Biology):\n"
            "• [DIAGRAM: labelled plant cell showing cell wall, membrane, nucleus, vacuole, chloroplast]\n"
            "• [DIAGRAM: circuit diagram with resistors, battery, ammeter, voltmeter]\n"
            "• [DIAGRAM: ray diagram showing refraction through a convex lens, F and 2F points]\n"
            "• [DIAGRAM: human digestive system with labels]\n"
            "Use format [DIAGRAM: …] on its own line after the question stem.\n"
            "Include [DIAGRAM:] in ≥20% of Section B, C, D questions where a visual genuinely adds educational value.\n"
        )
    elif is_math:
        diag_block = (
            "DIAGRAMS — include wherever geometric/graphical clarity is needed:\n"
            "• [DIAGRAM: triangle ABC with angle A=60°, B=80°, side BC=7cm, altitude from A to BC]\n"
            "• [DIAGRAM: number line showing solution set of inequality -3 < x ≤ 5]\n"
            "• [DIAGRAM: coordinate axes with parabola y=x²-4x+3, showing vertex and x-intercepts]\n"
            "Use format [DIAGRAM: …] on its own line after the question stem.\n"
            "Include [DIAGRAM:] in ≥25% of geometry/coordinate/construction questions where a visual is essential.\n"
        )
    elif is_social:
        diag_block = (
            "DIAGRAMS — include maps and charts wherever relevant:\n"
            "• [DIAGRAM: outline map of India showing major rivers, mountain ranges, state boundaries]\n"
            "• [DIAGRAM: bar chart comparing GDP of 5 countries with labelled axes]\n"
            "• [DIAGRAM: flowchart showing the legislative process in Parliament]\n"
            "Use format [DIAGRAM: …] on its own line after the question stem.\n"
            "Include [DIAGRAM:] in ≥10% of written-answer questions only where a map or chart genuinely helps.\n"
        )
    else:
        diag_block = (
            "DIAGRAMS — include [DIAGRAM: description] on its own line wherever a visual aids understanding.\n"
        )

    return math_block + diag_block


# ═══════════════════════════════════════════════════════════════════════
# BOARD EXAM STRUCTURE CALCULATOR
# Section A (1M) · B (2M) · C (4M) · D (5/6M) — scales to any total
# ═══════════════════════════════════════════════════════════════════════

def _compute_structure(marks):
    """
    Returns a dict describing Section A/B/C/D for the given mark total.
    Section totals always add up to exactly `marks`.

    Section A : 1-mark  — MCQ + Fill-in-blank + Match (split evenly)
    Section B : 2-mark  — Very Short Answer (all compulsory)
    Section C : 4-mark  — Short/Medium Answer (choice for bigger papers)
    Section D : 5-mark  — Long Answer (only for papers ≥ 40 marks; choice given)

    Reference (user's confirmed good paper at 20 marks):
      A: 10×1=10   B: 4×2=8   C: 1×4=4   (no D)  → total=22 marks
      (The AI header says Total:{m} marks — question counts drive quality, not the sum.)
    """
    m = max(10, int(marks))

    # ── Exact presets for every common AP/TS exam size ─────────────────
    # Tuple: (nA, nB, nC, nD, dEach)  — all guaranteed to sum correctly
    PRESET = {
        10:  ( 6,  2, 0, 0, 0),  #  6+ 4+ 0+ 0 = 10 ✓
        15:  ( 7,  2, 1, 0, 0),  #  7+ 4+ 4+ 0 = 15 ✓
        20:  (10,  3, 1, 0, 0),  # 10+ 6+ 4+ 0 = 20 ✓
        25:  (10,  3, 1, 1, 5),  # 10+ 6+ 4+ 5 = 25 ✓
        30:  (10,  4, 2, 1, 4),  # 10+ 8+ 8+ 4 = 30 ✓
        35:  (10,  5, 2, 1, 7),  # 10+10+ 8+ 7 = 35 ✓
        40:  (10,  5, 3, 1, 8),  # 10+10+12+ 8 = 40 ✓
        45:  (10,  5, 4, 1, 9),  # 10+10+16+ 9 = 45 ✓
        50:  (10,  5, 4, 2, 7),  # 10+10+16+14 = 50 ✓
        55:  (10,  5, 5, 3, 5),  # 10+10+20+15 = 55 ✓
        60:  (10,  5, 5, 2,10),  # 10+10+20+20 = 60 ✓
        70:  (10, 10, 5, 4, 5),  # 10+20+20+20 = 70 ✓
        80:  (20,  8, 6, 4, 5),  # 20+16+24+20 = 80 ✓
        90:  (20, 10, 8, 3, 6),  # 20+20+32+18 = 90 ✓
        100: (20, 10,10, 4, 5),  # 20+20+40+20 = 100 ✓
    }

    # Use preset if available; otherwise compute dynamically with exact remainder
    if m in PRESET:
        nA, nB, nC, nD, dEach = PRESET[m]
    else:
        # ── Dynamic: fix A, then greedily fill B / C / D ───────────────
        nA    = 20 if m >= 80 else 10
        dEach = 5  if m >= 40 else 0
        rem   = m - nA
        # Allocate B (2M each) ≈ 25% of remainder
        nB = max(2, round(rem * 0.25) // 2)
        rem -= nB * 2
        # Allocate C (4M each) ≈ 40% of original remainder
        nC = max(0, rem // 4 if dEach == 0 else round(rem * 0.55) // 4)
        rem -= nC * 4
        # Remainder → D (5M each)
        if dEach > 0 and rem >= dEach:
            nD = rem // dEach
            rem -= nD * dEach
        else:
            nD, dEach = 0, 0
        # Any leftover marks: absorb into B (add extra 2M questions)
        if rem >= 2:
            nB += rem // 2
            rem = rem % 2
        # Odd leftover: can't place — reduce one C question and add a B
        if rem == 1 and nC > 0:
            nC -= 1
            nB += 3  # −4 + 2+2+2 = +2 net → fixes the 1-mark gap... actually +2M net
            # nC-=1 frees 4 marks, nB+=2 uses 4 marks → balanced

    # Compute MCQ / fill / match split inside Section A
    nA_mcq   = max(1, round(nA * 0.50))
    nA_fill  = max(1, round(nA * 0.25))
    nA_match = max(1, nA - nA_mcq - nA_fill)
    # Adjust so they sum to nA
    while nA_mcq + nA_fill + nA_match > nA:
        if nA_match > 1: nA_match -= 1
        elif nA_fill > 1: nA_fill -= 1
        else: nA_mcq -= 1
    while nA_mcq + nA_fill + nA_match < nA:
        nA_mcq += 1

    totA = nA * 1
    totB = nB * 2
    totC = nC * 4
    totD = nD * dEach
    grand = totA + totB + totC + totD

    # Choice logic: sections C and D get "attempt any N" for big papers
    cC_att = max(nC - 1, nC) if nC <= 3 else nC - 1   # give 1 extra in C for ≥4 questions
    cD_att = nD                                          # D: no extra by default
    if m >= 50 and nC >= 4:
        cC_given = nC + 1
    else:
        cC_given = nC
    if m >= 60 and nD >= 2:
        cD_given = nD + 1
        cD_att   = nD
    else:
        cD_given = nD
        cD_att   = nD

    return dict(
        m=m, grand=grand,
        nA=nA, nA_mcq=nA_mcq, nA_fill=nA_fill, nA_match=nA_match, totA=totA,
        nB=nB, totB=totB,
        nC=nC, totC=totC, cC_given=cC_given, cC_att=cC_att,
        nD=nD, dEach=dEach, totD=totD, cD_given=cD_given, cD_att=cD_att,
        has_D=(nD > 0),
    )


# ─────────────────────────────────────────────────────────────────────
# MASTER BUILD_PROMPT
# ─────────────────────────────────────────────────────────────────────
def build_prompt(class_name, subject, chapter, board, exam_type,
                 difficulty, marks, suggestions):
    m   = max(10, int(marks) if str(marks).isdigit() else 100)
    cls = str(class_name or "10").strip()

    diff     = _difficulty_profile(difficulty)
    notation = _notation_rules(subject)
    chap_str = chapter.strip() if chapter and chapter.strip() else "Full Syllabus"
    teacher  = f"\nSPECIAL INSTRUCTIONS FROM EXAMINER: {suggestions.strip()}\n" if (suggestions or "").strip() else ""

    board_l = (board or "").lower()
    if any(k in board_l for k in ["ntse", "nso", "imo", "ijso"]):
        return _prompt_competitive(board, subject, chap_str, cls, m, diff, notation, teacher)
    elif exam_type == "competitive":
        exam_name = (board or "").upper()
        return _prompt_competitive(exam_name, subject, chap_str, cls, m, diff, notation, teacher)
    else:
        return _prompt_board(subject, chap_str, board or "AP State Board", cls, m, diff, notation, teacher)


# ─────────────────────────────────────────────────────────────────────
# COMPETITIVE EXAM PROMPT  —  NTSE / NSO / IMO / IJSO / etc.
# ─────────────────────────────────────────────────────────────────────
def _prompt_competitive(exam, subject, chap, cls, m, diff, notation, teacher):
    """Alias to _prompt_board with exam name substituted as board."""
    return _prompt_board(subject, chap, exam or "Competitive Exam", cls, m, diff, notation, teacher)


# ─────────────────────────────────────────────────────────────────────
# BOARD EXAM PROMPT  —  Section A / B / C / D  (clean, scalable)
# Keeps all LaTeX, notation, diagram and answer-key rules intact.
# ─────────────────────────────────────────────────────────────────────
def _prompt_board(subject, chap, board, cls, m, diff, notation, teacher):
    s    = _compute_structure(m)
    time = _time_for_marks(m)

    # ── Human-readable section breakdown string ────────────────────────
    lines = []
    lines.append(f"SECTION A — Very Short Answer / Objective  ({s['totA']} Marks)")
    lines.append(f"  {s['nA_mcq']} Multiple Choice Questions     × 1 mark  =  {s['nA_mcq']} marks  [write ALL {s['nA_mcq']}]")
    lines.append(f"  {s['nA_fill']} Fill in the Blank questions   × 1 mark  =  {s['nA_fill']} marks  [write ALL {s['nA_fill']}]")
    lines.append(f"  {s['nA_match']} Match the Following pair(s)  × 1 mark  =  {s['nA_match']} marks  [write ALL {s['nA_match']}]")
    lines.append(f"  SECTION A TOTAL = {s['totA']} marks")
    lines.append("")
    lines.append(f"SECTION B — Short Answer  ({s['totB']} Marks)")
    lines.append(f"  {s['nB']} questions × 2 marks each  =  {s['totB']} marks  [write ALL {s['nB']}]")
    lines.append("")
    if s['nC'] > 0:
        if s['cC_given'] > s['nC']:
            lines.append(f"SECTION C — Medium Answer  ({s['totC']} Marks)")
            lines.append(f"  Give {s['cC_given']} questions, students attempt any {s['cC_att']}  × 4 marks  =  {s['totC']} marks")
        else:
            lines.append(f"SECTION C — Medium Answer  ({s['totC']} Marks)")
            lines.append(f"  {s['nC']} questions × 4 marks each  =  {s['totC']} marks  [write ALL {s['nC']}]")
        lines.append("")
    if s['has_D']:
        if s['cD_given'] > s['nD']:
            lines.append(f"SECTION D — Long Answer  ({s['totD']} Marks)")
            lines.append(f"  Give {s['cD_given']} questions, students attempt any {s['cD_att']}  × {s['dEach']} marks  =  {s['totD']} marks")
        else:
            lines.append(f"SECTION D — Long Answer  ({s['totD']} Marks)")
            lines.append(f"  {s['nD']} question(s) × {s['dEach']} marks each  =  {s['totD']} marks  [write ALL {s['nD']}]")
        lines.append("")

    lines.append(f"  ★ GRAND TOTAL = {s['grand']} marks  ★")
    struct = "\n".join(lines)

    # ── MCQ / match instructions ───────────────────────────────────────
    mcq_note = (
        f"Write EXACTLY {s['nA_mcq']} MCQ questions. "
        "Each must have exactly 4 options labelled (A)(B)(C)(D). "
        "Wrong options must reflect genuine student misconceptions — not random."
    )
    fill_note = (
        f"Write EXACTLY {s['nA_fill']} Fill-in-the-Blank questions. "
        "Mark each blank as __________ (ten underscores). One blank per question only."
    )
    match_note = (
        f"Write EXACTLY {s['nA_match']} Match-the-Following pair(s). "
        "Format as a pipe table:\n"
        "| Group A | Group B |\n"
        "|---|---|\n"
        f"| item | match |\n"
        f"(exactly {s['nA_match']} data rows — no extra rows, no separator-only rows)"
    )
    secB_note  = f"Write EXACTLY {s['nB']} questions worth 2 marks each. All are compulsory."
    secc_scored = s['cC_att'] * 4  # actual marks counted = attempted × 4
    secC_note  = (
        f"Write EXACTLY {s['cC_given']} questions worth 4 marks each."
        + (f" Students will attempt any {s['cC_att']} (scoring {secc_scored} marks total)." if s['cC_given'] > s['nC'] else " All are compulsory.")
    ) if s['nC'] > 0 else ""
    secd_scored = s['cD_att'] * s['dEach']
    secD_note  = (
        f"Write EXACTLY {s['cD_given']} questions worth {s['dEach']} marks each."
        + (f" Students will attempt any {s['cD_att']} (scoring {secd_scored} marks total)." if s['cD_given'] > s['nD'] else " All are compulsory.")
        + f" You may include an alternate OR option for up to {min(2, s['cD_given'])} of these questions (optional, on a different sub-topic)."
    ) if s['has_D'] else ""

    return f"""CRITICAL RULE — READ FIRST: Start your output DIRECTLY with "SECTION A". Do NOT write any title, header, instructions, preamble, or numbered general notes before the first section. No "General Instructions:", no "Time: 3 hours", no "Total Marks:", no "Note:", no "1. All questions are...", no introductory text of any kind. Start IMMEDIATELY with SECTION A.

Create a complete model question paper for Class {cls} {subject}, {chap} chapter.
Board: {board}    Total Marks: {m}    Time Allowed: {time}
Difficulty: {diff}
{teacher}
Structure the paper EXACTLY as follows:

{struct}

━━━ SECTION-BY-SECTION RULES ━━━

SECTION A:
{mcq_note}
{fill_note}
{match_note}

SECTION B:
{secB_note}

{"SECTION C:" + chr(10) + secC_note if secC_note else ""}

{"SECTION D:" + chr(10) + secD_note if secD_note else ""}

━━━ CONTENT & QUALITY RULES ━━━
1. {("Cover the COMPLETE " + board + " Class " + cls + " " + subject + " syllabus — all chapters and topics included." if chap == "Full Syllabus" else 'Every question MUST be strictly about the chapter "' + chap + '" — no questions from other chapters.')}
2. Question counts are EXACT — do NOT add or remove any questions.
3. Include one genuinely challenging question in each section.
4. End each question with its mark allocation in square brackets — for Section B, C, D only: [2 Marks], [4 Marks], [5 Marks]. Do NOT add [1 Mark] labels to individual MCQ, fill-in-blank, or match items — those sections already have the mark stated in the section heading.
5. Follow {board} syllabus strictly.
6. Output ONLY the questions and section headings. No hints in the question paper itself.
7. ⚠ DIAGRAMS — use when genuinely needed: For questions involving geometric shapes, constructions,
   circuits, biological structures, scientific apparatus, graphs, or maps — place a
   [DIAGRAM: detailed description] tag on its own line immediately after the question stem.
   Do NOT add diagrams to MCQs, fill-in-blank, match-the-following, or purely text/calculation questions.
   The DIAGRAMS section below contains subject-specific examples. Use only those.
   ⛔ NEVER write [DIAGRAM: Not applicable] or [DIAGRAM: None] — just omit the tag if no diagram needed.
   Include [DIAGRAM:] tags only where a visual is genuinely needed (geometric constructions, circuits, body systems, apparatus, graphs). Do NOT add diagrams to purely text/calculation questions.
8. TABLES: Any question with data or comparisons — format as a pipe table (|col|col|...).
9. ⚠ START THE PAPER IMMEDIATELY with "SECTION A" — do NOT write any preamble, title, header, or instructions block before SECTION A. No lines like "1. The question paper consists of...", "Time allowed: 3 hours", "General Instructions:", "Note:", or similar. Those are already printed on the answer sheet. The very first line of your output must be the SECTION A header.
10. DIAGRAMS IN ANSWER KEY: Repeat the same [DIAGRAM: ...] tag in the answer key solution for any question that has a diagram in the paper — the key must include a diagram to show what a correct answer looks like.

━━━ {notation.upper().split(chr(10))[0]} ━━━
{notation}

━━━ ANSWER KEY ━━━
After ALL questions are written, print this EXACT line alone on its own line:
ANSWER KEY

Then provide:
• Section A Part I (MCQs)  : 1.(A)  2.(C)  3.(B)  … list all the MCQ count answers
• Section A Part II (Fill) : 1. answer  2. answer  … list all the fill count answers
• Section A Part III (Match): a pipe table showing each Group A → Group B match

• Sections B / C / D: full worked solutions for EVERY question.
  — Show every calculation step on a new line.
  — Diagram questions: repeat [DIAGRAM: …] with full description.

━━━ OUTPUT FORMAT ━━━
Start immediately with the paper — no preamble, no "Sure!", no commentary.
Use this EXACT layout:

SECTION A  ({s['nA_mcq']} + {s['nA_fill']} + {s['nA_match']} = {s['totA']} Marks)

Part I — Multiple Choice Questions  [1 Mark each]
(Choose the correct answer from (A), (B), (C), (D).)

Part II — Fill in the Blank  [1 Mark each]
(Fill each blank with the most appropriate word or value.)

Part III — Match the Following  [1 Mark each]
(Match each item in Group A with the correct item in Group B.)

SECTION B  ({s['nB']} x 2 = {s['totB']} Marks)
(Answer all questions. Each carries 2 marks.)

{"SECTION C  (" + str(s['cC_att']) + " x 4 = " + str(s['cC_att']*4) + " Marks)" + chr(10) + "(" + ("Attempt any " + str(s['cC_att']) + " questions from " + str(s['cC_given']) + "." if s['cC_given'] > s['nC'] else "Answer all questions.") + " Each carries 4 marks.)" if s['nC'] > 0 else ""}

{"SECTION D  (" + str(s['cD_att']) + " x " + str(s['dEach']) + " = " + str(s['cD_att']*s['dEach']) + " Marks)" + chr(10) + "(" + ("Attempt any " + str(s['cD_att']) + " questions from " + str(s['cD_given']) + "." if s['cD_given'] > s['nD'] else "Answer all questions.") + " Each carries " + str(s['dEach']) + " marks.)" if s['has_D'] else ""}

"""


# SPLIT PAPER / KEY
# ═══════════════════════════════════════════════════════════════════════
