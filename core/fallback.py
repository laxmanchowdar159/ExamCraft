"""
core/fallback.py
A single, always-safe offline template used only when Gemini is
completely unreachable (no key configured, or every model/key
exhausted). Previously this branched into _fallback_math /
_fallback_social / _fallback_generic for non-science subjects —
none of those functions actually existed, so any fallback paper
for Maths, Social Studies, or a language subject crashed with a
NameError. This version is one template that adapts its labels to
the subject and never crashes.
"""

SAMPLE_QUESTIONS = {
    "science": {
        "mcq": "Which of the following best describes Newton's First Law of Motion?",
        "fill": "The chemical formula of water is __________.",
        "short": "State Newton's Second Law of Motion.",
        "long": "Derive the equations of motion $v = u + at$ and $s = ut + \\frac{1}{2}at^2$.",
    },
    "math": {
        "mcq": "The roots of $x^2 - 5x + 6 = 0$ are:",
        "fill": "The value of $\\sin 30°$ is __________.",
        "short": "Solve for x: $2x + 5 = 17$.",
        "long": "Prove that the sum of the first $n$ natural numbers is $\\frac{n(n+1)}{2}$.",
    },
    "social": {
        "mcq": "The Indian Constitution was adopted on:",
        "fill": "The capital of the Maurya Empire was __________.",
        "short": "Name two Fundamental Rights guaranteed by the Indian Constitution.",
        "long": "Explain the causes and consequences of the Indian freedom movement of 1857.",
    },
    "generic": {
        "mcq": "Which of the following statements is correct?",
        "fill": "Complete the sentence: __________.",
        "short": "Write a short note on the topic covered in this chapter.",
        "long": "Explain, with examples, the key concept covered in this chapter.",
    },
}


def _subject_bucket(subject: str) -> str:
    s = (subject or "").lower()
    if any(k in s for k in ("math", "algebra", "geometry", "trigonometry", "statistics")):
        return "math"
    if any(k in s for k in ("social", "history", "geography", "civics", "economics")):
        return "social"
    if any(k in s for k in ("science", "physics", "chemistry", "biology")):
        return "science"
    return "generic"


def build_local_paper(cls, subject, chapter, marks, difficulty) -> str:
    """
    Minimal, always-valid offline paper — used only when the AI
    backend is completely unreachable. Not curriculum-precise; it
    exists so the app degrades gracefully instead of failing outright.
    """
    bucket = _subject_bucket(subject)
    q = SAMPLE_QUESTIONS[bucket]
    subject_label = subject or bucket.title()
    chapter_line = f"Chapter: {chapter}" if chapter and chapter != "Full Syllabus" else "Full Syllabus"

    return f"""{subject_label} — Model Question Paper
Subject: {subject_label}   Class: {cls}   {chapter_line}
Total Marks: {marks}   Difficulty: {difficulty}   Time Allowed: 3 Hours

[NOTE: The AI service was unavailable, so this is a basic offline
template rather than a fully AI-generated paper. Try again shortly
for a curriculum-matched paper.]

PART A — OBJECTIVE (20 Marks)

Section-I — Multiple Choice Questions [1 Mark each]
1. {q['mcq']} [1 Mark]
   (A) Option A   (B) Option B   (C) Option C   (D) Option D  (   )

Section-II — Fill in the Blanks [1 Mark each]
11. {q['fill']}

PART B — WRITTEN (80 Marks)

Section-IV — Very Short Answer Questions [2 Marks each]
(Answer ALL questions in not more than 5 lines each.)
1. {q['short']} [2 Marks]

Section-VI — Long Answer Questions [6 Marks each]
(Answer any FOUR of the following six questions.)
21. {q['long']} [6 Marks]

ANSWER KEY

Section-I:
1. (B)

Section-II:
11. See textbook chapter for the exact term.

Section-IV:
1. See textbook definition for this chapter.

Section-VI:
21. Full worked solution requires the AI service — please retry generation.
"""
