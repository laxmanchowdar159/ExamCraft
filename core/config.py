"""
core/config.py
Environment variables, file paths, and static reference data.
This is the single source of truth for "where things are" and
"what keys/models are available" — nothing else in the codebase
should read os.environ directly.
"""
import os
import json
from pathlib import Path

# ── API keys ─────────────────────────────────────────────────────────
GEMINI_KEY   = os.environ.get("GEMINI_API_KEY",   "").strip()
GEMINI_KEY_2 = os.environ.get("GEMINI_API_KEY_2", "").strip()
GEMINI_KEY_3 = os.environ.get("GEMINI_API_KEY_3", "").strip()
ACTIVE_KEYS  = [k for k in (GEMINI_KEY, GEMINI_KEY_2, GEMINI_KEY_3) if k]

# ── Error alert email (optional) ────────────────────────────────────
ALERT_RECIPIENT = os.environ.get("ALERT_EMAIL", "laxmanchowdary159@gmail.com")
SMTP_EMAIL       = os.environ.get("SMTP_EMAIL", "")
SMTP_PASSWORD    = os.environ.get("SMTP_PASSWORD", "")
SMTP_HOST        = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT        = int(os.environ.get("SMTP_PORT", "587"))

# ── Paths ────────────────────────────────────────────────────────────
BASE_DIR  = Path(os.path.dirname(os.path.abspath(__file__))).parent
DATA_DIR  = BASE_DIR / "data"
FONT_DIR  = BASE_DIR / "static" / "fonts"
SYS_FONT_DIR = "/usr/share/fonts/truetype/dejavu"


def load_json(name: str) -> dict:
    p = DATA_DIR / name
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}


PATTERN_AP_TS = load_json("exam_patterns/ap_ts.json")
PATTERN_COMP  = load_json("exam_patterns/competitive.json")
CURRICULUM    = load_json("curriculum.json")

# ── Gemini models, fastest/most-reliable first ─────────────────────
# Speed strategy lives in core/ai_text.py — this is just the candidate
# pool it races across.
GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemma-3-4b-it",
    "gemma-3-1b-it",
]
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# ── Time budgets (seconds) — the whole reason paper generation used
# to take 3 minutes is that none of these existed before: every step
# was allowed to retry serially with 180s timeouts. Everything in
# ai_text.py / ai_diagrams.py / app.py generate() is built around
# these numbers so a request has a predictable upper bound.
BUDGET_TEXT_SECONDS      = 22   # main paper + answer key generation
BUDGET_DIAGRAM_SECONDS   = 12   # all diagrams combined, parallel
BUDGET_TOTAL_SECONDS     = 40   # hard ceiling for the whole /generate call
