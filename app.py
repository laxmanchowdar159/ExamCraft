import os
import re
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from io import BytesIO

# ── PDF ──────────────────────────────────────────────────────────────
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY, TA_RIGHT
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.units import mm

# ── Flask ────────────────────────────────────────────────────────────
from flask import Flask, render_template, request, jsonify, send_file

# ── Gemini (REST — no SDK needed, keeps Vercel bundle small) ─────────
# LangChain + Gemini imports
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.runnables import RunnableWithFallbacks
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

import requests as _requests  # kept for diagram SVG calls
GENAI_AVAILABLE = True
genai = None

app = Flask(__name__, template_folder="templates",
            static_folder="static", static_url_path="/static")

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# ═══════════════════════════════════════════════════════════════════════
# ERROR EMAIL SYSTEM
# Config via env vars:
#   SMTP_EMAIL     — your Gmail address (sender)
#   SMTP_PASSWORD  — Gmail App Password (16-char, not your login password)
#   ALERT_EMAIL    — recipient (defaults to laxmanchowdary159@gmail.com)
# ═══════════════════════════════════════════════════════════════════════
import smtplib
import socket
import platform
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

_ALERT_RECIPIENT = os.environ.get("ALERT_EMAIL", "laxmanchowdary159@gmail.com")
_SMTP_EMAIL      = os.environ.get("SMTP_EMAIL", "")        # sender Gmail
_SMTP_PASSWORD   = os.environ.get("SMTP_PASSWORD", "")     # Gmail App Password
_SMTP_HOST       = os.environ.get("SMTP_HOST", "smtp.gmail.com")
_SMTP_PORT       = int(os.environ.get("SMTP_PORT", "587"))


def _fmt_dict(d: dict, indent: int = 2) -> str:
    """Pretty-format a dict for the email body."""
    pad = " " * indent
    lines = []
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"{pad}{k}:")
            lines.append(_fmt_dict(v, indent + 4))
        elif isinstance(v, str) and len(v) > 200:
            lines.append(f"{pad}{k}: [TRUNCATED — first 200 chars]")
            lines.append(f"{pad}    {v[:200]}…")
        else:
            lines.append(f"{pad}{k}: {v!r}")
    return "\n".join(lines)


def send_error_email(
    error_type: str,
    error_msg: str,
    traceback_str: str = "",
    user_choices: dict = None,
    extra_context: dict = None,
) -> bool:
    """
    Send a detailed error report to the alert recipient.
    Returns True if sent successfully, False otherwise.
    Does NOT raise — email failure must never crash the app.
    """
    if not _SMTP_EMAIL or not _SMTP_PASSWORD:
        # Email not configured — log to console and return
        print(f"[EMAIL ALERT — not configured] {error_type}: {error_msg}")
        return False

    try:
        ts  = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        env = os.environ.get("ENVIRONMENT", os.environ.get("VERCEL_ENV", "unknown"))

        # ── Build subject ────────────────────────────────────────────
        subject = f"🚨 ExamCraft Error — {error_type} @ {ts}"

        # ── Build text body ──────────────────────────────────────────
        sections = []

        sections.append("=" * 60)
        sections.append("EXAMCRAFT ERROR REPORT")
        sections.append("=" * 60)
        sections.append(f"Time       : {ts}")
        sections.append(f"Error Type : {error_type}")
        sections.append(f"Environment: {env}")
        sections.append(f"Host       : {socket.gethostname()}")
        sections.append(f"Platform   : {platform.platform()}")
        sections.append(f"Python     : {platform.python_version()}")
        sections.append("")

        sections.append("-" * 60)
        sections.append("ERROR MESSAGE")
        sections.append("-" * 60)
        sections.append(str(error_msg))
        sections.append("")

        if user_choices:
            sections.append("-" * 60)
            sections.append("USER CHOICES (every field)")
            sections.append("-" * 60)
            sections.append(_fmt_dict(user_choices))
            sections.append("")

        if extra_context:
            sections.append("-" * 60)
            sections.append("EXTRA CONTEXT")
            sections.append("-" * 60)
            sections.append(_fmt_dict(extra_context))
            sections.append("")

        if traceback_str:
            sections.append("-" * 60)
            sections.append("FULL TRACEBACK")
            sections.append("-" * 60)
            sections.append(traceback_str)
            sections.append("")

        sections.append("=" * 60)
        sections.append("END OF REPORT — ExamCraft Auto-Mailer")
        sections.append("=" * 60)

        plain_body = "\n".join(sections)

        # ── Build HTML body ──────────────────────────────────────────
        def _html_escape(s):
            return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace(chr(10),"<br>")

        uc_rows = ""
        if user_choices:
            for k, v in user_choices.items():
                vstr = _html_escape(str(v)[:300])
                uc_rows += f"<tr><td style='padding:6px 12px;color:#94a3b8;font-size:12px;white-space:nowrap'>{_html_escape(k)}</td><td style='padding:6px 12px;font-size:12px;color:#e2e8f0;word-break:break-all'>{vstr}</td></tr>"

        ctx_rows = ""
        if extra_context:
            for k, v in extra_context.items():
                vstr = _html_escape(str(v)[:300])
                ctx_rows += f"<tr><td style='padding:6px 12px;color:#94a3b8;font-size:12px;white-space:nowrap'>{_html_escape(k)}</td><td style='padding:6px 12px;font-size:12px;color:#e2e8f0;word-break:break-all'>{vstr}</td></tr>"

        tb_html = f"""<div style="background:#0f172a;border-radius:8px;padding:16px;margin-top:8px;overflow-x:auto">
          <pre style="color:#f87171;font-size:11px;font-family:monospace;white-space:pre-wrap;margin:0">{_html_escape(traceback_str[:4000])}</pre>
        </div>""" if traceback_str else "<p style='color:#64748b;font-size:12px'>No traceback available.</p>"

        html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#0a0f1e;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif">
<div style="max-width:680px;margin:32px auto;background:#111827;border-radius:16px;overflow:hidden;border:1px solid #1e293b">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#0f2149,#1a3a6e);padding:28px 32px">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:4px">
      <span style="font-size:24px">🚨</span>
      <h1 style="margin:0;color:#fff;font-size:20px;font-weight:700;letter-spacing:-.5px">ExamCraft Error Report</h1>
    </div>
    <p style="margin:0;color:#94a3b8;font-size:13px">{ts}</p>
  </div>

  <!-- Error summary -->
  <div style="padding:24px 32px;border-bottom:1px solid #1e293b">
    <div style="background:#1e1b4b;border:1px solid #3730a3;border-radius:10px;padding:16px 18px">
      <p style="margin:0 0 6px;color:#a5b4fc;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:1px">{_html_escape(error_type)}</p>
      <p style="margin:0;color:#f8fafc;font-size:14px;line-height:1.6">{_html_escape(str(error_msg)[:500])}</p>
    </div>
    <table style="margin-top:16px;border-collapse:collapse;width:100%">
      <tr><td style="color:#64748b;font-size:12px;padding:4px 0;width:120px">Environment</td><td style="color:#cbd5e1;font-size:12px">{_html_escape(env)}</td></tr>
      <tr><td style="color:#64748b;font-size:12px;padding:4px 0">Host</td><td style="color:#cbd5e1;font-size:12px">{_html_escape(socket.gethostname())}</td></tr>
    </table>
  </div>

  <!-- User choices -->
  <div style="padding:24px 32px;border-bottom:1px solid #1e293b">
    <h2 style="margin:0 0 14px;color:#e2e8f0;font-size:14px;font-weight:600">📋 User Choices</h2>
    {"<table style='width:100%;border-collapse:collapse;background:#0f172a;border-radius:8px;overflow:hidden'>" + uc_rows + "</table>" if uc_rows else "<p style='color:#64748b;font-size:12px'>No user choices captured.</p>"}
  </div>

  <!-- Extra context -->
  {"<div style='padding:24px 32px;border-bottom:1px solid #1e293b'><h2 style='margin:0 0 14px;color:#e2e8f0;font-size:14px;font-weight:600'>🔧 Context</h2><table style='width:100%;border-collapse:collapse;background:#0f172a;border-radius:8px;overflow:hidden'>" + ctx_rows + "</table></div>" if ctx_rows else ""}

  <!-- Traceback -->
  <div style="padding:24px 32px">
    <h2 style="margin:0 0 10px;color:#e2e8f0;font-size:14px;font-weight:600">🔍 Traceback</h2>
    {tb_html}
  </div>

  <div style="padding:16px 32px;background:#0d1117;border-top:1px solid #1e293b">
    <p style="margin:0;color:#475569;font-size:11px;text-align:center">ExamCraft Auto-Mailer · {ts}</p>
  </div>
</div>
</body>
</html>"""

        # ── Assemble message ─────────────────────────────────────────
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"ExamCraft Alerts <{_SMTP_EMAIL}>"
        msg["To"]      = _ALERT_RECIPIENT
        msg.attach(MIMEText(plain_body, "plain"))
        msg.attach(MIMEText(html_body,  "html"))

        # ── Send via STARTTLS ────────────────────────────────────────
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(_SMTP_EMAIL, _SMTP_PASSWORD)
            server.sendmail(_SMTP_EMAIL, _ALERT_RECIPIENT, msg.as_string())

        print(f"[EMAIL SENT] Error report → {_ALERT_RECIPIENT}")
        return True

    except Exception as mail_err:
        print(f"[EMAIL FAILED] Could not send error report: {mail_err}")
        return False


def _capture_user_choices(data: dict) -> dict:
    """Extract and label every user choice from a request payload."""
    return {
        "exam_type":        data.get("examType", "—"),
        "state_board":      data.get("state", "—"),
        "competitive_exam": data.get("competitiveExam", "—"),
        "class":            data.get("class", "—"),
        "subject":          data.get("subject", "—"),
        "chapter":          data.get("chapter", "—"),
        "scope":            data.get("scope", "—"),
        "all_chapters":     data.get("all_chapters", False),
        "total_marks":      data.get("marks", "—"),
        "difficulty":       data.get("difficulty", "—"),
        "include_answer_key": data.get("includeKey", False),
        "special_instructions": (data.get("suggestions") or "")[:300] or "—",
        "used_fallback":    data.get("use_fallback", False),
    }

# ═══════════════════════════════════════════════════════════════════════
# LOAD EXAM PATTERN DATA
# ═══════════════════════════════════════════════════════════════════════
_DATA_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "data"

def _load_json(name):
    p = _DATA_DIR / name
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}

_PATTERN_AP_TS    = _load_json("exam_patterns/ap_ts.json")
_PATTERN_COMP     = _load_json("exam_patterns/competitive.json")
_CURRICULUM       = _load_json("curriculum.json")

# ═══════════════════════════════════════════════════════════════════════
# FONT REGISTRATION
# ═══════════════════════════════════════════════════════════════════════
_fonts_registered = False

def register_fonts():
    global _fonts_registered
    if _fonts_registered:
        return
    _base = os.path.dirname(os.path.abspath(__file__))
    fdir  = os.path.join(_base, "static", "fonts")
    sys_d = "/usr/share/fonts/truetype/dejavu"

    def reg(name, filename):
        for d in [fdir, sys_d]:
            p = os.path.join(d, filename)
            if os.path.exists(p):
                try:
                    pdfmetrics.registerFont(TTFont(name, p))
                    return True
                except Exception:
                    pass
        return False

    reg("Reg",  "DejaVuSans.ttf")
    reg("Bold", "DejaVuSans-Bold.ttf")
    reg("Ital", "DejaVuSans-Oblique.ttf")
    _fonts_registered = True

def _f(variant="Reg"):
    register_fonts()
    fallback = {"Reg": "Helvetica", "Bold": "Helvetica-Bold", "Ital": "Helvetica-Oblique"}
    try:
        pdfmetrics.getFont(variant)
        return variant
    except Exception:
        return fallback.get(variant, "Helvetica")


# ═══════════════════════════════════════════════════════════════════════
# LATEX → REPORTLAB XML
# CRITICAL: NEVER use Unicode sub/superscript chars — use <sub>/<super>
# ═══════════════════════════════════════════════════════════════════════
_MATH_RE = re.compile(r'(\$\$[^$]+\$\$|\$[^$\n]+\$)')

_GREEK = {
    r'\alpha':'α', r'\beta':'β', r'\gamma':'γ', r'\delta':'δ',
    r'\epsilon':'ε', r'\varepsilon':'ε', r'\zeta':'ζ', r'\eta':'η',
    r'\theta':'θ', r'\iota':'ι', r'\kappa':'κ', r'\lambda':'λ',
    r'\mu':'μ', r'\nu':'ν', r'\xi':'ξ', r'\pi':'π', r'\rho':'ρ',
    r'\sigma':'σ', r'\tau':'τ', r'\upsilon':'υ', r'\phi':'φ',
    r'\varphi':'φ', r'\chi':'χ', r'\psi':'ψ', r'\omega':'ω',
    r'\Gamma':'Γ', r'\Delta':'Δ', r'\Theta':'Θ', r'\Lambda':'Λ',
    r'\Xi':'Ξ', r'\Pi':'Π', r'\Sigma':'Σ', r'\Upsilon':'Υ',
    r'\Phi':'Φ', r'\Psi':'Ψ', r'\Omega':'Ω',
}
_SYM = {
    # Arithmetic
    r'\times':'×', r'\div':'÷', r'\pm':'±', r'\mp':'∓',
    r'\cdot':'·', r'\bullet':'•',
    # Dots
    r'\ldots':'…', r'\cdots':'⋯', r'\vdots':'⋮', r'\ddots':'⋱',
    # Calculus/Analysis
    r'\infty':'∞', r'\partial':'∂', r'\nabla':'∇',
    r'\int':'∫', r'\oint':'∮', r'\iint':'∬', r'\iiint':'∭',
    r'\sum':'Σ', r'\prod':'Π', r'\coprod':'∐',
    # Sets
    r'\in':'∈', r'\notin':'∉', r'\ni':'∋',
    r'\subset':'⊂', r'\subseteq':'⊆', r'\supset':'⊃', r'\supseteq':'⊇',
    r'\cup':'∪', r'\cap':'∩', r'\emptyset':'∅', r'\varnothing':'∅',
    r'\setminus':'\\',
    # Relations
    r'\leq':'≤', r'\geq':'≥', r'\le':'≤', r'\ge':'≥',
    r'\neq':'≠', r'\ne':'≠', r'\approx':'≈',
    r'\equiv':'≡', r'\sim':'~', r'\simeq':'≃', r'\propto':'∝',
    r'\ll':'≪', r'\gg':'≫',
    # Arrows
    r'\rightarrow':'→', r'\leftarrow':'←',
    r'\Rightarrow':'⇒', r'\Leftarrow':'⇐',
    r'\leftrightarrow':'↔', r'\Leftrightarrow':'⇔',
    r'\uparrow':'↑', r'\downarrow':'↓',
    r'\to':'→', r'\gets':'←', r'\mapsto':'↦',
    r'\implies':'⇒', r'\iff':'⇔',
    # Logic
    r'\forall':'∀', r'\exists':'∃', r'\nexists':'∄',
    r'\neg':'¬', r'\lnot':'¬', r'\land':'∧', r'\lor':'∨',
    # Geometry
    r'\angle':'∠', r'\measuredangle':'∡', r'\sphericalangle':'∢',
    r'\perp':'⊥', r'\parallel':'∥', r'\not\parallel':'∦',
    r'\triangle':'△', r'\square':'□',
    r'\cong':'≅', r'\ncong':'≇', r'\sim':'~',
    # Common
    r'\degree':'°', r'\circ':'°',
    r'\therefore':'∴', r'\because':'∵',
    r'\prime':'′', r'\doubleprime':'″',
    r'\%':'%', r'\$':'$', r'\#':'#',
    # Trig (just ensure they pass through cleanly)
    r'\sin':'sin', r'\cos':'cos', r'\tan':'tan',
    r'\sec':'sec', r'\csc':'csc', r'\cot':'cot',
    r'\arcsin':'arcsin', r'\arccos':'arccos', r'\arctan':'arctan',
    r'\sinh':'sinh', r'\cosh':'cosh', r'\tanh':'tanh',
    r'\log':'log', r'\ln':'ln', r'\lg':'log',
    r'\exp':'exp', r'\lim':'lim', r'\max':'max', r'\min':'min',
    r'\sup':'sup', r'\inf':'inf', r'\det':'det',
    r'\gcd':'gcd', r'\lcm':'lcm', r'\mod':'mod',
    r'\deg':'deg', r'\dim':'dim', r'\ker':'ker', r'\rank':'rank',
    # Number sets
    r'\mathbb{R}':'ℝ', r'\mathbb{Z}':'ℤ', r'\mathbb{N}':'ℕ',
    r'\mathbb{Q}':'ℚ', r'\mathbb{C}':'ℂ',
    # Brackets (just remove the commands, let the chars through)
    r'\lfloor':'⌊', r'\rfloor':'⌋', r'\lceil':'⌈', r'\rceil':'⌉',
    r'\langle':'⟨', r'\rangle':'⟩',
    # Misc
    r'\hline':'', r'\\':'',
}


def _extract_braced(s, pos):
    if pos >= len(s) or s[pos] != '{':
        return (s[pos], pos + 1) if pos < len(s) else ('', pos)
    depth, i = 0, pos
    while i < len(s):
        if   s[i] == '{': depth += 1
        elif s[i] == '}': depth -= 1
        if depth == 0:
            return s[pos+1:i], i+1
        i += 1
    return s[pos+1:], len(s)


def _latex_to_rl(expr: str) -> str:
    s = expr.strip().lstrip('$').rstrip('$').strip()
    s = re.sub(r'\\(?:text|mathrm|mathbf|mathit|boldsymbol)\{([^}]*)\}', r'\1', s)
    s = re.sub(r'\\(?:left|right)(?=[|(\[\]{}.])', '', s)
    for k in sorted(_GREEK, key=len, reverse=True):
        s = s.replace(k, _GREEK[k])
    for k in sorted(_SYM, key=len, reverse=True):
        s = s.replace(k, _SYM[k])

    result, i = '', 0
    while i < len(s):
        if s[i:i+5] == '\\frac':
            i += 5
            num, i = _extract_braced(s, i)
            den, i = _extract_braced(s, i)
            result += f'({_latex_to_rl(num)}/{_latex_to_rl(den)})'
            continue
        if s[i:i+5] == '\\sqrt':
            i += 5
            n_root = ''
            if i < len(s) and s[i] == '[':
                j = s.find(']', i); j = j if j != -1 else i
                n_root = s[i+1:j];  i = j + 1
            inner, i = _extract_braced(s, i)
            result += f'{n_root}√({_latex_to_rl(inner)})'
            continue
        if s[i] == '^':
            i += 1
            raw, i = _extract_braced(s, i)
            inner = _latex_to_rl(raw).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
            result += f'<super>{inner}</super>'
            continue
        if s[i] == '_':
            i += 1
            raw, i = _extract_braced(s, i)
            inner = _latex_to_rl(raw).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
            result += f'<sub>{inner}</sub>'
            continue
        decorated = False
        for cmd in (r'\overline', r'\widehat', r'\widetilde', r'\vec', r'\hat', r'\bar', r'\tilde'):
            if s[i:].startswith(cmd):
                i += len(cmd)
                inner, i = _extract_braced(s, i)
                result += _latex_to_rl(inner)
                decorated = True
                break
        if decorated:
            continue
        if s[i] == '\\':
            j = i + 1
            while j < len(s) and (s[j].isalpha() or s[j] == '*'):
                j += 1
            if j == i + 1 and j < len(s):
                j += 1
            i = j
            result += ' '
            continue
        c = s[i]
        if   c == '&': result += '&amp;'
        elif c == '<': result += '&lt;'
        elif c == '>': result += '&gt;'
        else:          result += c
        i += 1
    return re.sub(r'  +', ' ', result).strip()


def _process(text: str) -> str:
    text = re.sub(r'\\_', '_', text)
    text = re.sub(r'\\-',  '-', text)
    text = re.sub(r'\\%',  '%', text)

    def _repl(m):
        return _latex_to_rl(m.group(0))
    converted = _MATH_RE.sub(_repl, text)

    tag_re = re.compile(r'(</?(?:super|sub|b|i|font)[^>]*>)')
    parts  = tag_re.split(converted)
    safe   = []
    for p in parts:
        if tag_re.match(p):
            safe.append(p)
        else:
            p = p.replace('&', '&amp;')
            p = re.sub(r'&amp;(amp|lt|gt|quot|#\d+);', r'&\1;', p)
            p = re.sub(r'<', '&lt;', p)
            safe.append(p)

    out = ''.join(safe)
    out = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', out)
    out = re.sub(r'\*(.+?)\*',     r'<i>\1</i>', out)
    return out


# ═══════════════════════════════════════════════════════════════════════
# COLOURS
# ═══════════════════════════════════════════════════════════════════════
# Professional exam paper palette — authoritative, print-clean, executive-grade
C_NAVY   = HexColor("#0f2149")   # Deep navy — top bar, major headers
C_NAVY2  = HexColor("#1a3a6e")   # Mid navy — section accents
C_STEEL  = HexColor("#1e293b")   # Near-black — question text
C_BODY   = HexColor("#1e293b")   # Body text
C_GREY   = HexColor("#475569")   # Meta text, marks labels
C_LGREY  = HexColor("#94a3b8")   # Light divider lines
C_LIGHT  = HexColor("#f0f4f8")   # Section banner background (light blue-grey)
C_LIGHT2 = HexColor("#e8eef5")   # Alternate row tint
C_RULE   = HexColor("#0f2149")   # Horizontal rules — navy
C_MARK   = HexColor("#0f2149")   # Mark bracket color
C_KHEAD  = HexColor("#0f2149")   # Answer key banner bg
C_KFILL  = HexColor("#fafbfc")   # Answer key bg (off-white)
C_KSTEP  = HexColor("#1e293b")   # Key step text
C_ACCENT = HexColor("#2563eb")   # Thin accent line
C_HDR    = HexColor("#0f2149")   # Legacy compat
# Aliases for backward compat
C_KRED   = C_KHEAD
C_STEP   = C_KSTEP


# ═══════════════════════════════════════════════════════════════════════
# STYLES
# ═══════════════════════════════════════════════════════════════════════
def _styles():
    """Return all ReportLab paragraph styles for a professional exam paper."""
    register_fonts()
    R, B, I = _f("Reg"), _f("Bold"), _f("Ital")
    base = getSampleStyleSheet()

    def S(name, **kw):
        if name not in base:
            base.add(ParagraphStyle(name=name, **kw))
        else:
            for k, v in kw.items():
                setattr(base[name], k, v)

    # ── Paper header ──────────────────────────────────────────────────
    S("PTitle",    fontName=B, fontSize=14, textColor=white,
      alignment=TA_CENTER, leading=20, spaceAfter=0, spaceBefore=0)
    S("PSubtitle", fontName=R, fontSize=9.5, textColor=HexColor("#d0e4f7"),
      alignment=TA_CENTER, leading=14, spaceAfter=0)
    S("PMeta",     fontName=R, fontSize=9, textColor=C_GREY,
      alignment=TA_LEFT, leading=13, spaceAfter=0)
    S("PMetaR",    fontName=R, fontSize=9, textColor=C_GREY,
      alignment=TA_RIGHT, leading=13, spaceAfter=0)
    S("PMetaC",    fontName=R, fontSize=9.5, textColor=C_BODY,
      alignment=TA_CENTER, leading=14, spaceAfter=0)
    S("PMetaBold", fontName=B, fontSize=9.5, textColor=C_NAVY,
      alignment=TA_CENTER, leading=14, spaceAfter=0)

    # ── Section banners ───────────────────────────────────────────────
    S("SecBanner", fontName=B, fontSize=10.5, textColor=C_NAVY,
      leading=15, spaceAfter=0, spaceBefore=0)
    S("SecBannerKey", fontName=B, fontSize=11, textColor=white,
      alignment=TA_CENTER, leading=16, spaceAfter=0, spaceBefore=0)

    # ── Instructions ──────────────────────────────────────────────────
    S("InstrHead", fontName=B, fontSize=9.5, textColor=C_NAVY,
      leading=14, spaceAfter=2, spaceBefore=4)
    S("Instr",     fontName=R, fontSize=9.5, textColor=C_BODY,
      leading=14, spaceAfter=2, leftIndent=18, firstLineIndent=-18)

    # ── Question text ─────────────────────────────────────────────────
    S("Q",    fontName=R, fontSize=11, textColor=C_STEEL,
      alignment=TA_JUSTIFY, leading=17, spaceBefore=7, spaceAfter=2,
      leftIndent=26, firstLineIndent=-26)
    S("QCont",fontName=R, fontSize=11, textColor=C_STEEL,
      alignment=TA_JUSTIFY, leading=17, spaceBefore=1, spaceAfter=2, leftIndent=26)
    S("QSub", fontName=R, fontSize=11, textColor=C_STEEL,
      alignment=TA_JUSTIFY, leading=17, spaceBefore=3, spaceAfter=2,
      leftIndent=40, firstLineIndent=-14)
    S("Opt",  fontName=R, fontSize=10.5, textColor=C_BODY,
      leading=15, spaceAfter=1, leftIndent=0)

    # ── Answer key ────────────────────────────────────────────────────
    S("KTitle",fontName=B, fontSize=13, textColor=white,
      alignment=TA_CENTER, leading=19, spaceAfter=0, spaceBefore=0)
    S("KSec",  fontName=B, fontSize=10.5, textColor=C_NAVY,
      leading=14, spaceAfter=2, spaceBefore=6)
    S("KQ",    fontName=B, fontSize=10.5, textColor=C_NAVY,
      leading=14, spaceAfter=2, spaceBefore=5, leftIndent=24, firstLineIndent=-24)
    S("KStep", fontName=R, fontSize=10.5, textColor=C_KSTEP,
      leading=16, spaceAfter=2, leftIndent=24)
    S("KSub",  fontName=R, fontSize=10.5, textColor=C_BODY,
      leading=16, spaceAfter=2, leftIndent=36, firstLineIndent=-12)
    S("KMath", fontName=I, fontSize=10.5, textColor=C_BODY,
      leading=16, spaceAfter=2, leftIndent=32)

    # ── Diagram label ─────────────────────────────────────────────────
    S("DiagLabel", fontName=I, fontSize=9, textColor=C_GREY,
      leading=12, spaceAfter=2, spaceBefore=2)

    return base
class ExamCanvas:
    """Page template: thin navy top-rule, subtle footer with page number."""
    def __call__(self, canvas, doc):
        W, H = A4
        LM = doc.leftMargin
        RM = W - doc.rightMargin

        canvas.saveState()

        # ── Top rule — two lines (thick navy + hairline) ─────────────
        canvas.setStrokeColor(C_NAVY)
        canvas.setLineWidth(1.2)
        canvas.line(LM, H - 10*mm, RM, H - 10*mm)
        canvas.setStrokeColor(C_ACCENT)
        canvas.setLineWidth(0.5)
        canvas.line(LM, H - 10*mm - 1.5, RM, H - 10*mm - 1.5)

        # ── Footer rule + text ────────────────────────────────────────
        canvas.setStrokeColor(HexColor("#c8d5e5"))
        canvas.setLineWidth(0.4)
        canvas.line(LM, 22, RM, 22)

        canvas.setFont(_f("Reg"), 7.5)
        canvas.setFillColor(C_GREY)
        canvas.drawString(LM, 10, "ExamCraft  |  Generated Paper — For Internal Use")
        canvas.drawRightString(RM, 10, f"Page  {doc.page}")

        canvas.restoreState()


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════
def _sec_banner(text, st, pw, is_key=False):
    """Section banner: navy bg for answer key, pale blue-grey for questions."""
    if is_key:
        p = Paragraph(f'<b>{text}</b>', st["SecBannerKey"])
        bg, line_c = C_NAVY, C_NAVY
    else:
        p = Paragraph(f'<b>{text}</b>', st["SecBanner"])
        bg, line_c = C_LIGHT, C_NAVY2

    # Left accent bar (3pt wide navy strip)
    accent = Table([[""]], colWidths=[3])
    accent.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), C_ACCENT),
        ("TOPPADDING",    (0,0),(-1,-1), 0),
        ("BOTTOMPADDING", (0,0),(-1,-1), 0),
    ]))

    row = Table([[accent, p]], colWidths=[3, pw - 3])
    row.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), bg),
        ("LINEBELOW",     (0,0),(-1,-1), 0.6, line_c),
        ("LINETOP",       (0,0),(-1,-1), 0.6, line_c),
        ("LEFTPADDING",   (0,0),(0,-1),  0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 8),
        ("TOPPADDING",    (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("LEFTPADDING",   (0,1),(1,-1),  8),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))
    return row


def _opts_table(opts, st, pw):
    rows = []
    for k in range(0, len(opts), 2):
        L = opts[k]
        R = opts[k+1] if k+1 < len(opts) else ('', '')
        lp = Paragraph(f'<b>({L[0]})</b>  {L[1]}', st["Opt"])
        rp = Paragraph(f'<b>({R[0]})</b>  {R[1]}' if R[0] else '', st["Opt"])
        rows.append([lp, rp])
    col = pw / 2
    t = Table(rows, colWidths=[col, col])
    t.setStyle(TableStyle([
        ("TOPPADDING",    (0,0),(-1,-1), 1),
        ("BOTTOMPADDING", (0,0),(-1,-1), 1),
        ("LEFTPADDING",   (0,0),(-1,-1), 20),
        ("RIGHTPADDING",  (0,0),(-1,-1), 4),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
    ]))
    return t


def _pipe_table(rows, st, pw):
    if not rows:
        return None
    mc = max(len(r) for r in rows)
    norm = [r + ['']*(mc-len(r)) for r in rows]
    R, B = _f("Reg"), _f("Bold")

    para_rows = []
    for ri, row in enumerate(norm):
        sty = st["KQ"] if ri == 0 else st["KStep"]
        para_rows.append([Paragraph(_process(c), sty) for c in row])

    cw = pw / mc
    t = Table(para_rows, colWidths=[cw]*mc, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTNAME",       (0,0),(-1,-1), R),
        ("FONTSIZE",       (0,0),(-1,-1), 9.5),
        ("BACKGROUND",     (0,0),(-1,0),  HexColor("#e8e8e8")),
        ("TEXTCOLOR",      (0,0),(-1,0),  black),
        ("FONTNAME",       (0,0),(-1,0),  B),
        ("GRID",           (0,0),(-1,-1), 0.5, HexColor("#aaaaaa")),
        ("ROWBACKGROUNDS", (0,1),(-1,-1), [white, HexColor("#f8f8f8")]),
        ("TOPPADDING",     (0,0),(-1,-1), 4),
        ("BOTTOMPADDING",  (0,0),(-1,-1), 4),
        ("LEFTPADDING",    (0,0),(-1,-1), 7),
        ("RIGHTPADDING",   (0,0),(-1,-1), 7),
        ("VALIGN",         (0,0),(-1,-1), "MIDDLE"),
    ]))
    return t


# ═══════════════════════════════════════════════════════════════════════
# LINE-TYPE DETECTORS
# ═══════════════════════════════════════════════════════════════════════
def _is_sec_hdr(s):
    s = s.strip()
    if re.match(r'^(SECTION|Section|PART|Part)\s+[A-Da-d](\s|[-:]|$)', s):
        return True
    return bool(re.match(r'^(GENERAL INSTRUCTIONS|General Instructions'
                         r'|Instructions|Note:|NOTE:)\s*$', s))

def _is_table_row(s):
    return '|' in s and s.strip().startswith('|')

def _is_divider(s):
    return bool(re.match(r'^\|[\s\-:|]+\|', s.strip()))

def _is_hrule(s):
    s = s.strip()
    return len(s) > 3 and all(c in '-=_' for c in s)

_HDR_SKIP = re.compile(
    r'^(School|Subject|Class|Board|Total\s*Marks|Time\s*Allowed|Date)\s*[:/]',
    re.I)

# ── Figure junk-line filter ───────────────────────────────────────────
# AI sometimes outputs stray figure-description lines that are NOT
# proper [DIAGRAM:…] markers. These patterns match lines that look like
# leaked figure metadata and should be silently dropped from the PDF.
_FIG_JUNK = re.compile(
    r'^('
    r'Figure\s*:'                               # "Figure: Triangle ABC with..."
    r'|Triangle\s+[A-Z]{2,4}$'                 # "Triangle ABC"
    r'|Trapezium\s+[A-Z]{2,4}$'                # "Trapezium ABCD"
    r'|Right[\s-]?angled?\s+(Triangle|Iso)'     # "Right-angled Triangle", "Right-angled Isosceles..."
    r'|Right\s+Angle\s+Triangle$'              # "Right Angle Triangle"
    r'|Altitude(\s+from\s+\w+(\s+to\s+\w+)?)?$'  # "Altitude" / "Altitude from A to BC"
    r'|Angle\s+[A-Z]\s*=?\s*\d+°?$'            # "Angle A = 60°"
    r'|Angle\s+[A-Z]\s+\d+°?$'
    r'|∠[A-Z]\s*=\s*\d+°?$'                   # "∠A = 60°"
    r'|[A-Z]+\s+is\s+(altitude|median|midpoint|perpendicular)\s+to\s+[A-Z]+'
    r'|Side\s+[A-Z]{2}$'                       # "Side AB"
    r'|Parallel\s+[A-Z]{2}$'                   # "Parallel DE"
    r'|Diagonals?\s+[A-Z]{2}\s+and\s+[A-Z]{2}' # "Diagonals AC and BD intersect at O"
    r'|[A-Z]{2}\s+Parallel\s+to\s+[A-Z]{2}$'  # "DE Parallel to BC"
    r'|[A-Z]+\s+on\s+[A-Z]{2}$'               # "D on AB"
    r'|[A-Z]+\s+Parallel\s+to\s+[A-Z]+$'
    r'|Right\s+(angles?|angle\s+at\s+vertex)'
    r'|Perpendicular$'
    r'|Distance\s+from\s+[A-Z]\s+to\s+[A-Z]+'
    r'|(?:\d+°?\s*){3,}$'                      # "60° 60° 60°" lines of angles
    r'|(?:140"|140\s*"?\s*){2,}'               # "140" 140" 140"" repeated
    r'|θ\s*=\s*\d+°?\s*$'                      # "θ = 60°"
    r'|α\s*=\s*\d+°?\s*$'
    r'|[A-Z]M\s*is\s+altitude'
    r'|(?:Angle\s+[A-Z]\s*\n?){2,}'           # multiple "Angle X" lines
    r')',
    re.IGNORECASE
)


# ═══════════════════════════════════════════════════════════════════════
# MAIN PDF BUILDER
# ═══════════════════════════════════════════════════════════════════════

def _strip_ai_noise(text: str) -> str:
    """Remove AI-generated preamble and closing remarks from the paper text."""
    if not text or not text.strip():
        return text
    lines = text.split('\n')
    _preamble_pat = re.compile(
        r'^(okay|sure|here|alright|certainly|of course|i\'ve|i have|'
        r'below is|here is|here\'s|this is|the following|examcraft|'
        r'created by|note:|please note|disclaimer)',
        re.IGNORECASE
    )
    _real_start = re.compile(
        r'^(SECTION|PART|Q\.?\s*\d|^\d+[\.\)\]]\s|'
        r'MATHEMATICS|SCIENCE|PHYSICS|CHEMISTRY|BIOLOGY|SOCIAL|ENGLISH|HINDI|TELUGU|'
        r'Class\s+\d|Board:|Total\s+Marks)',
        re.IGNORECASE
    )
    _closing_pat = re.compile(
        r'^(i hope|this completes|do you want|let me know|please let|'
        r'feel free|if you need|note that|end of paper|---\s*$)',
        re.IGNORECASE
    )
    # Find where real content starts
    start_idx = 0
    for i, ln in enumerate(lines[:20]):  # only check first 20 lines for preamble
        s = ln.strip()
        if not s:
            continue
        if _preamble_pat.match(s):
            start_idx = i + 1
        elif _real_start.match(s):
            start_idx = i
            break
        elif re.match(r'^[-=]{3,}\s*$', s):
            start_idx = i + 1
    # Trim trailing closing remarks
    end_idx = len(lines)
    for i in range(len(lines) - 1, max(len(lines) - 10, 0) - 1, -1):
        s = lines[i].strip()
        if not s:
            end_idx = i
        elif _closing_pat.match(s) or re.match(r'^[-=]{3,}\s*$', s):
            end_idx = i
        else:
            break
    return '\n'.join(lines[start_idx:end_idx]).strip()


def create_exam_pdf(text, subject, chapter, board="",
                   answer_key=None, include_key=False, diagrams=None,
                   marks=None) -> bytes:

    # Strip AI preamble/closing noise before parsing
    text = _strip_ai_noise(text)
    if answer_key:
        answer_key = _strip_ai_noise(answer_key)

    register_fonts()
    st = _styles()

    LM = BM = 20 * mm
    RM = 20 * mm
    TM = 16 * mm
    PW = A4[0] - LM - RM

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=LM, rightMargin=RM,
                            topMargin=TM, bottomMargin=BM,
                            title=f"{subject}{' – '+chapter if chapter else ''}")
    elems = []

    def _pull(pat, default=""):
        m = re.search(pat, text, re.I | re.M)
        return m.group(1).strip() if m else default

    # Use passed marks if provided (more reliable than parsing AI text)
    h_marks = str(marks) if marks else _pull(r'Total\s*Marks\s*[:/]\s*(\d+)', "100")
    h_time  = _pull(r'Time\s*(?:Allowed|:)\s*([^\n]+)', "3 Hours")
    h_class = _pull(r'Class\s*[:/]?\s*(\d+\w*)', "")
    h_board = board or _pull(r'Board\s*[:/]\s*([^\n]+)', "")

    disp_title   = subject or "Question Paper"
    disp_chapter = chapter or ""

    # ── Full-width navy header block ──────────────────────────────────
    #  ┌─────────────────────────────────────────┐  ← navy fill
    #  │   SUBJECT — CHAPTER          [Logo dot] │
    #  │   Board | Class                Time     │
    #  ├─────────────────────────────────────────┤  ← accent stripe
    #  │  Marks: XX  | Class: X | Board: ...     │  ← light meta row
    #  └─────────────────────────────────────────┘
    title_str = disp_title.upper()
    if disp_chapter:
        title_str += f"  ·  {disp_chapter}"

    # --- Title row (navy bg, white text) ---
    dot = Paragraph('<font color="#2563eb">●</font>', st["PTitle"])
    tit = Paragraph(f'<b>{title_str}</b>', st["PTitle"])

    tbl_top = Table([[tit, dot]], colWidths=[PW - 18, 18])
    tbl_top.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), C_NAVY),
        ("TOPPADDING",    (0,0),(-1,-1), 10),
        ("BOTTOMPADDING", (0,0),(-1,-1), 10),
        ("LEFTPADDING",   (0,0),(0,-1),  14),
        ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))

    # --- Accent stripe (1 pt, bright blue) ---
    stripe = Table([[""]], colWidths=[PW])
    stripe.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), C_ACCENT),
        ("TOPPADDING",    (0,0),(-1,-1), 0),
        ("BOTTOMPADDING", (0,0),(-1,-1), 0),
        ("LINEBELOW",     (0,0),(-1,-1), 0, white),
        ("ROWHEIGHT",     (0,0),(-1,-1), 2),
    ]))

    # --- Meta row (light bg, 3-column) ---
    board_cls = "  ·  ".join(x for x in [h_board, f"Class {h_class}" if h_class else ""] if x)
    c1 = Paragraph(f'<b>{board_cls}</b>', st["PMeta"])
    c2 = Paragraph(f'<font color="#0f2149"><b>Total Marks: {h_marks}</b></font>', st["PMetaBold"])
    c3 = Paragraph(f'<font color="#475569">Time: {h_time}</font>', st["PMetaR"])

    tbl_meta = Table([[c1, c2, c3]], colWidths=[PW*0.40, PW*0.30, PW*0.30])
    tbl_meta.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), C_LIGHT2),
        ("LINEBELOW",     (0,0),(-1,-1), 1.2, C_NAVY),
        ("TOPPADDING",    (0,0),(-1,-1), 5),
        ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))

    elems += [tbl_top, stripe, tbl_meta, Spacer(1, 10)]

    tbl_rows    = []
    in_table    = False
    pending_opts = []
    in_instr    = False

    def flush_table():
        nonlocal tbl_rows, in_table
        if tbl_rows:
            t = _pipe_table(tbl_rows, st, PW)
            if t:
                elems.append(Spacer(1, 3))
                elems.append(t)
                elems.append(Spacer(1, 5))
        tbl_rows, in_table = [], False

    def flush_opts():
        nonlocal pending_opts
        if pending_opts:
            elems.append(_opts_table(pending_opts, st, PW))
            elems.append(Spacer(1, 3))
        pending_opts = []

    lines = text.split('\n')
    i_line = 0

    def _is_general_instr(s):
        return bool(re.match(r'^(GENERAL INSTRUCTIONS|General Instructions'
                             r'|Instructions)\s*$', s.strip()))

    def _is_instr_line(s):
        return bool(re.match(r'^\d+\.\s+', s.strip())) and in_instr

    while i_line < len(lines):
        raw  = lines[i_line].rstrip()
        line = re.sub(r'\\_', '_', re.sub(r'\\-', '-', raw))
        s    = line.strip()
        i_line += 1

        if _is_table_row(line):
            if _is_divider(line):
                continue
            flush_opts()
            cells = [c.strip() for c in line.split('|') if c.strip()]
            if cells:
                tbl_rows.append(cells)
                in_table = True
            continue
        elif in_table:
            flush_table()

        if not s:
            flush_opts()
            elems.append(Spacer(1, 4))
            continue

        if _HDR_SKIP.match(s):
            continue

        # Drop stray figure-description lines that the AI emits alongside [DIAGRAM:] markers
        if _FIG_JUNK.match(s):
            continue

        # "Figure: ..." lines emitted outside [DIAGRAM:] tags — convert to italic label
        fig_m = re.match(r'^Figure\s*:\s*(.+)', s, re.I)
        if fig_m:
            flush_opts()
            desc = fig_m.group(1).strip()
            # Remove trailing angle noise like "Angle A = 60° Angle B = 60°..."
            desc = re.sub(r'(?:\.\s*)?(?:Angle\s+[A-Z]\s*=?\s*\d+°?\s*){1,}$', '', desc).strip()
            desc = re.sub(r'(?:\s*\d+°){2,}', '', desc).strip()
            if desc:
                elems.append(Paragraph(f'<i>Figure: {desc}</i>', st["DiagLabel"]))
            continue

        if _is_hrule(line):
            flush_opts()
            elems.append(HRFlowable(width="100%", thickness=0.4,
                                    color=C_RULE, spaceBefore=3, spaceAfter=3))
            continue

        if s.startswith('[DIAGRAM:') or s.lower().startswith('[draw'):
            flush_opts()
            label   = s.strip('[]')
            desc    = re.sub(r'^DIAGRAM:\s*', '', label, flags=re.I).strip()
            # Sanitise desc — drop any angle/measurement noise that crept in
            desc = re.sub(r'(?:\s*\d+°){2,}', '', desc).strip()
            elems.append(Paragraph(f'<i>Figure: {desc}</i>', st["DiagLabel"]))

            drawing = None
            if diagrams:
                # Exact match first
                if desc in diagrams and diagrams[desc]:
                    drawing = svg_to_best_image(diagrams[desc], width_pt=PW * 0.65)
                if drawing is None:
                    # Fuzzy match: find diagram key with most word overlap
                    desc_words = set(re.findall(r'\w+', desc.lower()))
                    best_key, best_score = None, 0
                    for d_key, d_svg in diagrams.items():
                        if not d_svg:
                            continue
                        key_words = set(re.findall(r'\w+', d_key.lower()))
                        overlap = len(desc_words & key_words)
                        if overlap > best_score:
                            best_score, best_key = overlap, d_key
                    if best_key and best_score >= 2:
                        drawing = svg_to_best_image(diagrams[best_key], width_pt=PW * 0.65)

            if drawing is not None:
                elems.append(Spacer(1, 3))
                # Centre the drawing
                outer_d = Table([[drawing]], colWidths=[PW])
                outer_d.setStyle(TableStyle([
                    ('ALIGN',         (0,0),(-1,-1), 'CENTER'),
                    ('TOPPADDING',    (0,0),(-1,-1), 2),
                    ('BOTTOMPADDING', (0,0),(-1,-1), 2),
                ]))
                elems.append(outer_d)
            else:
                # Clean placeholder box — no stray text inside, just a neat space
                blank_height_mm = 38  # ~38 mm reserved for hand-drawn diagram
                ph_label = Paragraph(
                    f'<i>[ Draw diagram here: {desc} ]</i>',
                    st["DiagLabel"])
                box = Table(
                    [[ph_label],
                     [Spacer(1, blank_height_mm * mm - 20)]],
                    colWidths=[PW * 0.72])
                box.setStyle(TableStyle([
                    ('BOX',           (0,0),(-1,-1), 0.6, C_RULE),
                    ('BACKGROUND',    (0,0),(-1,-1), HexColor('#f9f9f9')),
                    ('TOPPADDING',    (0,0),(-1,-1), 6),
                    ('BOTTOMPADDING', (0,0),(-1,-1), 6),
                    ('LEFTPADDING',   (0,0),(-1,-1), 10),
                    ('RIGHTPADDING',  (0,0),(-1,-1), 10),
                    ('VALIGN',        (0,0),(-1,-1), 'TOP'),
                ]))
                outer = Table([[box]], colWidths=[PW])
                outer.setStyle(TableStyle([
                    ('ALIGN',         (0,0),(-1,-1), 'CENTER'),
                    ('TOPPADDING',    (0,0),(-1,-1), 2),
                    ('BOTTOMPADDING', (0,0),(-1,-1), 4),
                ]))
                elems.append(outer)
            elems.append(Spacer(1, 5))
            continue

        if _is_general_instr(s):
            flush_opts()
            in_instr = True
            # Skip instructions header — don't render to save space
            continue

        if _is_sec_hdr(line) and not _is_general_instr(s):
            flush_opts()
            in_instr = False
            elems.append(Spacer(1, 4))
            elems.append(_sec_banner(s, st, PW))
            elems.append(Spacer(1, 3))
            continue

        if _is_instr_line(s):
            # Skip instructions to save paper space
            continue

        opt_m = re.match(r'^\s*[\(\[]\s*([a-dA-D])\s*[\)\]\.]?\s+(.+)', s)
        if opt_m and not re.match(r'^(Q\.?\s*)?\d+[\.)\]]\s', s):
            in_instr = False
            letter = opt_m.group(1).lower()
            val    = _process(opt_m.group(2))
            pending_opts.append((letter, val))
            if len(pending_opts) >= 4:
                flush_opts()
            continue

        multi = re.findall(
            r'[\(\[]([a-dA-D])[\)\]\.]?\s+([^(\[]+?)(?=\s*[\(\[][a-dA-D][\)\]\.]|$)',
            s)
        if len(multi) >= 2 and not re.match(r'^(Q\.?\s*)?\d+[\.)\]]\s', s):
            flush_opts()
            in_instr = False
            opts = [(l.lower(), _process(v.strip())) for l, v in multi]
            elems.append(_opts_table(opts, st, PW))
            elems.append(Spacer(1, 3))
            continue

        q_m = re.match(r'^(Q\.?\s*)?(\d+)[\.)\]]\s+(.+)', s)
        if q_m and not in_instr:
            flush_opts()
            in_instr = False
            qnum  = q_m.group(2)
            qbody = q_m.group(3)
            mk_m = re.search(r'\[\s*(\d+)\s*[Mm]arks?\s*\]\s*$', qbody)
            mark_tag = ''
            if mk_m:
                mark_tag = f'[{mk_m.group(1)}M]'
                qbody    = qbody[:mk_m.start()].strip()
            body_rl = _process(qbody)
            mark_rl = (f'  <font color="{C_GREY.hexval()}" size="9">'
                       f'{mark_tag}</font>') if mark_tag else ''
            xml = (f'<font color="{C_STEEL.hexval()}"><b>{qnum}.</b></font>'
                   f'  {body_rl}{mark_rl}')
            elems.append(Paragraph(xml, st["Q"]))
            continue

        sub_m = re.match(r'^\s*[\(\[]\s*([a-z])\s*[\)\]]\s+(.+)', s)
        if sub_m and not in_instr:
            flush_opts()
            sl    = sub_m.group(1)
            sbod  = sub_m.group(2)
            mk_m2 = re.search(r'(\[\s*\d+\s*[Mm]arks?\s*\])\s*$', sbod)
            mark2 = ''
            if mk_m2:
                mark2 = (f'  <font color="{C_MARK.hexval()}" size="9.5">'
                         f'<b>{mk_m2.group(1)}</b></font>')
                sbod  = sbod[:mk_m2.start()].strip()
            elems.append(Paragraph(
                f'<b>({sl})</b>  {_process(sbod)}{mark2}',
                st["QSub"]))
            continue

        flush_opts()
        elems.append(Paragraph(_process(s), st["QCont"]))

    flush_opts()
    if in_table:
        flush_table()

    # ─── Answer key ───────────────────────────────────────────────────
    if include_key and answer_key and answer_key.strip():
        elems.append(PageBreak())
        # ── Answer Key header — full navy banner ─────────────────────
        key_dot = Paragraph('<font color="#2563eb">●</font>', st["KTitle"])
        key_lbl = Paragraph('<b>ANSWER  KEY  &amp;  SOLUTIONS</b>', st["KTitle"])
        kt = Table([[key_lbl, key_dot]], colWidths=[PW - 18, 18])
        kt.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), C_NAVY),
            ("TOPPADDING",    (0,0),(-1,-1), 10),
            ("BOTTOMPADDING", (0,0),(-1,-1), 10),
            ("LEFTPADDING",   (0,0),(0,-1),  14),
            ("RIGHTPADDING",  (0,0),(-1,-1), 10),
            ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ]))
        # Accent stripe under the key header
        kstripe = Table([[""]], colWidths=[PW])
        kstripe.setStyle(TableStyle([
            ("BACKGROUND", (0,0),(-1,-1), C_ACCENT),
            ("ROWHEIGHT",  (0,0),(-1,-1), 2),
            ("TOPPADDING", (0,0),(-1,-1), 0),
            ("BOTTOMPADDING", (0,0),(-1,-1), 0),
        ]))
        elems += [kt, kstripe, Spacer(1, 10)]

        key_lines = answer_key.split('\n')
        ki = 0
        while ki < len(key_lines):
            raw_k  = key_lines[ki].rstrip()
            line_k = re.sub(r'\\_', '_', re.sub(r'\\-', '-', raw_k))
            sk     = line_k.strip()
            ki    += 1

            if not sk:
                elems.append(Spacer(1, 3))
                continue

            if re.match(r'^(Section|SECTION|Part|PART)\s+[A-Da-d]\b', sk):
                ks = _sec_banner(sk.rstrip(":"), st, PW, is_key=False)
                elems += [Spacer(1, 6), ks, Spacer(1, 4)]
                continue

            q_km = re.match(r'^(Q\.?\s*)?(\d+)[\.)\]]\s*(.*)', sk)
            if q_km:
                body_k = q_km.group(3).strip()
                mk_k = re.search(r'(\[\s*\d+\s*[Mm]arks?\s*\])\s*$', body_k)
                mk_str = ''
                if mk_k:
                    mk_str  = (f'  <font color="{C_MARK.hexval()}" size="9">'
                               f'<b>{mk_k.group(1)}</b></font>')
                    body_k  = body_k[:mk_k.start()].strip()
                body_rl = _process(body_k) if body_k else ''
                elems.append(Paragraph(
                    f'<b>{q_km.group(2)}.</b>  {body_rl}{mk_str}',
                    st["KQ"]))
                continue

            sub_km = re.match(r'^\(?([a-z])\)\.?\s+(.+)', sk)
            if sub_km:
                elems.append(Paragraph(
                    f'<b>({sub_km.group(1)})</b>  {_process(sub_km.group(2))}',
                    st["KSub"]))
                continue

            if raw_k.startswith('   ') or raw_k.startswith('\t'):
                elems.append(Paragraph(_process(sk), st["KStep"]))
                continue

            if (sk.startswith('$') or
                    re.match(r'^[A-Za-z]\s*[=<>≤≥]', sk) or
                    re.match(r'^\s*(∴|Therefore|Hence|Thus)\b', sk, re.I)):
                elems.append(Paragraph(_process(sk), st["KStep"]))
                continue

            elems.append(Paragraph(_process(sk), st["KStep"]))

    doc.build(elems, onFirstPage=ExamCanvas(), onLaterPages=ExamCanvas())
    pdf = buf.getvalue()
    buf.close()
    return pdf


# ═══════════════════════════════════════════════════════════════════════
# GEMINI
# ═══════════════════════════════════════════════════════════════════════
# ── Model priority — tuned to your actual API quota ──────────────────
# Tier 1: gemini-2.5-flash          5 RPM / 250K TPM  ← best output
# Tier 2: gemini-2.5-flash-lite    10 RPM / 250K TPM  ← most RPM headroom
# Tier 3: gemini-2.5-flash-preview  stable alias for 2.5-flash
# Tier 4: gemini-1.5-flash          legacy wide-availability fallback
# NOTE: gemini-2.0-flash series shows 0/0 remaining — excluded
_PRIMARY_MODEL   = "gemini-2.5-flash"
_FALLBACK_MODEL  = "gemini-2.5-flash-lite"
_GEMINI_MODELS   = [
    "gemini-2.5-flash",                  # Tier 1 — best output quality
    "gemini-2.5-flash-lite",             # Tier 2 — most RPM headroom (10/min)
    "gemini-2.5-flash-preview-05-20",    # Tier 3 — explicit preview alias
    "gemini-1.5-flash",                  # Tier 4 — stable legacy fallback
    "gemini-1.5-pro",                    # Tier 5 — last resort
]
_GEMINI_BASE     = "https://generativelanguage.googleapis.com/v1beta/models"

# LangChain chain — built lazily on first call so startup stays fast
_lc_chain        = None
_lc_chain_fb     = None  # fallback chain


def _get_lc_chain(model_name: str):
    """Build (or return cached) a LangChain chain for the given model."""
    if not LANGCHAIN_AVAILABLE or not GEMINI_KEY:
        return None
    try:
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=GEMINI_KEY,
            temperature=0.2,
            max_output_tokens=16384,
            top_p=0.85,
            top_k=40,
            timeout=180,
            max_retries=2,
        )
        # System + Human message structure — better instruction following than
        # a single monolithic string prompt. The system message grounds the
        # model's role; the human message carries the full paper spec.
        prompt_tpl = ChatPromptTemplate.from_messages([
            (
                "system",
                (
                    "You are an expert Indian school exam paper setter with 20 years of experience. "
                    "You follow instructions with military precision. "
                    "Output ONLY the exam paper and answer key — no preamble, "
                    "no commentary, no markdown fences. "
                    "Start directly with the paper header."
                ),
            ),
            ("human", "{prompt}"),
        ])
        return prompt_tpl | llm | StrOutputParser()
    except Exception as e:
        return None


def discover_models():
    """Return model list for health endpoint."""
    if not GEMINI_KEY:
        return []
    return _GEMINI_MODELS


def call_gemini(prompt: str):
    """
    Call Gemini via LangChain (primary) or plain REST (fallback).
    Returns (text, error_or_None).
    """
    if not GEMINI_KEY:
        return None, "GEMINI_API_KEY not set."

    # ── LangChain path (preferred) ────────────────────────────────────
    if LANGCHAIN_AVAILABLE:
        for model_name in [_PRIMARY_MODEL, _FALLBACK_MODEL]:
            chain = _get_lc_chain(model_name)
            if chain is None:
                continue
            try:
                result = chain.invoke({"prompt": prompt})
                if result and result.strip():
                    call_gemini._last_model_used = model_name
                    return result.strip(), None
            except Exception as lc_err:
                last_lc_error = str(lc_err)
                # 429 quota → try next model immediately
                if "429" in str(lc_err) or "quota" in str(lc_err).lower():
                    continue
                # Other errors: log and fall through to REST fallback
                break

    # ── Plain REST fallback (no LangChain installed or LangChain failed) ─
    last_error = ""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature":     0.2,
            "maxOutputTokens": 16384,
            "topP":            0.85,
            "topK":            40,
        },
    }
    for model_name in _GEMINI_MODELS:
        url = f"{_GEMINI_BASE}/{model_name}:generateContent?key={GEMINI_KEY}"
        for attempt in range(2):
            try:
                resp = _requests.post(url, json=payload, timeout=180)
                if resp.status_code == 200:
                    data = resp.json()
                    text = (data.get("candidates", [{}])[0]
                                .get("content", {})
                                .get("parts", [{}])[0]
                                .get("text", "")).strip()
                    if text:
                        call_gemini._last_model_used = model_name
                        return text, None
                    last_error = f"{model_name}: empty response"
                    break
                elif resp.status_code in (404, 400):
                    last_error = f"{model_name}: HTTP {resp.status_code}"
                    break
                elif resp.status_code == 429:
                    last_error = f"{model_name}: quota exceeded"
                    time.sleep(0.5)
                    break
                else:
                    last_error = f"{model_name}: HTTP {resp.status_code} — {resp.text[:200]}"
                    if attempt == 0:
                        time.sleep(1.5)
                        continue
                    break
            except Exception as e:
                last_error = f"{model_name} ({attempt+1}): {e}"
                if attempt == 0:
                    time.sleep(1.5)
                    continue
                break

    return None, last_error


# ═══════════════════════════════════════════════════════════════════════
# FALLBACK PAPER (used when Gemini is unavailable)
# ═══════════════════════════════════════════════════════════════════════
def build_local_paper(cls, subject, chapter, marks, difficulty):
    return f"""{subject or "Science"} — Model Question Paper
Subject: {subject or "Science"}   Class: {cls}
Total Marks: {marks}   Time Allowed: 3 Hours 15 Minutes

GENERAL INSTRUCTIONS
1. Answer all the questions under Part-A on the question paper itself and attach it to the answer booklet at the end.
2. Read the instructions carefully and answer only the required number of questions in each section.
3. Figures to the right indicate marks allotted.
4. Draw neat, labelled diagrams wherever necessary.

PART A — OBJECTIVE (20 Marks)
(Answer in the question paper itself. Submit after 30 minutes.)

Section-I — Multiple Choice Questions [1 Mark each]
1. Which of the following best describes Newton's First Law of Motion? [1 Mark]
   (A) Force equals mass times acceleration
   (B) An object at rest stays at rest unless acted upon by an external force
   (C) Every action has an equal and opposite reaction
   (D) Acceleration is inversely proportional to mass  (   )

2. The SI unit of electric charge is __________. [1 Mark]
   (A) Ampere   (B) Coulomb   (C) Volt   (D) Ohm  (   )

Section-II — Fill in the Blanks [1 Mark each]
11. The chemical formula of water is __________.
12. The process by which plants make food using sunlight is called __________.

Section-III — Match the Following [1 Mark each]
| Group A | Group B |
|---|---|
| Newton | Laws of Motion |
| Ohm | Resistance |
| Faraday | Electromagnetic Induction |
| Darwin | Theory of Evolution |
| Mendel | Laws of Heredity |

PART B — WRITTEN (80 Marks)

Section-IV — Very Short Answer Questions [2 Marks each]
(Answer ALL questions in not more than 5 lines each.)

1. State Newton's Second Law of Motion. [2 Marks]
2. What is an electric circuit? Name its two essential components. [2 Marks]

Section-V — Short Answer Questions [4 Marks each]
(Answer any FOUR of the following six questions.)

11. Explain the process of photosynthesis with a labelled diagram. [4 Marks]
12. State and explain Ohm's Law. Give one example. [4 Marks]

Section-VI — Long Answer / Essay Questions [6 Marks each]
(Answer any FOUR of the following six questions.)

21. (i) Derive the equations of motion $v = u + at$ and $s = ut + \\frac{{1}}{{2}}at^2$. [6 Marks]
OR
    (ii) A car starts from rest and accelerates uniformly at $2\\ m/s^2$. Find the velocity after 5 seconds and the distance covered. [6 Marks]

Section-VII — Application / Problem Solving [10 Marks each]
(Answer any TWO of the following three questions.)

31. A wire of resistance $R = 6\\ \\Omega$ is connected to a $12\\ V$ battery.
    (a) Find the current flowing through the circuit. [3 Marks]
    (b) If three such resistors are connected in parallel, find the equivalent resistance and total current. [4 Marks]
    (c) State two differences between series and parallel circuits. [3 Marks]

ANSWER KEY

Section-I:
1. (B)   2. (B)

Section-II:
11. H₂O   12. Photosynthesis

Section-III:
Newton → Laws of Motion, Ohm → Resistance, Faraday → Electromagnetic Induction, Darwin → Theory of Evolution, Mendel → Laws of Heredity

Section-IV:
1. Newton's Second Law: The rate of change of momentum of a body is directly proportional to the applied force and takes place in the direction of the force. F = ma.
2. An electric circuit is a closed path through which electric current flows. Essential components: (1) a source of EMF (battery/cell), (2) conducting wires.

Section-V:
11. Photosynthesis: 6CO₂ + 6H₂O → C₆H₁₂O₆ + 6O₂. Occurs in chloroplasts. Requires sunlight, chlorophyll, CO₂, and water. [DIAGRAM: Chloroplast showing grana and stroma]

Section-VI:
21. (i) Starting from F = ma → a = (v-u)/t → v = u + at. Substituting: s = ut + ½at². 
(ii) Given: u=0, a=2 m/s², t=5s. v = 0 + 2×5 = 10 m/s. s = 0 + ½×2×25 = 25 m.

Section-VII:
31. (a) I = V/R = 12/6 = 2 A.
    (b) 1/R_eq = 1/6 + 1/6 + 1/6 = 3/6, R_eq = 2 Ω. I_total = 12/2 = 6 A.
    (c) Series: same current, voltages add. Parallel: same voltage, currents add.
"""


# ═══════════════════════════════════════════════════════════════════════
# MATH NOTATION RULES (injected into every STEM prompt)
# ═══════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════
# UNIVERSAL PROMPT ENGINE  v4
# One clean function per paper type. No chapter banks. No hallucination.
# The LLM uses its own deep knowledge; we provide structure + rules only.
# ═══════════════════════════════════════════════════════════════════════

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
    is_math = any(k in subj_l for k in ["math", "algebra", "geometry", "trigonometry", "statistics", "arithmetic"])
    is_science = any(k in subj_l for k in ["science", "physics", "chemistry", "biology"])
    is_stem = is_math or is_science

    if not is_stem:
        return (
            "FORMATTING:\n"
            "• [DIAGRAM: brief description] on its own line where a diagram/map/chart helps\n"
            "• Use plain text; no LaTeX needed for humanities subjects\n"
        )

    math_block = (
        "MATH & SCIENCE NOTATION — strictly required:\n"
        "• ALL expressions inside $…$:  $x^{2}$  $\\frac{a}{b}$  $\\sqrt{b^2-4ac}$\n"
        "• Chemical formulas: $H_2O$  $CO_2$  $H_2SO_4$  $Ca(OH)_2$\n"
        "• Powers / subscripts: $a^{3}$  $v_0$  $10^{-3}$  never write as plain a3 or v0\n"
        "• Greek letters: $\\theta$  $\\alpha$  $\\beta$  $\\pi$  $\\lambda$  $\\mu$  $\\Omega$\n"
        "• Trig: $\\sin\\theta$  $\\cos 60^{\\circ}$  $\\tan\\alpha$  $\\sin^2\\theta + \\cos^2\\theta = 1$\n"
        "• Fractions: $\\frac{mv^2}{r}$  $\\frac{\\Delta v}{\\Delta t}$  never use /\n"
        "• Units OUTSIDE $: write '5 cm', '$F = ma$ where F is in newtons'\n"
        "• Fill blanks: __________ (underscores only, never LaTeX)\n"
        "• Equations on own line: $PV = nRT$\n"
    )

    if is_science:
        diag_block = (
            "DIAGRAMS — include wherever they add clarity:\n"
            "• [DIAGRAM: labelled diagram of a plant cell showing cell wall, membrane, nucleus, vacuole, chloroplast]\n"
            "• [DIAGRAM: circuit diagram with 3Ω and 6Ω resistors in parallel connected to 12V battery]\n"
            "• [DIAGRAM: ray diagram showing refraction through a convex lens, showing F and 2F points]\n"
            "• [DIAGRAM: human digestive system with labels: mouth, oesophagus, stomach, small intestine, large intestine]\n"
            "Use format [DIAGRAM: …] on its own line after the question stem.\n"
            "Include diagrams in ≥30% of written-answer questions.\n"
        )
    elif is_math:
        diag_block = (
            "DIAGRAMS — include wherever geometric/graphical clarity is needed:\n"
            "• [DIAGRAM: triangle ABC with angle A=60°, B=80°, side BC=7cm, altitude from A to BC]\n"
            "• [DIAGRAM: number line showing solution set of inequality -3 < x ≤ 5]\n"
            "• [DIAGRAM: coordinate axes with parabola y=x²-4x+3, showing vertex and x-intercepts]\n"
            "Use format [DIAGRAM: …] on its own line after the question stem.\n"
            "Include diagrams in ≥20% of geometry/coordinate questions.\n"
        )
    else:
        diag_block = "• [DIAGRAM: description] on its own line where a visual would help\n"

    return math_block + "\n" + diag_block


def _compute_structure(marks):
    """Compute AP/TS paper structure that EXACTLY matches requested mark total."""
    m = max(10, int(marks))

    # ── Small papers (< 40M): simplified 2-section Part B ──────────────
    if m < 40:
        partA = max(4, round(m * 0.20))
        partB = m - partA

        n_mcq   = max(1, round(partA * 0.50))
        n_fill  = max(1, round(partA * 0.25))
        n_match = partA - n_mcq - n_fill
        if n_match < 1:
            n_match = 1
            n_fill  = max(1, partA - n_mcq - 1)
            n_mcq   = partA - n_fill - 1
        actual_partA = n_mcq + n_fill + n_match

        n_vsq      = max(1, round(partB * 0.50) // 2)
        vsq_tot    = n_vsq * 2
        sa_rem     = partB - vsq_tot
        n_sa_given = max(1, sa_rem // 2)
        sa_tot     = n_sa_given * 2
        if vsq_tot + sa_tot < partB:
            extra_vsq = (partB - vsq_tot - sa_tot) // 2
            n_vsq += extra_vsq; vsq_tot = n_vsq * 2

        return dict(
            m=m, partA=actual_partA, partB=partB, total=m, small=True,
            n_mcq=n_mcq, n_fill=n_fill, n_match=n_match,
            n_vsq=n_vsq, vsq_total=vsq_tot,
            n_sa_given=n_sa_given, n_sa_att=n_sa_given, sa_total=sa_tot, marks_sa=2,
            n_la_given=0, n_la_att=0, la_total=0,
            n_app_given=0, n_app_att=0, app_total=0, marks_per_app=0,
        )

    # ── Full papers (≥ 40M): complete 7-section AP/TS structure ────────
    partA = round(m * 0.20)
    partB = m - partA

    n_mcq   = round(partA * 0.50)
    n_fill  = round(partA * 0.25)
    n_match = partA - n_mcq - n_fill
    if n_match < 1:
        n_match = 1; n_fill = max(1, partA - n_mcq - 1)
    actual_partA = n_mcq + n_fill + n_match

    vsq_bud = round(partB * 0.25)
    sa_bud  = round(partB * 0.20)
    la_bud  = round(partB * 0.30)
    app_bud = partB - vsq_bud - sa_bud - la_bud

    n_vsq     = max(1, vsq_bud // 2)
    n_sa_att  = max(1, sa_bud  // 4)
    n_la_att  = max(1, la_bud  // 6)
    mpa       = 10 if app_bud >= 10 else 8 if app_bud >= 8 else 4
    n_app_att = max(1, app_bud // mpa)

    vsq_tot = n_vsq    * 2
    sa_tot  = n_sa_att * 4
    la_tot  = n_la_att * 6
    app_tot = n_app_att * mpa
    leftover = partB - (vsq_tot + sa_tot + la_tot + app_tot)
    if leftover >= 2:
        extra_vsq = leftover // 2
        n_vsq   += extra_vsq
        vsq_tot += extra_vsq * 2
    actual_partB = vsq_tot + sa_tot + la_tot + app_tot

    n_sa_given  = n_sa_att + 2
    n_la_given  = n_la_att + 2
    n_app_given = n_app_att + 1

    return dict(
        m=m, partA=actual_partA, partB=actual_partB,
        total=actual_partA + actual_partB, small=False,
        n_mcq=n_mcq, n_fill=n_fill, n_match=n_match,
        n_vsq=n_vsq, vsq_total=vsq_tot,
        n_sa_given=n_sa_given, n_sa_att=n_sa_att, sa_total=sa_tot, marks_sa=4,
        n_la_given=n_la_given, n_la_att=n_la_att, la_total=la_tot,
        n_app_given=n_app_given, n_app_att=n_app_att, app_total=app_tot, marks_per_app=mpa,
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
# BOARD EXAM PROMPT  (AP / Telangana SSC — scales to any mark total)
# ─────────────────────────────────────────────────────────────────────
def _prompt_board(subject, chap, board, cls, m, diff, notation, teacher):
    s    = _compute_structure(m)
    time = _time_for_marks(m)
    mw   = "pair" if s['n_match'] == 1 else "pairs"

    # ── Common header instructions printed on real AP/TS papers ────────
    instr = (
        "GENERAL INSTRUCTIONS:\n"
        "1. Answer all questions under Part A on the question paper itself. Attach it to the answer booklet.\n"
        "2. Read instructions carefully. Answer only the required number of questions in each section.\n"
        "3. Figures to the right indicate marks allotted to each question.\n"
        "4. Draw neat, labelled diagrams wherever necessary.\n"
        "5. In case of any ambiguity, the English version shall be treated as final.\n"
    )

    if s.get('small'):
        # ── Small paper (< 40M) ───────────────────────────────────────
        struct = (
            f"PART A — OBJECTIVE  ({s['partA']} Marks)\n"
            f"  Section I   — MCQ: {s['n_mcq']} questions × 1 mark  =  {s['n_mcq']} marks\n"
            f"  Section II  — Fill in the Blank: {s['n_fill']} questions × 1 mark  =  {s['n_fill']} marks\n"
            f"  Section III — Match the Following: {s['n_match']} {mw}  =  {s['n_match']} marks\n"
            f"  PART A TOTAL = {s['partA']} marks\n\n"
            f"PART B — WRITTEN  ({s['partB']} Marks)\n"
            f"  Section IV — Very Short Answer: {s['n_vsq']} questions × 2 marks = {s['vsq_total']} marks  [ALL compulsory]\n"
            f"  Section V  — Short Answer: {s['n_sa_given']} questions × 2 marks = {s['sa_total']} marks  [ALL compulsory]\n"
            f"  PART B TOTAL = {s['partB']} marks\n\n"
            f"  ★ GRAND TOTAL = {m} marks  ★"
        )
    else:
        # ── Full paper (≥ 40M) ────────────────────────────────────────
        struct = (
            f"PART A — OBJECTIVE  ({s['partA']} Marks)\n"
            f"  Section I   — MCQ: {s['n_mcq']} questions × 1 mark  =  {s['n_mcq']} marks\n"
            f"  Section II  — Fill in the Blank: {s['n_fill']} questions × 1 mark  =  {s['n_fill']} marks\n"
            f"  Section III — Match the Following: {s['n_match']} {mw}  =  {s['n_match']} marks\n"
            f"  PART A TOTAL = {s['partA']} marks\n\n"
            f"PART B — WRITTEN  ({s['partB']} Marks)\n"
            f"  Section IV  — Very Short Answer: {s['n_vsq']} questions × 2 marks = {s['vsq_total']} marks  [ALL compulsory]\n"
            f"  Section V   — Short Answer: Give {s['n_sa_given']} questions, attempt any {s['n_sa_att']} × 4 marks = {s['sa_total']} marks\n"
            f"  Section VI  — Long Answer: Give {s['n_la_given']} questions, attempt any {s['n_la_att']} × 6 marks = {s['la_total']} marks  [each must have an OR alternative]\n"
            f"  Section VII — Application / Problem: Give {s['n_app_given']} questions, attempt any {s['n_app_att']} × {s['marks_per_app']} marks = {s['app_total']} marks\n"
            f"  PART B TOTAL = {s['partB']} marks\n\n"
            f"  ★ GRAND TOTAL = {m} marks  ★"
        )

    return f"""You are a senior {board} Class {cls} question-paper setter with 20 years of experience.
Generate a complete, board-accurate, ready-to-print examination paper followed immediately by its answer key.
{teacher}
━━━ PAPER METADATA ━━━
Subject  : {subject}
Chapter  : {chap}
Board    : {board}
Class    : {cls}
Total    : {m} marks
Time     : {time}
Difficulty: {diff}

━━━ MANDATORY STRUCTURE — follow exactly, do NOT deviate ━━━
{struct}

━━━ CONTENT QUALITY RULES ━━━
1. Every question MUST be strictly about "{chap}" — no questions outside this scope.
2. MCQ options (A)(B)(C)(D): wrong options must reflect real student misconceptions, not random guesses.
3. Fill-in-the-blank: blank marked as __________ (ten underscores). One blank per sentence.
4. Match the Following: pipe table with header row | Group A | Group B | and exactly {s['n_match']} data rows.
5. Every Section VI Long Answer question MUST have an alternate "OR" question on a different sub-topic.
6. Application / problem questions: multi-step, realistic contexts, no plug-and-chug.
7. End every question with its mark allocation in square brackets: [1 Mark], [2 Marks], [4 Marks], [6 Marks], [{s.get('marks_per_app',10)} Marks].

━━━ {notation.upper().split(chr(10))[0]} ━━━
{notation}

━━━ ANSWER KEY RULES ━━━
After writing ALL questions, print exactly this line by itself:
ANSWER KEY
Then provide:
• Section I: Q1.(A)  Q2.(C)  … (all MCQ answers on one line per question)
• Section II: numbered fill-blank answers
• Section III: matching pairs table
• Sections IV–VII: full worked solution for every question, showing all steps.
  — For calculations: show every algebraic step on its own line.
  — For explanations: use numbered sub-points.
  — For diagrams: repeat [DIAGRAM: …] tag and describe key labels.

━━━ OUTPUT FORMAT ━━━
Start the paper immediately with the header below (no preamble, no "Sure!", no AI commentary):

{subject}
{board}  |  Class {cls}  |  Total Marks: {m}  |  Time: {time}

{instr}
PART A — OBJECTIVE  ({s['partA']} Marks)
(Answer on this sheet. Submit this sheet after completing Part A.)

Section I — Multiple Choice Questions  [1 Mark each]
"""


# ─────────────────────────────────────────────────────────────────────
# COMPETITIVE EXAM PROMPT
# ─────────────────────────────────────────────────────────────────────
def _prompt_competitive(exam, subject, chap, cls, m, diff, notation, teacher):
    exam_u = (exam or "").upper().strip()
    subj_l = (subject or "").lower()
    time   = _time_for_marks(m)

    # ── NTSE ─────────────────────────────────────────────────────────
    if exam_u == "NTSE":
        is_mat = any(k in subj_l for k in ["mat", "mental", "reasoning", "ability"])
        if is_mat:
            return f"""You are a NTSE exam paper setter. Generate a complete NTSE MAT (Mental Ability Test) practice paper for Class {cls}.
{teacher}
━━━ PAPER METADATA ━━━
Exam     : NTSE — MAT (Mental Ability Test)
Class    : {cls}
Total    : 100 questions × 1 mark = 100 marks
Time     : 2 Hours
Marking  : Stage 1: +1/0   Stage 2: +1/−⅓
Difficulty: {diff}

━━━ MANDATORY STRUCTURE (100 questions, 1 mark each) ━━━
Q1–12   : Verbal Analogy (12 questions)
Q13–22  : Number & Letter Series (10 questions)
Q23–32  : Non-Verbal Analogy — describe the visual pattern in words (10 questions)
Q33–40  : Coding-Decoding (8 questions)
Q41–46  : Blood Relations (6 questions)
Q47–52  : Direction & Distance (6 questions)
Q53–58  : Ranking & Arrangement (6 questions)
Q59–64  : Clock & Calendar (6 questions)
Q65–70  : Venn Diagrams (6 questions)
Q71–76  : Mirror/Water Image — describe image in words (6 questions)
Q77–82  : Odd One Out / Classification (6 questions)
Q83–88  : Pattern Completion — describe pattern in words (6 questions)
Q89–94  : Mathematical Operations (6 questions)
Q95–100 : Mixed / Analytical Reasoning (6 questions)

━━━ CONTENT QUALITY RULES ━━━
{diff}
1. Every question must test pure reasoning, NOT subject knowledge.
2. Non-verbal questions: describe figures using letters, numbers, shapes — no actual images needed.
3. Wrong options must be answers you'd get with a specific common error in reasoning.
4. Questions should be solvable in ≤90 seconds each.

━━━ ANSWER KEY ━━━
After ALL 100 questions, print:
ANSWER KEY
List: Q1.(B)  Q2.(D)  Q3.(A)  … (10 per line)
Then explain the reasoning for Q1–Q20 fully (one paragraph each).

━━━ OUTPUT ━━━
Start immediately — no preamble:

NTSE — Mental Ability Test (MAT) Practice Paper
Class: {cls}   Total Marks: 100   Time: 2 Hours   Marking: Stage 1 (+1/0)

General Instructions:
1. All questions are compulsory.
2. Each question carries 1 mark. No negative marking at Stage 1.
3. Choose the most appropriate option from (A), (B), (C), (D).
4. Time allowed: 2 Hours.

Q1–Q12  —  Verbal Analogy  [1 Mark each]
"""
        # SAT
        return f"""You are a NTSE SAT exam paper setter. Generate a complete NTSE SAT (Scholastic Aptitude Test) practice paper for Class {cls}.
{teacher}
━━━ PAPER METADATA ━━━
Exam     : NTSE — SAT (Scholastic Aptitude Test)
Topic    : {chap}
Class    : {cls}
Total    : 100 questions × 1 mark = 100 marks
Time     : 2 Hours
Marking  : Stage 1: +1/0   Stage 2: +1/−⅓
Difficulty: {diff}

━━━ MANDATORY STRUCTURE (100 questions) ━━━
Science (Q1–Q40):
  Physics    Q1–Q14  (14 questions)
  Chemistry  Q15–Q27 (13 questions)
  Biology    Q28–Q40 (13 questions)
Social Science (Q41–Q80):
  History    Q41–Q54 (14 questions)
  Geography  Q55–Q66 (12 questions)
  Civics     Q67–Q73  (7 questions)
  Economics  Q74–Q80  (7 questions)
Mathematics (Q81–Q100):
  Class {cls} topics  (20 questions)

━━━ CONTENT QUALITY RULES ━━━
{diff}
1. Questions must test NCERT Class {cls} syllabus — concept-based, not textbook definitions.
2. All Science questions require application of concepts, not mere recall.
3. Mathematics questions: multi-step problems only.
4. Social Science: causality, comparison, map-skills — not pure dates/names.

{notation}

━━━ ANSWER KEY ━━━
After ALL 100 questions, print:
ANSWER KEY
List all 100: Q1.(B) Q2.(D) … (10 per line)
Then give full step-by-step solutions for Q81–Q100 (Maths).

━━━ OUTPUT ━━━
Start immediately — no preamble:

NTSE — Scholastic Aptitude Test (SAT) Practice Paper
Class: {cls}   Total Marks: 100   Time: 2 Hours   Topic: {chap}

General Instructions:
1. All questions carry 1 mark. No negative marking at Stage 1.
2. Choose the most appropriate answer from (A), (B), (C), (D).

Science — Physics  (Q1–Q14)  [1 Mark each]
"""

    # ── NSO ──────────────────────────────────────────────────────────
    if exam_u == "NSO":
        return f"""You are an NSO (National Science Olympiad — SOF) paper setter. Generate a complete NSO practice paper for Class {cls}.
{teacher}
━━━ PAPER METADATA ━━━
Exam     : NSO — National Science Olympiad (SOF)
Topic    : {chap}
Class    : {cls}
Total    : 60 marks
Time     : 1 Hour
Marking  : No negative marking
Difficulty: {diff}

━━━ MANDATORY STRUCTURE ━━━
Section 1 — Logical Reasoning     : Q1–Q10    (10 questions × 1 mark = 10 marks)
Section 2 — Science                : Q11–Q45   (35 questions × 1 mark = 35 marks)
Section 3 — Achiever's Section     : Q46–Q50   (5 questions × 3 marks = 15 marks)
TOTAL = 60 marks ✓

━━━ CONTENT QUALITY RULES ━━━
{diff}
Section 1: Pure logical reasoning — no science knowledge needed.
Section 2: Class {cls} Science (topic: {chap}) — apply concepts, not recall definitions.
Section 3 (Achiever's): Extremely challenging HOT questions. Each requires 3+ reasoning steps.
  Wrong options must be answers obtained by a specific error in logic.

{notation}

━━━ ANSWER KEY ━━━
After ALL 50 questions, print:
ANSWER KEY
Q1.(B) Q2.(D) … (10 per line, all 50)
Then for Section 3 (Q46–Q50): give full explanations including why the best wrong option is wrong.

━━━ OUTPUT ━━━
Start immediately:

NSO Practice Paper — Class {cls}
Topic: {chap}   Total Marks: 60   Time: 1 Hour   No Negative Marking

Instructions:
1. Section 3 questions carry 3 marks each. Sections 1 and 2 carry 1 mark each.
2. No negative marking.

Section 1 — Logical Reasoning  [Q1–Q10 | 1 Mark each]
"""

    # ── IMO ──────────────────────────────────────────────────────────
    if exam_u == "IMO":
        return f"""You are an IMO (International Mathematics Olympiad — SOF) paper setter. Generate a complete IMO practice paper for Class {cls}.
{teacher}
━━━ PAPER METADATA ━━━
Exam     : IMO — International Mathematics Olympiad (SOF)
Topic    : {chap}
Class    : {cls}
Total    : 60 marks
Time     : 1 Hour
Marking  : No negative marking
Difficulty: {diff}

━━━ MANDATORY STRUCTURE ━━━
Section 1 — Logical Reasoning       : Q1–Q10   (10 × 1 mark = 10 marks)
Section 2 — Mathematical Reasoning  : Q11–Q35  (25 × 1 mark = 25 marks)
Section 3 — Everyday Mathematics    : Q36–Q45  (10 × 1 mark = 10 marks)
Section 4 — Achiever's Section      : Q46–Q50  (5 × 3 marks = 15 marks)
TOTAL = 60 marks ✓

━━━ CONTENT QUALITY RULES ━━━
{diff}
Section 1: Pure logical reasoning — no maths knowledge needed.
Section 2: Class {cls} Mathematics (topic: {chap}) — problem-solving, NOT formula application.
Section 3: Real-world maths application — percentages, ratios, measurements, data interpretation.
Section 4 (Achiever's): Competition-level. Each question must require insight or a non-obvious approach.
  Wrong options must be answers from common algebraic errors or overlooked constraints.

{notation}

━━━ ANSWER KEY ━━━
After ALL 50 questions, print:
ANSWER KEY
Q1.(B) Q2.(D) … (10 per line, all 50)
Then for Section 4 (Q46–Q50): full step-by-step solutions showing the key insight.

━━━ OUTPUT ━━━
Start immediately:

IMO Practice Paper — Class {cls}
Topic: {chap}   Total Marks: 60   Time: 1 Hour   No Negative Marking

Instructions:
1. Section 4 questions carry 3 marks each. Sections 1–3 carry 1 mark each.
2. No negative marking.

Section 1 — Logical Reasoning  [Q1–Q10 | 1 Mark each]
"""

    # ── IJSO ─────────────────────────────────────────────────────────
    if exam_u == "IJSO":
        return f"""You are an IJSO/NSEJS paper setter. Generate a complete IJSO Stage 1 (NSEJS) practice paper for Class {cls}.
{teacher}
━━━ PAPER METADATA ━━━
Exam     : IJSO / NSEJS Stage 1 — Integrated Science
Topic    : {chap}
Class    : {cls}
Total    : 80 questions
Marking  : +3 correct / −1 wrong / 0 skipped
Max Score: 240 marks
Time     : 2 Hours
Difficulty: {diff}

━━━ MANDATORY STRUCTURE ━━━
Physics   : Q1–Q27   (27 questions)
Chemistry : Q28–Q54  (27 questions)
Biology   : Q55–Q80  (26 questions)
TOTAL = 80 questions ✓

━━━ CONTENT QUALITY RULES ━━━
{diff}
1. Every question requires genuine conceptual understanding — pure recall questions are forbidden.
2. Each wrong option must represent a specific named misconception or a calculation error.
3. Questions must be suitable for Class 10 students appearing for NSEJS.
4. Physics: mechanics, optics, electricity, heat. Chemistry: reactions, solutions, periodic table, acids/bases. Biology: cell biology, genetics, ecology, physiology.
5. At least 30% of questions should involve numerical calculation.
6. Multi-concept questions (crossing subject boundaries) allowed in Physics and Chemistry.

{notation}

━━━ ANSWER KEY ━━━
After ALL 80 questions, print:
ANSWER KEY
List: Q1.(B) Q2.(C) … (10 per line, all 80)
Then for each question give: (i) correct answer with one-sentence justification, (ii) why the most tempting wrong option is wrong.

━━━ OUTPUT ━━━
Start immediately:

IJSO / NSEJS Stage 1 Practice Paper
Class: {cls}   Topic: {chap}   Total: 80 Questions   Marking: +3/−1/0   Time: 2 Hours

Instructions:
1. Each correct answer = +3 marks. Incorrect answer = −1 mark. No response = 0 marks.
2. Choose the single best answer from (A), (B), (C), (D).

Physics  (Q1–Q27)  [+3/−1 each]
"""

    # ── Fallback for unknown competitive exam ─────────────────────────
    return _prompt_board(subject or "General", chap, exam_u or "Competitive", cls, m, diff, notation, teacher)




# SPLIT PAPER / KEY
# ═══════════════════════════════════════════════════════════════════════
def split_key(text):
    for pat in [r'\nANSWER KEY\n', r'\n---\s*ANSWER KEY\s*---\n',
                r'(?i)\nANSWER KEY:?\s*\n']:
        parts = re.split(pat, text, maxsplit=1)
        if len(parts) == 2:
            return parts[0].strip(), parts[1].strip()
    return text.strip(), ""


# ═══════════════════════════════════════════════════════════════════════
# AI DIAGRAM GENERATION (SVG via Gemini)
# ═══════════════════════════════════════════════════════════════════════

# Subject-specific diagram prompt templates
# ═══════════════════════════════════════════════════════════════════════
# HIGH-QUALITY DIAGRAM ENGINE
# Pipeline: Gemini SVG → wkhtmltoimage PNG @ 300dpi → embed in PDF
# Falls back to pure ReportLab SVG renderer if wkhtmltoimage unavailable
# ═══════════════════════════════════════════════════════════════════════
import tempfile
# subprocess only imported lazily inside functions (not at module level)
# wkhtmltoimage not available on Vercel — always use ReportLab SVG renderer
_WKHTML_AVAILABLE = False


# ── Subject → diagram type hints ─────────────────────────────────────
_DIAG_CONTEXT = {
    # Geometry
    "tangent":      "circle geometry: external point P, two tangent lines PA and PB touching the circle at A and B, centre O, radius OA perpendicular to PA, all lengths and angles labelled",
    "secant":       "circle with a secant line intersecting at two points and a tangent from an external point, all lengths labelled",
    "circle":       "circle with centre O, radius, chord, tangent line, and relevant angles clearly labelled",
    "triangle":     "triangle with labelled vertices A B C, sides a b c, angles, altitude or median as required",
    "geometry":     "clean geometric figure with all vertices, sides, angles and relevant construction marks labelled",
    "coordinate":   "coordinate plane with clearly marked x-axis and y-axis, origin O, labelled points, plotted line or curve",
    "construction": "step-by-step geometric construction showing compass arcs (dashed), straight lines, and all labelled points",
    "pythagoras":   "right-angled triangle with the right angle marked by a small square, sides labelled a, b, and hypotenuse c",
    "similar":      "two similar triangles with corresponding sides and angles marked with tick marks and arcs",
    "mensuration":  "3D solid (cylinder/cone/sphere/frustum) drawn in perspective with all dimensions r, h, l labelled",
    # Physics
    "circuit":      "electric circuit schematic using standard symbols: battery (long/short lines), resistor (rectangle), bulb (circle-X), switch, ammeter (A in circle), voltmeter (V in circle), connecting wires",
    "ray":          "optics ray diagram: incident ray, normal (dashed), reflected or refracted ray, angles of incidence and reflection/refraction labelled with θ, lens or mirror surface",
    "lens":         "convex or concave lens diagram showing principal axis, focal points F and 2F, object arrow, image arrow, three standard rays",
    "mirror":       "concave or convex mirror diagram with principal axis, centre of curvature C, focal point F, object, image, and ray paths",
    "motion":       "velocity-time or distance-time graph with clearly labelled axes, values on axes, and the plotted line or curve",
    "force":        "free body diagram showing an object (rectangle or dot) with force arrows labelled: weight W downward, normal N upward, friction f horizontal, applied force F",
    "magnet":       "bar magnet with field lines curving from N pole to S pole, arrowheads showing direction",
    "refraction":   "glass slab or prism with incident ray, refracted ray inside the medium, emergent ray, normals (dashed) and angles i, r labelled",
    # Biology
    "cell":         "animal or plant cell (oval/rectangle outline) with organelles inside: nucleus (double circle), mitochondria, ribosomes, cell wall (plant only), vacuole, chloroplast (plant only), each labelled with leader lines",
    "heart":        "human heart cross-section showing 4 chambers: left atrium (LA), right atrium (RA), left ventricle (LV), right ventricle (RV), aorta, pulmonary artery/vein, vena cava, bicuspid and tricuspid valves, all labelled",
    "digestion":    "human digestive system: mouth → oesophagus → stomach → small intestine (duodenum, jejunum, ileum) → large intestine → rectum → anus, with liver and pancreas, all labelled",
    "neuron":       "neuron showing: dendrites (branching), cell body (circle with nucleus), axon (long line), myelin sheath (oval segments), nodes of Ranvier, synaptic knob, direction of impulse arrow",
    "eye":          "human eye cross-section: cornea, iris, pupil, lens, vitreous humour, retina, fovea, blind spot, optic nerve, ciliary muscles, all labelled",
    "reproduction": "longitudinal section of a flower showing: sepal, petal, stamen (anther + filament), carpel (stigma + style + ovary), ovules, receptacle, all labelled",
    "photosynthesis":"chloroplast structure: outer membrane, inner membrane, granum (stack of thylakoids), stroma, starch grain, labelled; with equation 6CO₂ + 6H₂O → C₆H₁₂O₆ + 6O₂ shown",
    "respiration":  "mitochondrion cross-section: outer membrane, inner membrane, cristae (folds), matrix, ATP synthase, all labelled",
    # Chemistry
    "atom":         "Bohr atomic model: nucleus (circle) labelled with protons P and neutrons N, electron shells (concentric circles) with electrons (dots) on each shell, element symbol in centre",
    "apparatus":    "laboratory glassware setup: stand with clamp holding a test tube or flask over a burner, beaker, thermometer, delivery tube, collecting jar over water trough, all labelled",
    "molecule":     "structural formula or ball-and-stick model of a simple molecule with atoms as circles and bonds as lines, atom symbols labelled",
    # Social Studies
    "map":          "outline map of India showing state boundaries, major rivers (Ganga, Yamuna, Godavari, Krishna, Brahmaputra), mountain ranges (Himalayas, Western/Eastern Ghats), and key locations as required",
}

def _get_diag_context(desc: str) -> str:
    dl = desc.lower()
    # Score by how many context keywords appear in description
    best_score, best_ctx = 0, "educational diagram for a school exam paper with all parts clearly labelled"
    for key, ctx in _DIAG_CONTEXT.items():
        if key in dl:
            score = len(key)  # longer key = more specific match
            if score > best_score:
                best_score, best_ctx = score, ctx
    return best_ctx


# ── Master SVG generation prompt ──────────────────────────────────────
def generate_diagram_svg(description: str) -> str | None:
    """
    Ask Gemini to produce a clean, accurate SVG for the given description.
    Returns the SVG string or None on failure.
    """
    ctx = _get_diag_context(description)

    prompt = f"""You are a professional technical illustrator producing diagrams for a Class 10 Indian school exam paper.

DIAGRAM TO DRAW: "{description}"
DIAGRAM TYPE: {ctx}

═══════════════════════════════════════════════════
OUTPUT RULES — follow every rule or the diagram is rejected
═══════════════════════════════════════════════════
1. Output ONLY the raw SVG code. No markdown code fences (``` or ```svg), no explanation, no comments outside SVG tags.
2. SVG must start with exactly:
   <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 320" width="500" height="320">
3. SVG must end with: </svg>
4. Background: add <rect x="0" y="0" width="500" height="320" fill="white"/> as the very first element.

VISUAL STYLE:
5. Main structural lines: stroke="#111111" stroke-width="2"
6. Secondary/dimension lines: stroke="#333333" stroke-width="1"
7. Dashed/construction lines: stroke="#555555" stroke-width="1" stroke-dasharray="5,3"
8. Arrow fill: fill="#111111"
9. Shape fills: fill="white" for closed shapes (triangles, circles, rectangles)
10. Shaded regions (if needed): fill="#e8e8e8"

LABELLING — critical for educational quality:
11. All labels: font-family="Arial, Helvetica, sans-serif" font-size="13" fill="#111111"
12. Smaller secondary labels (angle names, dimension ticks): font-size="11"
13. Place every label clearly AWAY from lines — never overlapping a line or another label
14. Use text-anchor="middle" for centred labels, "start" for left-aligned, "end" for right-aligned
15. Every important point, line, angle, and measurement MUST be labelled — this is an exam diagram
16. For angles: draw a small arc near the vertex, label it clearly (θ, α, ∠A, 60°, etc.)
17. Right angles: mark with a 6×6 square at the corner vertex

ARROWS:
18. Draw arrowheads as filled triangles: <polygon points="x1,y1 x2,y2 x3,y3" fill="#111111"/>
19. Use arrows on dimension lines (both ends) and direction-of-flow indicators

GEOMETRY ACCURACY:
20. All measurements must be geometrically consistent — if you label a length or angle, draw it accurately to scale
21. For circles: use <circle> elements. For arcs: use <path d="M... A..."/>
22. For curves and bezier paths: use smooth <path> with C or Q commands
23. Leave at least 25px padding on all four sides of the viewBox

ALLOWED ELEMENTS ONLY:
24. You may ONLY use: <svg>, <g>, <line>, <circle>, <ellipse>, <rect>, <polygon>, <polyline>, <path>, <text>, <tspan>
25. Do NOT use: <image>, <use>, <defs>, <symbol>, <clipPath>, <filter>, <foreignObject>, <marker>, <pattern>, <mask>, CSS styles, JavaScript

COMPLETENESS:
26. The diagram must be COMPLETE and SELF-CONTAINED — a student can understand it without reading anything else
27. Include all parts mentioned in the description. Do not omit any component.
28. If the description mentions specific measurements (e.g. radius 5 cm), label those measurements on the diagram

Generate the SVG now:"""

    text, _ = call_gemini(prompt)
    if not text:
        return None

    # Extract the SVG block — strip markdown fences if they crept in
    text = re.sub(r'```(?:svg|xml|html)?', '', text).strip()
    m = re.search(r'(<svg[\s\S]*?</svg>)', text, re.IGNORECASE)
    if not m:
        return None

    svg = m.group(1).strip()
    # Ensure background rect is present
    if '<rect x="0" y="0"' not in svg and "white" not in svg[:200]:
        svg = svg.replace(
            '>', '><rect x="0" y="0" width="500" height="320" fill="white"/>', 1
        )
    return svg


# ── High-quality SVG → PNG via wkhtmltoimage ──────────────────────────
def svg_to_png_bytes(svg_str: str, target_width_px: int = 900) -> bytes | None:
    """
    Render SVG to PNG at high resolution using wkhtmltoimage.
    Returns PNG bytes or None on failure.
    """
    if not _WKHTML_AVAILABLE:
        return None

    try:
        # Parse viewBox to get aspect ratio
        vb_match = re.search(r'viewBox=["\'][\d. ]+ ([\d.]+) ([\d.]+)["\']', svg_str)
        if vb_match:
            vb_w = float(vb_match.group(1))
            vb_h = float(vb_match.group(2))
        else:
            vb_w, vb_h = 500.0, 320.0

        target_height_px = int(target_width_px * vb_h / vb_w)

        # Wrap SVG in minimal HTML so wkhtmltoimage renders it cleanly
        html = f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: white; width: {target_width_px}px; height: {target_height_px}px; overflow: hidden; }}
  svg {{ display: block; width: {target_width_px}px; height: {target_height_px}px; }}
</style>
</head><body>{svg_str}</body></html>"""

        with tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w', encoding='utf-8') as f:
            f.write(html)
            htmlfile = f.name

        pngfile = htmlfile.replace('.html', '.png')

        import subprocess
        result = subprocess.run([
            'wkhtmltoimage',
            '--format', 'png',
            '--width', str(target_width_px),
            '--height', str(target_height_px),
            '--disable-smart-width',
            '--quality', '100',
            '--quiet',
            htmlfile, pngfile
        ], capture_output=True, timeout=20)

        if result.returncode == 0 and os.path.exists(pngfile):
            with open(pngfile, 'rb') as f:
                png_bytes = f.read()
            os.unlink(pngfile)
            os.unlink(htmlfile)
            return png_bytes if len(png_bytes) > 500 else None

        # Cleanup on failure
        for fp in [htmlfile, pngfile]:
            if os.path.exists(fp):
                os.unlink(fp)
        return None

    except Exception:
        return None


# ── PNG bytes → ReportLab ImageFlowable ──────────────────────────────
def png_to_rl_image(png_bytes: bytes, width_pt: float):
    """Convert PNG bytes to a ReportLab flowable Image at the given width with correct height."""
    from reportlab.platypus import Image as RLImage
    from PIL import Image as PILImage

    # Get actual PNG dimensions so we can calculate the correct height
    pil_img = PILImage.open(BytesIO(png_bytes))
    px_w, px_h = pil_img.size
    aspect = px_h / px_w if px_w > 0 else 0.64
    height_pt = width_pt * aspect

    buf = BytesIO(png_bytes)
    img = RLImage(buf, width=width_pt, height=height_pt)
    img.hAlign = 'CENTER'
    return img


# ── Master function: SVG string → best available PDF flowable ─────────
def svg_to_best_image(svg_str: str, width_pt: float = 380):
    """
    Convert an SVG string to the best available ReportLab flowable.
    Priority: wkhtmltoimage PNG (high quality) → pure ReportLab renderer (fallback)
    """
    # Try high-quality PNG path first
    target_px = int(width_pt * 2.2)  # 2.2x gives crisp output at half the size
    png_bytes = svg_to_png_bytes(svg_str, target_width_px=target_px)
    if png_bytes:
        return png_to_rl_image(png_bytes, width_pt)

    # Fallback: pure ReportLab SVG renderer
    return svg_to_rl_drawing(svg_str, width_pt)


# ── Pure-Python SVG → ReportLab Drawing (fallback renderer) ───────────
def _svg_color(val, default=(0, 0, 0)):
    if not val or val in ('none', 'transparent', ''):
        return None
    val = val.strip()
    named = {
        'black': (0,0,0), 'white': (1,1,1), 'red': (1,0,0), 'blue': (0,0,1),
        'green': (0,.5,0), 'grey': (.5,.5,.5), 'gray': (.5,.5,.5),
        'lightgrey': (.83,.83,.83), 'lightgray': (.83,.83,.83),
        'darkgray': (.33,.33,.33), 'darkgrey': (.33,.33,.33),
        '#111111': (.067,.067,.067), '#333333': (.2,.2,.2),
        '#555555': (.333,.333,.333), '#888888': (.533,.533,.533),
        '#e8e8e8': (.91,.91,.91), '#f5f5f5': (.961,.961,.961),
        '#f0f0f0': (.941,.941,.941), '#ffffff': (1,1,1), '#000000': (0,0,0),
    }
    if val.lower() in named:
        return named[val.lower()]
    if val.startswith('#'):
        h = val[1:]
        if len(h) == 3: h = h[0]*2 + h[1]*2 + h[2]*2
        if len(h) == 6:
            try: return (int(h[0:2],16)/255, int(h[2:4],16)/255, int(h[4:6],16)/255)
            except Exception: pass
    if val.startswith('rgb('):
        nums = re.findall(r'\d+', val)
        if len(nums) >= 3: return (int(nums[0])/255, int(nums[1])/255, int(nums[2])/255)
    return default


def _parse_points(pts_str):
    nums = re.findall(r'[-+]?\d*\.?\d+', pts_str)
    return [(float(nums[i]), float(nums[i+1])) for i in range(0, len(nums)-1, 2)]


def _parse_style(style_str):
    result = {}
    for part in (style_str or '').split(';'):
        if ':' in part:
            k, v = part.split(':', 1)
            result[k.strip()] = v.strip()
    return result


def _parse_path_d(d, scale_x, height_pt):
    import math

    def tx(x): return float(x) * scale_x
    def ty(y): return height_pt - float(y) * scale_x

    tokens = re.findall(
        r'[MmLlHhVvZzAaCcQqSsTt]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', d)

    paths = []
    cur_pts = []
    cur_x, cur_y = 0.0, 0.0
    start_x, start_y = 0.0, 0.0
    cmd = 'M'
    i = 0

    def consume(n):
        nonlocal i
        vals = []
        for _ in range(n):
            while i < len(tokens) and re.match(r'[A-Za-z]', tokens[i]):
                break
            if i < len(tokens):
                vals.append(float(tokens[i])); i += 1
        return vals

    while i < len(tokens):
        t = tokens[i]
        if re.match(r'[A-Za-z]', t):
            cmd = t; i += 1; continue

        if cmd in 'Mm':
            v = consume(2)
            if len(v) < 2: continue
            if cmd == 'm': cur_x += v[0]; cur_y += v[1]
            else: cur_x, cur_y = v[0], v[1]
            start_x, start_y = cur_x, cur_y
            if cur_pts: paths.append((cur_pts, False))
            cur_pts = [(tx(cur_x), ty(cur_y))]
            cmd = 'l' if cmd == 'm' else 'L'

        elif cmd in 'Ll':
            v = consume(2)
            if len(v) < 2: continue
            if cmd == 'l': cur_x += v[0]; cur_y += v[1]
            else: cur_x, cur_y = v[0], v[1]
            cur_pts.append((tx(cur_x), ty(cur_y)))

        elif cmd in 'Hh':
            v = consume(1)
            if not v: continue
            if cmd == 'h': cur_x += v[0]
            else: cur_x = v[0]
            cur_pts.append((tx(cur_x), ty(cur_y)))

        elif cmd in 'Vv':
            v = consume(1)
            if not v: continue
            if cmd == 'v': cur_y += v[0]
            else: cur_y = v[0]
            cur_pts.append((tx(cur_x), ty(cur_y)))

        elif cmd in 'Zz':
            if cur_pts: cur_pts.append((tx(start_x), ty(start_y)))
            paths.append((cur_pts, True))
            cur_pts = []
            cur_x, cur_y = start_x, start_y

        elif cmd in 'Aa':
            v = consume(7)
            if len(v) < 7: continue
            rx_a, ry_a, x_rot, laf, sf, ex, ey = v
            if cmd == 'a': ex += cur_x; ey += cur_y
            try:
                x_rot_r = math.radians(x_rot)
                cos_r, sin_r = math.cos(x_rot_r), math.sin(x_rot_r)
                dx2, dy2 = (cur_x - ex) / 2, (cur_y - ey) / 2
                x1p = cos_r*dx2 + sin_r*dy2
                y1p = -sin_r*dx2 + cos_r*dy2
                laf, sf = int(laf), int(sf)
                rx_a, ry_a = abs(rx_a), abs(ry_a)
                if rx_a > 0 and ry_a > 0:
                    sq = max(0, (rx_a*ry_a)**2 - (rx_a*y1p)**2 - (ry_a*x1p)**2)
                    dq = (rx_a*y1p)**2 + (ry_a*x1p)**2
                    c = math.sqrt(sq / dq) if dq > 0 else 0
                    if laf == sf: c = -c
                    cxp = c * rx_a * y1p / ry_a
                    cyp = -c * ry_a * x1p / rx_a
                    cxc = cos_r*cxp - sin_r*cyp + (cur_x+ex)/2
                    cyc = sin_r*cxp + cos_r*cyp + (cur_y+ey)/2
                    ang1 = math.atan2((y1p - cyp) / ry_a, (x1p - cxp) / rx_a)
                    ang2 = math.atan2((-y1p - cyp) / ry_a, (-x1p - cxp) / rx_a)
                    if sf == 0 and ang2 > ang1: ang2 -= 2*math.pi
                    if sf == 1 and ang2 < ang1: ang2 += 2*math.pi
                    steps = max(12, int(abs(ang2 - ang1) * max(rx_a, ry_a) * scale_x / 3))
                    for k in range(steps + 1):
                        a = ang1 + (ang2 - ang1) * k / steps
                        px = cxc + rx_a*math.cos(a)*cos_r - ry_a*math.sin(a)*sin_r
                        py = cyc + rx_a*math.cos(a)*sin_r + ry_a*math.sin(a)*cos_r
                        cur_pts.append((tx(px), ty(py)))
                else:
                    cur_pts.append((tx(ex), ty(ey)))
            except Exception:
                cur_pts.append((tx(ex), ty(ey)))
            cur_x, cur_y = ex, ey

        elif cmd in 'CcQqSsTt':
            # Approximate bezier curves by sampling 8 intermediate points
            import math
            n_params = {'C':6,'c':6,'Q':4,'q':4,'S':4,'s':4,'T':2,'t':2}
            n = n_params.get(cmd.upper(), 2)
            v = consume(n)
            if len(v) < 2: continue
            # For cubic bezier, sample the curve
            if cmd.upper() == 'C' and len(v) == 6:
                bx0, by0 = cur_x, cur_y
                if cmd == 'c':
                    bx1,by1 = cur_x+v[0],cur_y+v[1]
                    bx2,by2 = cur_x+v[2],cur_y+v[3]
                    bx3,by3 = cur_x+v[4],cur_y+v[5]
                else:
                    bx1,by1 = v[0],v[1]
                    bx2,by2 = v[2],v[3]
                    bx3,by3 = v[4],v[5]
                for k in range(1, 9):
                    t_ = k / 8
                    s_ = 1 - t_
                    bx = s_**3*bx0 + 3*s_**2*t_*bx1 + 3*s_*t_**2*bx2 + t_**3*bx3
                    by = s_**3*by0 + 3*s_**2*t_*by1 + 3*s_*t_**2*by2 + t_**3*by3
                    cur_pts.append((tx(bx), ty(by)))
                cur_x, cur_y = bx3, by3
            else:
                if cmd.islower(): cur_x += v[-2]; cur_y += v[-1]
                else: cur_x, cur_y = v[-2], v[-1]
                cur_pts.append((tx(cur_x), ty(cur_y)))
        else:
            i += 1

    if cur_pts:
        paths.append((cur_pts, False))
    return paths


def svg_to_rl_drawing(svg_str: str, width_pt: float = 380):
    """Pure ReportLab SVG renderer — fallback when wkhtmltoimage unavailable."""
    from reportlab.graphics.shapes import Drawing, Line, Circle, Rect, Polygon, PolyLine, String, Group
    from reportlab.lib.colors import Color
    import math

    try:
        clean = re.sub(r'<(/?)[\w]+:', r'<\1', svg_str)
        clean = re.sub(r'\s[\w]+:[\w-]+="[^"]*"', '', clean)
        clean = re.sub(r'&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[\da-fA-F]+);)', '&amp;', clean)

        root = ET.fromstring(clean)

        vb = root.get('viewBox', '0 0 500 320')
        vb_parts = [float(x) for x in re.findall(r'[-\d.]+', vb)]
        svg_w = vb_parts[2] if len(vb_parts) >= 3 else float(root.get('width', 500) or 500)
        svg_h = vb_parts[3] if len(vb_parts) >= 4 else float(root.get('height', 320) or 320)
        if svg_w <= 0: svg_w = 500
        if svg_h <= 0: svg_h = 320

        scale_x = width_pt / svg_w
        height_pt = svg_h * scale_x
        drawing = Drawing(width_pt, height_pt)

        def tx(x): return float(x) * scale_x
        def ty(y): return height_pt - float(y) * scale_x

        def make_color(val, default_rgb=(0, 0, 0)):
            if val in (None, 'none', 'transparent', ''): return None
            rgb = _svg_color(val, default_rgb)
            return Color(rgb[0], rgb[1], rgb[2]) if rgb else None

        def parse_sw(val):
            try: return max(0.3, float(re.findall(r'[\d.]+', str(val))[0]) * scale_x)
            except Exception: return 1.0

        NS = '{http://www.w3.org/2000/svg}'

        def _inh(el, attr, ps, default):
            style = _parse_style(el.get('style', ''))
            css = attr.replace('_', '-')
            if css in style: return style[css]
            v = el.get(attr)
            if v is not None: return v
            if attr in ps: return ps[attr]
            return default

        def render_el(el, group, ps=None):
            if ps is None: ps = {}
            tag = el.tag.replace(NS, '').lower()

            my_stroke = _inh(el, 'stroke', ps, '#111111')
            my_fill   = _inh(el, 'fill',   ps, 'none')
            sw_raw    = _inh(el, 'stroke-width', ps, '1.5')
            sw        = parse_sw(sw_raw)
            dash_raw  = _inh(el, 'stroke-dasharray', ps, None)

            stroke_c = make_color(my_stroke)
            fill_c   = make_color(my_fill)

            cs = dict(ps)
            cs.update({'stroke': my_stroke, 'fill': my_fill, 'stroke-width': sw_raw})
            if dash_raw: cs['stroke-dasharray'] = dash_raw

            def set_dash(shape):
                if dash_raw:
                    try:
                        dp = [float(v)*scale_x for v in re.findall(r'[\d.]+', dash_raw)]
                        shape.strokeDashArray = dp
                    except Exception: pass

            if tag == 'line':
                shape = Line(tx(el.get('x1','0')), ty(el.get('y1','0')),
                             tx(el.get('x2','0')), ty(el.get('y2','0')))
                shape.strokeColor = stroke_c or Color(0,0,0)
                shape.strokeWidth = sw
                set_dash(shape)
                group.add(shape)

            elif tag == 'circle':
                shape = Circle(tx(el.get('cx','0')), ty(el.get('cy','0')),
                               float(el.get('r','5')) * scale_x)
                shape.fillColor   = fill_c or Color(1,1,1)
                shape.strokeColor = stroke_c or Color(0,0,0)
                shape.strokeWidth = sw
                group.add(shape)

            elif tag == 'ellipse':
                cx = tx(el.get('cx','0')); cy = ty(el.get('cy','0'))
                rx = float(el.get('rx','10')) * scale_x
                ry = float(el.get('ry','10')) * scale_x
                pts = []
                for k in range(37):
                    a = 2 * math.pi * k / 36
                    pts += [cx + rx*math.cos(a), cy + ry*math.sin(a)]
                shape = Polygon(pts)
                shape.fillColor   = fill_c or Color(1,1,1)
                shape.strokeColor = stroke_c or Color(0,0,0)
                shape.strokeWidth = sw
                group.add(shape)

            elif tag == 'rect':
                x_  = float(el.get('x','0')); y_  = float(el.get('y','0'))
                rw  = float(el.get('width','10')); rh = float(el.get('height','10'))
                shape = Rect(tx(x_), ty(y_+rh), rw*scale_x, rh*scale_x)
                shape.fillColor   = fill_c or Color(1,1,1)
                shape.strokeColor = stroke_c or Color(0,0,0)
                shape.strokeWidth = sw
                group.add(shape)

            elif tag in ('polygon','polyline'):
                pairs = _parse_points(el.get('points',''))
                if len(pairs) >= 2:
                    pts = []
                    for (px, py) in pairs: pts += [tx(px), ty(py)]
                    shape = Polygon(pts) if tag=='polygon' else PolyLine(pts)
                    if tag == 'polygon': shape.fillColor = fill_c or Color(1,1,1)
                    shape.strokeColor = stroke_c or Color(0,0,0)
                    shape.strokeWidth = sw
                    set_dash(shape)
                    group.add(shape)

            elif tag == 'path':
                d = el.get('d','')
                if not d.strip(): return
                for (pts, closed) in _parse_path_d(d, scale_x, height_pt):
                    if len(pts) < 2: continue
                    flat = [c for pt in pts for c in pt]
                    if closed and fill_c:
                        shape = Polygon(flat)
                        shape.fillColor   = fill_c
                        shape.strokeColor = stroke_c or Color(0,0,0)
                        shape.strokeWidth = sw
                    else:
                        shape = PolyLine(flat)
                        shape.strokeColor = stroke_c or Color(0,0,0)
                        shape.strokeWidth = sw
                        set_dash(shape)
                    group.add(shape)

            elif tag == 'text':
                raw_x = float(el.get('x','0')); raw_y = float(el.get('y','0'))
                anchor = el.get('text-anchor', _parse_style(el.get('style','')).get('text-anchor','start'))
                fs_raw = _inh(el, 'font-size', ps, '13')
                try: fs = max(6, float(re.findall(r'[\d.]+', str(fs_raw))[0]) * scale_x)
                except Exception: fs = 11 * scale_x

                parts_text = []
                if el.text and el.text.strip():
                    parts_text.append((raw_x, raw_y, el.text.strip()))
                for tspan in el:
                    if tspan.tag.replace(NS,'').lower() == 'tspan':
                        tx_ = float(tspan.get('x', raw_x))
                        ty_ = float(tspan.get('y', raw_y))
                        if tspan.text and tspan.text.strip():
                            parts_text.append((tx_, ty_, tspan.text.strip()))
                if not parts_text:
                    all_txt = ''.join(el.itertext()).strip()
                    if all_txt: parts_text.append((raw_x, raw_y, all_txt))

                fc  = make_color(_inh(el,'fill',ps,'#111111')) or Color(0,0,0)
                bold = 'bold' in (_inh(el,'font-weight',ps,'')+_parse_style(el.get('style','')).get('font-weight',''))
                font_name = 'Helvetica-Bold' if bold else 'Helvetica'

                for (px, py, txt) in parts_text:
                    x_pos = tx(px); y_pos = ty(py) - fs * 0.15
                    if anchor == 'middle': x_pos -= len(txt) * fs * 0.27
                    elif anchor == 'end':  x_pos -= len(txt) * fs * 0.53
                    s = String(x_pos, y_pos, txt)
                    s.fontSize = fs; s.fillColor = fc; s.fontName = font_name
                    group.add(s)

            elif tag == 'g':
                sub = Group()
                for child in el: render_el(child, sub, cs)
                group.add(sub)

        top = Group()
        for child in root: render_el(child, top, {})
        drawing.add(top)
        return drawing

    except Exception:
        return None


# Keep old name as alias for backward compat
def svg_to_rl_image(svg_str: str, width_pt: float = 380):
    return svg_to_best_image(svg_str, width_pt)




# ═══════════════════════════════════════════════════════════════════════
# FLASK ROUTES
# ═══════════════════════════════════════════════════════════════════════
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    import traceback as _tb
    data = {}
    try:
        data             = request.get_json(force=True) or {}
        class_name       = (data.get("class") or "").strip()
        subject          = (data.get("subject") or "").strip()
        chapter          = (data.get("chapter") or "").strip()
        marks            = (data.get("marks") or "100").strip()
        difficulty       = (data.get("difficulty") or "Medium").strip()
        state            = (data.get("state") or "").strip()
        competitive_exam = (data.get("competitiveExam") or "").strip()
        exam_type        = (data.get("examType") or "").strip()
        suggestions      = (data.get("suggestions") or "").strip()

        if exam_type == "state-board" and state:
            board = f"{state} State Board"
        elif exam_type == "competitive" and competitive_exam:
            board = competitive_exam
        else:
            board = (data.get("board") or "AP State Board").strip()

        if not subject and (data.get("scope") == "all" or data.get("all_chapters")):
            subject = "Mixed Subjects"

        use_fallback = str(data.get("use_fallback", "false")).lower() in ("true", "1", "yes")

        # Build and capture the prompt (for debugging)
        prompt = data.get("prompt") or build_prompt(
            class_name, subject, chapter, board, exam_type, difficulty, marks, suggestions)

        generated_text = None
        api_error      = None
        model_used     = None

        if not use_fallback:
            generated_text, api_error = call_gemini(prompt)
            # Detect which model responded (injected by call_gemini if we track it)
            model_used = getattr(call_gemini, "_last_model_used", None)

        if not generated_text:
            if use_fallback or not GEMINI_KEY:
                generated_text = build_local_paper(class_name, subject, chapter, marks, difficulty)
                use_fallback = True
            else:
                # ── Send failure email ────────────────────────────────
                user_choices = _capture_user_choices(data)
                user_choices["board_resolved"] = board
                send_error_email(
                    error_type   = "AI Generation Failed — No Output",
                    error_msg    = api_error or "Gemini returned empty response after all retries.",
                    user_choices = user_choices,
                    extra_context = {
                        "gemini_key_set": bool(GEMINI_KEY),
                        "langchain_available": LANGCHAIN_AVAILABLE,
                        "models_tried": str(_GEMINI_MODELS),
                        "prompt_length_chars": len(prompt),
                        "prompt_preview_100chars": prompt[:100],
                    },
                )
                return jsonify({
                    "success": False,
                    "error": "AI generation failed. The developer has been notified.",
                    "api_error": api_error,
                    "suggestion": "Send use_fallback=true for a template paper.",
                }), 502

        paper, key = split_key(generated_text)
        return jsonify({
            "success": True, "paper": paper, "answer_key": key,
            "api_error": api_error, "used_fallback": use_fallback,
            "board": board, "subject": subject, "chapter": chapter,
        })

    except Exception as e:
        tb_str = _tb.format_exc()
        # ── Send crash email ──────────────────────────────────────────
        send_error_email(
            error_type    = "Unhandled Exception in /generate",
            error_msg     = str(e),
            traceback_str = tb_str,
            user_choices  = _capture_user_choices(data),
            extra_context = {
                "endpoint": "/generate",
                "gemini_key_set": bool(GEMINI_KEY),
                "langchain_available": LANGCHAIN_AVAILABLE,
            },
        )
        return jsonify({"success": False, "error": str(e), "trace": tb_str}), 500


@app.route("/download-pdf", methods=["POST"])
def download_pdf():
    try:
        data        = request.get_json(force=True) or {}
        paper_text  = data.get("paper", "")
        answer_key  = data.get("answer_key", "")
        subject     = (data.get("subject") or "Question Paper").strip()
        chapter     = (data.get("chapter") or "").strip()
        board       = (data.get("board") or "").strip()
        include_key = str(data.get("includeKey", "false")).lower() == "true"
        marks       = data.get("marks") or ""

        if not paper_text.strip():
            return jsonify({"success": False, "error": "No paper text provided"}), 400

        diagrams = {}
        if GEMINI_KEY and GENAI_AVAILABLE:
            # Collect diagram descriptions from both paper and answer key
            full_text = paper_text + "\n" + (answer_key or "")
            diag_descs = re.findall(
                r'\[DIAGRAM:\s*([^\]]+)\]|\[draw\s+([^\]]+)\]',
                full_text, re.IGNORECASE)
            unique_descs = []
            seen = set()
            for d1, d2 in diag_descs:
                desc = (d1 or d2).strip()
                if desc and desc not in seen:
                    seen.add(desc)
                    unique_descs.append(desc)

            # Generate all diagrams in parallel for speed
            if unique_descs:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                with ThreadPoolExecutor(max_workers=min(4, len(unique_descs))) as ex:
                    futures = {ex.submit(generate_diagram_svg, d): d for d in unique_descs}
                    for future in as_completed(futures):
                        desc = futures[future]
                        try:
                            svg = future.result(timeout=30)
                            if svg:
                                diagrams[desc] = svg
                        except Exception:
                            pass

        pdf_bytes = create_exam_pdf(
            paper_text, subject, chapter,
            board=board, answer_key=answer_key,
            include_key=include_key, diagrams=diagrams,
            marks=marks)

        parts    = [p for p in [board, subject, chapter] if p]
        filename = ("_".join(parts) + ".pdf").replace(" ", "_").replace("/", "-")
        return send_file(BytesIO(pdf_bytes), as_attachment=True,
                         download_name=filename, mimetype="application/pdf")
    except Exception as e:
        import traceback as _tb2
        tb_str = _tb2.format_exc()
        send_error_email(
            error_type    = "PDF Generation / Download Failed",
            error_msg     = str(e),
            traceback_str = tb_str,
            user_choices  = {
                "subject":      data.get("subject", "—"),
                "chapter":      data.get("chapter", "—"),
                "board":        data.get("board", "—"),
                "marks":        data.get("marks", "—"),
                "include_key":  data.get("includeKey", False),
                "paper_length": len(data.get("paper", "")),
                "key_length":   len(data.get("answer_key", "")),
            },
            extra_context = {
                "endpoint": "/download-pdf",
                "diagrams_found": len(re.findall(
                    r"\[DIAGRAM:", data.get("paper","") + data.get("answer_key","")
                )),
            },
        )
        return jsonify({"success": False, "error": str(e), "trace": tb_str}), 500


@app.route("/health")
def health():
    configured = bool(GEMINI_KEY and GENAI_AVAILABLE)
    models     = discover_models() if configured else []
    return jsonify({"status": "ok",
                    "gemini": "configured" if configured else "not configured",
                    "models_available": models})


@app.route("/chapters")
def chapters():
    try:
        data_path = _DATA_DIR / "curriculum.json"
        if not data_path.exists():
            return jsonify({"success": False, "error": "curriculum.json not found"})
        with open(data_path, encoding="utf-8") as f:
            curriculum = json.load(f)
        cls = request.args.get("class") or request.args.get("cls")
        if cls and cls in curriculum:
            return jsonify({"success": True, "data": curriculum[cls]})
        return jsonify({"success": True, "data": curriculum})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False)