"""
core/splitter.py
Splits raw AI output into (question paper, answer key).
"""
import re


def split_key(text):
    """Split AI output into (paper, answer_key). Handles all AI formatting variations."""
    patterns = [
        r'\nANSWER KEY\n',
        r'\n---\s*ANSWER KEY\s*---\n',
        r'(?i)\nANSWER KEY:?\s*\n',
        r'(?i)\n\*+\s*ANSWER KEY\s*\*+\s*\n',
        r'(?i)\n#{1,3}\s*ANSWER KEY\s*\n',
        r'(?i)\nANSWER\s+KEY\s+(?:&|AND)\s+SOLUTIONS?\s*\n',
        r'(?i)\nSOLUTIONS?\s*(?:&\s*ANSWER\s*KEY)?\s*\n',
        r'(?i)(?:^|\n)ANSWER KEY\s*\n',
    ]
    for pat in patterns:
        parts = re.split(pat, text, maxsplit=1)
        if len(parts) == 2 and parts[1].strip():
            return parts[0].strip(), parts[1].strip()
    # Last resort: scan line by line
    lines = text.split('\n')
    for i, ln in enumerate(lines):
        s = ln.strip().upper().rstrip(':').rstrip('*').strip()
        if s in ('ANSWER KEY', 'ANSWER KEY & SOLUTIONS', 'ANSWERS', 'SOLUTIONS',
                 '--- ANSWER KEY ---', '=== ANSWER KEY ===',
                 'ANSWER KEY AND SOLUTIONS', 'SOLUTIONS & ANSWER KEY'):
            paper = '\n'.join(lines[:i]).strip()
            key   = '\n'.join(lines[i+1:]).strip()
            if key:
                return paper, key
    # Final fallback: look for a line that is ONLY "ANSWER KEY" with optional punctuation/decoration
    for i, ln in enumerate(lines):
        cleaned = re.sub(r'[^A-Z\s]', '', ln.strip().upper()).strip()
        if cleaned in ('ANSWER KEY', 'ANSWERS', 'ANSWER KEY AND SOLUTIONS'):
            paper = '\n'.join(lines[:i]).strip()
            key   = '\n'.join(lines[i+1:]).strip()
            if key and len(key) > 30:  # sanity check — key must have real content
                return paper, key
    return text.strip(), ""


