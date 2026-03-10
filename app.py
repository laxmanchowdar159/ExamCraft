import os
import re
import json
import time
import base64
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

# ═══════════════════════════════════════════════════════════════════════
# SECURITY HEADERS — applied to every response
# Denies all device permissions (camera, mic, geolocation, etc.)
# Prevents clickjacking, MIME-sniffing, XSS injection, and iframe embedding
# ═══════════════════════════════════════════════════════════════════════
@app.after_request
def apply_security_headers(response):
    # Content-Security-Policy — allow only known safe sources
    # - Scripts: self + trusted CDNs (GSAP, Chart.js, Lenis, Google Fonts)
    # - Styles: self + Google Fonts
    # - Fonts: self + Google Fonts
    # - Connect: self only (all API calls go to our own server)
    # - No eval(), no inline event handlers via unsafe-eval
    # - No object/embed/frame/worker from anywhere
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' "
        "https://cdnjs.cloudflare.com "
        "https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' "
        "https://fonts.googleapis.com; "
        "font-src 'self' "
        "https://fonts.gstatic.com; "
        "connect-src 'self'; "
        "img-src 'self' data:; "
        "media-src 'none'; "
        "object-src 'none'; "
        "frame-src 'none'; "
        "frame-ancestors 'none'; "
        "worker-src 'none'; "
        "manifest-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self';"
    )
    response.headers["Content-Security-Policy"] = csp

    # Permissions Policy — explicitly deny every device API
    # This is the key header that prevents any prompt for camera/mic/location
    permissions = (
        "camera=(), "
        "microphone=(), "
        "geolocation=(), "
        "gyroscope=(), "
        "accelerometer=(), "
        "magnetometer=(), "
        "usb=(), "
        "midi=(), "
        "payment=(), "
        "fullscreen=(self), "
        "picture-in-picture=(), "
        "display-capture=(), "
        "screen-wake-lock=(), "
        "web-share=(), "
        "clipboard-read=(), "
        "clipboard-write=(self), "
        "ambient-light-sensor=(), "
        "battery=(), "
        "bluetooth=(), "
        "serial=(), "
        "nfc=(), "
        "hid=()"
    )
    response.headers["Permissions-Policy"] = permissions

    # Anti-clickjacking — page cannot be embedded in any iframe
    response.headers["X-Frame-Options"]           = "DENY"
    # Prevent MIME-type sniffing attacks
    response.headers["X-Content-Type-Options"]    = "nosniff"
    # Enable XSS filter in older browsers
    response.headers["X-XSS-Protection"]          = "1; mode=block"
    # Only send referrer to same origin
    response.headers["Referrer-Policy"]           = "strict-origin-when-cross-origin"
    # Force HTTPS in production (ignored on HTTP dev servers)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # Remove server fingerprint
    response.headers.pop("Server", None)
    response.headers["X-Powered-By"] = "ExamCraft"

    return response

GEMINI_KEY   = os.environ.get("GEMINI_API_KEY",   "").strip()
GEMINI_KEY_2 = os.environ.get("GEMINI_API_KEY_2", "").strip()
GEMINI_KEY_3 = os.environ.get("GEMINI_API_KEY_3", "").strip()

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
        "include_answer_key": True,  # always generate key; PDF inclusion controlled separately
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
    r'\setminus':'∖',
    # Relations
    r'\leq':'≤', r'\geq':'≥', r'\le':'≤', r'\ge':'≥',
    r'\neq':'≠', r'\ne':'≠', r'\approx':'≈',
    r'\equiv':'≡', r'\sim':'∼', r'\simeq':'≃', r'\propto':'∝',
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
    r'\perp':'⊥', r'\parallel':'∥',
    r'\triangle':'△', r'\square':'□',
    r'\cong':'≅', r'\ncong':'≇',
    # Common
    r'\degree':'°', r'\circ':'°',
    r'\therefore':'∴', r'\because':'∵',
    r'\prime':'′', r'\doubleprime':'″',
    r'\%':'%', r'\$':'$', r'\#':'#',
    # Trig (ensure they pass through cleanly)
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
    # Brackets (remove commands, let chars through)
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

    # Guard: move fill-in-blank underscores out of $…$ so _latex_to_rl
    # never converts them to empty <sub> tags.
    # Replace $…________…$ patterns: pull blanks outside the math span.
    def _fix_blank_in_math(m):
        inner = m.group(1)
        # If the math span contains only underscores / spaces, return plain blanks
        if re.match(r'^[_\s]+$', inner):
            return '__________'
        # Replace underscore runs inside math with a placeholder word
        inner = re.sub(r'_{2,}', 'blank', inner)
        return f'${inner}$'
    text = re.sub(r'\$([^$\n]+)\$', _fix_blank_in_math, text)

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
            p = re.sub(r'>', '&gt;', p)
            safe.append(p)

    out = ''.join(safe)
    # Strip empty sub/super tags that would otherwise render as visible noise
    out = re.sub(r'<sub></sub>', '', out)
    out = re.sub(r'<super></super>', '', out)
    out = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', out)
    out = re.sub(r'\*(.+?)\*',     r'<i>\1</i>', out)
    # Balance any unclosed/mismatched XML tags to prevent ReportLab Paragraph crashes
    out = _balance_xml_tags(out)
    return out


def _balance_xml_tags(text: str) -> str:
    """Ensure all ReportLab-supported inline tags are properly balanced.
    Closes unclosed tags and strips unknown tags that would cause parse errors."""
    _RL_INLINE = {'b', 'i', 'u', 'sub', 'super', 'font'}
    stack = []
    result = []
    pos = 0
    tag_re = re.compile(r'<(/?)([a-zA-Z][a-zA-Z0-9]*)((?:\s[^>]*)?)(/?)>', re.S)
    for m in tag_re.finditer(text):
        # Append text before this tag
        result.append(text[pos:m.start()])
        pos = m.end()
        closing, tagname, attrs, self_close = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if tagname not in _RL_INLINE:
            # Unknown tag — strip it (already escaped to &lt; by _process, but just in case)
            continue
        if self_close or tagname in ('br',):
            result.append(m.group(0))
            continue
        if not closing:
            stack.append(tagname)
            result.append(f'<{tagname}{attrs}>')
        else:
            if tagname in stack:
                # Close all tags opened after this one, then close it, then reopen them
                tail = []
                while stack and stack[-1] != tagname:
                    t = stack.pop()
                    result.append(f'</{t}>')
                    tail.append(t)
                if stack:
                    stack.pop()
                    result.append(f'</{tagname}>')
                for t in reversed(tail):
                    stack.append(t)
                    result.append(f'<{t}>')
            # else: stray close tag — ignore
    result.append(text[pos:])
    # Close any remaining open tags
    for t in reversed(stack):
        result.append(f'</{t}>')
    return ''.join(result)


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
    S("PTitle",    fontName=B, fontSize=12, textColor=white,
      alignment=TA_CENTER, leading=17, spaceAfter=0, spaceBefore=0)
    S("PSubtitle", fontName=R, fontSize=8.5, textColor=HexColor("#d0e4f7"),
      alignment=TA_CENTER, leading=12, spaceAfter=0)
    S("PMeta",     fontName=R, fontSize=8.5, textColor=C_GREY,
      alignment=TA_LEFT, leading=12, spaceAfter=0)
    S("PMetaR",    fontName=R, fontSize=8.5, textColor=C_GREY,
      alignment=TA_RIGHT, leading=12, spaceAfter=0)
    S("PMetaC",    fontName=R, fontSize=8.5, textColor=C_BODY,
      alignment=TA_CENTER, leading=12, spaceAfter=0)
    S("PMetaBold", fontName=B, fontSize=8.5, textColor=C_NAVY,
      alignment=TA_CENTER, leading=12, spaceAfter=0)

    # ── Section banners ───────────────────────────────────────────────
    S("SecBanner", fontName=B, fontSize=9.5, textColor=C_NAVY,
      leading=13, spaceAfter=0, spaceBefore=0)
    S("SecBannerKey", fontName=B, fontSize=10, textColor=white,
      alignment=TA_CENTER, leading=14, spaceAfter=0, spaceBefore=0)

    # ── Instructions ──────────────────────────────────────────────────
    S("InstrHead", fontName=B, fontSize=8.5, textColor=C_NAVY,
      leading=12, spaceAfter=2, spaceBefore=3)
    S("Instr",     fontName=R, fontSize=8.5, textColor=C_BODY,
      leading=12, spaceAfter=1, leftIndent=16, firstLineIndent=-16)

    # ── Question text ─────────────────────────────────────────────────
    S("Q",    fontName=R, fontSize=9.5, textColor=C_STEEL,
      alignment=TA_JUSTIFY, leading=14, spaceBefore=5, spaceAfter=1,
      leftIndent=22, firstLineIndent=-22)
    S("QCont",fontName=R, fontSize=9.5, textColor=C_STEEL,
      alignment=TA_JUSTIFY, leading=14, spaceBefore=1, spaceAfter=1, leftIndent=22)
    S("QSub", fontName=R, fontSize=9.5, textColor=C_STEEL,
      alignment=TA_JUSTIFY, leading=14, spaceBefore=2, spaceAfter=1,
      leftIndent=34, firstLineIndent=-12)
    S("Opt",  fontName=R, fontSize=9, textColor=C_BODY,
      leading=13, spaceAfter=1, leftIndent=0)

    # ── Answer key ────────────────────────────────────────────────────
    S("KTitle",fontName=B, fontSize=12, textColor=white,
      alignment=TA_CENTER, leading=17, spaceAfter=0, spaceBefore=0)
    S("KSec",  fontName=B, fontSize=9.5, textColor=C_NAVY,
      leading=13, spaceAfter=1, spaceBefore=5)
    S("KQ",    fontName=B, fontSize=9.5, textColor=C_NAVY,
      leading=13, spaceAfter=1, spaceBefore=4, leftIndent=22, firstLineIndent=-22)
    S("KStep", fontName=R, fontSize=9.5, textColor=C_KSTEP,
      leading=14, spaceAfter=1, leftIndent=22)
    S("KSub",  fontName=R, fontSize=9.5, textColor=C_BODY,
      leading=14, spaceAfter=1, leftIndent=32, firstLineIndent=-11)
    S("KMath", fontName=I, fontSize=9.5, textColor=C_BODY,
      leading=14, spaceAfter=1, leftIndent=28)

    # ── Diagram label ─────────────────────────────────────────────────
    S("DiagLabel", fontName=I, fontSize=9, textColor=C_GREY,
      leading=12, spaceAfter=2, spaceBefore=2)

    # ── Section inline instruction note ───────────────────────────────
    S("InstrNote", fontName=I, fontSize=8.5, textColor=C_GREY,
      leading=12, spaceAfter=3, spaceBefore=0, leftIndent=6)

    return base
def _safe_para(text: str, style, fallback_style=None):
    """Build a Paragraph, falling back to plain-text if XML parsing fails."""
    from reportlab.platypus import Paragraph as _Para
    try:
        return _Para(text, style)
    except Exception:
        # Strip all tags and retry
        plain = re.sub(r'<[^>]+>', '', text).replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        try:
            plain_escaped = plain.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            return _Para(plain_escaped, fallback_style or style)
        except Exception:
            return None  # Skip this line entirely


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
        canvas.drawCentredString((LM + RM) / 2, 10, f"Page  {doc.page}")

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

    # Left accent bar (6pt wide strip)
    accent = Table([[""]], colWidths=[6])
    accent.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), C_ACCENT),
        ("TOPPADDING",    (0,0),(-1,-1), 0),
        ("BOTTOMPADDING", (0,0),(-1,-1), 0),
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
    ]))

    row = Table([[accent, p]], colWidths=[6, pw - 6])
    row.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), bg),
        ("LINEBELOW",     (0,0),(-1,-1), 0.6, line_c),
        ("LINETOP",       (0,0),(-1,-1), 0.6, line_c),
        # Accent column (col 0): zero padding so the 6pt column isn't squeezed
        ("LEFTPADDING",   (0,0),(0,-1),  0),
        ("RIGHTPADDING",  (0,0),(0,-1),  0),
        ("TOPPADDING",    (0,0),(0,-1),  0),
        ("BOTTOMPADDING", (0,0),(0,-1),  0),
        # Text column (col 1): comfortable padding
        ("LEFTPADDING",   (1,0),(1,-1),  10),
        ("RIGHTPADDING",  (1,0),(1,-1),  10),
        ("TOPPADDING",    (1,0),(1,-1),  5),
        ("BOTTOMPADDING", (1,0),(1,-1),  5),
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
    """Render a markdown pipe-table as a proper ReportLab Table with borders,
    header styling, and alternating row colors — exam-quality output."""
    if not rows:
        return None
    mc = max(len(r) for r in rows)
    if mc < 1:
        return None
    norm = [r + [''] * (mc - len(r)) for r in rows]

    R, B = _f("Reg"), _f("Bold")

    # ── Cell paragraph styles (no leftIndent — avoids negative-width crash) ──
    hdr_sty = ParagraphStyle(
        name="_tbl_hdr",
        fontName=B, fontSize=9.5, leading=14,
        textColor=white, alignment=TA_CENTER,
        spaceBefore=0, spaceAfter=0,
        firstLineIndent=0, leftIndent=0, rightIndent=0,
    )
    odd_sty = ParagraphStyle(
        name="_tbl_odd",
        fontName=R, fontSize=9.5, leading=14,
        textColor=C_STEEL, alignment=TA_CENTER,
        spaceBefore=0, spaceAfter=0,
        firstLineIndent=0, leftIndent=0, rightIndent=0,
    )
    even_sty = ParagraphStyle(
        name="_tbl_even",
        fontName=R, fontSize=9.5, leading=14,
        textColor=C_STEEL, alignment=TA_CENTER,
        spaceBefore=0, spaceAfter=0,
        firstLineIndent=0, leftIndent=0, rightIndent=0,
    )

    # Distribute columns evenly across page width
    col_w = pw / mc

    table_data = []
    for ri, row in enumerate(norm):
        is_hdr = (ri == 0)
        sty = hdr_sty if is_hdr else (odd_sty if ri % 2 == 1 else even_sty)
        cells = [Paragraph(_process(cell.strip()), sty) for cell in row]
        table_data.append(cells)

    tbl = Table(table_data, colWidths=[col_w] * mc, repeatRows=1)

    # Build TableStyle commands
    ts_cmds = [
        # Outer border — navy
        ("BOX",           (0, 0), (-1, -1), 1.0, C_NAVY),
        # Horizontal lines between all rows
        ("LINEBELOW",     (0, 0), (-1, -1), 0.5, C_LGREY),
        # Vertical lines between columns
        ("LINEBEFORE",    (1, 0), (-1, -1), 0.5, C_LGREY),
        # Padding
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        # Header row — navy background, heavier bottom border
        ("BACKGROUND",    (0, 0), (-1, 0),  C_NAVY),
        ("LINEBELOW",     (0, 0), (-1, 0),  1.2, C_ACCENT),
    ]

    # Alternating row backgrounds for data rows
    for ri in range(1, len(table_data)):
        bg = HexColor("#f4f6fb") if ri % 2 == 0 else white
        ts_cmds.append(("BACKGROUND", (0, ri), (-1, ri), bg))

    tbl.setStyle(TableStyle(ts_cmds))

    # Wrap in KeepTogether so short tables don't straddle pages awkwardly
    if len(table_data) <= 15:
        return KeepTogether([Spacer(1, 4), tbl, Spacer(1, 6)])
    return [Spacer(1, 4), tbl, Spacer(1, 6)]


# ═══════════════════════════════════════════════════════════════════════
# LINE-TYPE DETECTORS
# ═══════════════════════════════════════════════════════════════════════
def _is_sec_hdr(s):
    s = s.strip()
    # PART A/B/C/D or SECTION A/B/C/D (single letter)
    if re.match(r'^(SECTION|Section|PART|Part)\s+[A-Da-d](\s|[-:—]|$)', s):
        return True
    # Section I / II / III / IV / V / VI / VII (Roman numerals)
    if re.match(r'^(SECTION|Section)\s+(I{1,3}|IV|V?I{0,3}|IX|XI{0,3}|X)(\s|[-:—]|$)', s):
        return True
    # Section 1 / 2 / 3 etc. (Arabic numerals)
    if re.match(r'^(SECTION|Section)\s+\d+(\s|[-:—]|$)', s):
        return True
    return bool(re.match(r'^(GENERAL INSTRUCTIONS|General Instructions'
                         r'|Instructions|Note:|NOTE:)\s*$', s))

def _is_table_row(s):
    s = s.strip()
    # Standard table row: starts with |
    if '|' in s and s.startswith('|'):
        return True
    # Markdown separator row without leading pipe: :---... or ---...
    # These must be caught as table rows so _is_divider can skip them
    if re.match(r'^[:\-]{3}[-|:\s]*$', s) and len(s) >= 3:
        return True
    return False

def _is_divider(s):
    s = s.strip()
    # Standard: |---|---|
    if re.match(r'^\|[\s\-:|]+\|', s):
        return True
    # Separator without leading pipe: :---... or ---... (AI sometimes omits leading |)
    if re.match(r'^[:\-]{3}[-|:\s]*$', s) and len(s) >= 3:
        return True
    return False

def _is_hrule(s):
    s = s.strip()
    return len(s) > 3 and all(c in '-=_' for c in s)

_HDR_SKIP = re.compile(
    # "Subject: Mathematics" / "Total Marks: 100" key-colon form
    r'^(School|Subject|Class|Board|Total\s*Marks|Time\s*(?:Allowed)?|Date)\s*[:/]'
    # Bare subject name on its own line  e.g. "Mathematics" / "Social Studies"
    r'|^(Mathematics|Science|Physics|Chemistry|Biology|Social\s+Studies?'
    r'|English|Hindi|Telugu|Sanskrit|Computer\s*Science|EVS|General\s+Science'
    r'|Environmental\s+Science)\s*$'
    # Pipe-formatted header row  "Andhra Pradesh | Class 10 | Total Marks: 100 | Time: 3 hrs"
    r'|\|\s*Class\s+\d'
    r'|\|\s*Total\s+Marks\s*:'
    # Standalone time/marks/board header lines the AI emits at the top
    r'|^Time\s*:\s*\d'
    r'|^Total\s+Marks\s*:\s*\d'
    r'|^Marks\s*:\s*\d'
    r'|^(Andhra\s+Pradesh|Telangana)\s+State\s+Board'
    # "Andhra Pradesh State Board · Class 10   Total Marks: 100" combined meta line
    r'|^Andhra\s+Pradesh.*State\s+Board'
    r'|^Telangana.*State\s+Board',
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

# Descriptions that mean "no diagram needed" — suppress box and label entirely
_NO_DIAG = re.compile(
    r'^(not\s+applicable|none|n\s*/?\s*a|not\s+needed|no\s+diagram'
    r'|not\s+required|not\s+relevant|no\s+figure|no\s+image'
    r'|not\s+available|not\s+necessary)\s*[.\s]*$',
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
    # Patterns that mark the real start of content (stop skipping preamble)
    _real_start = re.compile(
        r'^(SECTION|PART|Q\.?\s*\d|^\d+[\.\)\]]\s|'
        r'MATHEMATICS|SCIENCE|PHYSICS|CHEMISTRY|BIOLOGY|SOCIAL|ENGLISH|HINDI|TELUGU|'
        r'Class\s+\d|Board:|Total\s+Marks)',
        re.IGNORECASE
    )
    # Bare subject-name lines and meta lines are duplicates of our rendered header — skip them
    _bare_subj = re.compile(
        r'^(Mathematics|Science|Physics|Chemistry|Biology|Social\s+Studies?'
        r'|English|Hindi|Telugu|Sanskrit|Computer\s*Science|EVS)\s*$'
        r'|\|\s*Class\s+\d|\|\s*Total\s+Marks'
        r'|^Time\s*:\s*\d|^Total\s+Marks\s*:\s*\d'
        r'|^Andhra\s+Pradesh.*Board|^Telangana.*Board',
        re.IGNORECASE
    )
    _closing_pat = re.compile(
        r'^(i hope|this completes|do you want|let me know|please let|'
        r'feel free|if you need|note that|end of paper|---\s*$)',
        re.IGNORECASE
    )
    # Find where real content starts
    start_idx = 0
    for i, ln in enumerate(lines[:25]):  # check first 25 lines for preamble
        s = ln.strip()
        if not s:
            continue
        if _preamble_pat.match(s):
            start_idx = i + 1
        elif _bare_subj.match(s):
            # Bare subject name / meta line — skip it, it duplicates our rendered header
            start_idx = i + 1
        elif _real_start.match(s):
            # If this is a bare subject name on its own, skip it too
            if _bare_subj.match(s):
                start_idx = i + 1
            else:
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


def _strip_leading_metadata(text: str, subject: str = "", board: str = "") -> str:
    """
    Strip the duplicate header block that AI emits at the top of the paper:
      e.g. bare subject name line, pipe-separated Board|Class|Marks|Time line,
    These appear BEFORE "GENERAL INSTRUCTIONS" / "PART A" / "Section"
    and duplicate info already in our PDF header table.
    """
    if not text or not text.strip():
        return text

    _META_PAT = re.compile(
        r'^('
        r'Total\s*Marks|Time\s*(Allowed|:)|Class\s*[:/]?\s*\d|'
        r'Board\s*[:/]|State\s*Board|Andhra\s*Pradesh|Telangana|'
        r'CBSE|ICSE|NTSE|NSO|IMO|IJSO|'
        r'Examination|Exam\s*Board|Duration|Max.*Marks'
        r')',
        re.I
    )
    _REAL_CONTENT = re.compile(
        r'^(GENERAL\s*INSTRUCTIONS?|PART\s+[A-Z]|SECTION\s+[IVXLC]+|'
        r'Section\s+[IVXLC]+|\d+\.\s|\(i\)|\(a\)|MCQ|OBJECTIVE|WRITTEN)',
        re.I
    )

    lines = text.split('\n')
    new_lines = []
    skipping_header = True

    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            if skipping_header:
                continue   # skip blank lines in the header block
            new_lines.append(ln)
            continue

        if skipping_header:
            # Once we see real content, stop skipping
            if _REAL_CONTENT.match(s):
                skipping_header = False
                new_lines.append(ln)
                continue

            # Skip lines that are the bare subject name
            if subject and s.strip().lower() == subject.strip().lower():
                continue
            # Skip lines that are just the board name
            if board and s.strip().lower() == board.strip().lower():
                continue
            # Skip pipe-separated metadata rows (Board | Class | Marks | Time)
            if '|' in s:
                cells = [c.strip() for c in s.split('|') if c.strip()]
                if cells and all(_META_PAT.match(c) or
                                 re.match(r'^Class\s*\d', c, re.I) or
                                 re.match(r'^\d+\s*(Marks?|Hours?|Min)', c, re.I) or
                                 re.match(r'^(Andhra|Telangana|AP|TS)', c, re.I) or
                                 re.match(r'^[A-Z][a-z]+\s+(Pradesh|Board|State)', c, re.I)
                                 for c in cells):
                    continue
            # Skip bare metadata lines (Subject / Board / Class / Time alone)
            if _META_PAT.match(s):
                continue
            # After 8 lines without finding real content, stop skipping
            if i >= 8:
                skipping_header = False
                new_lines.append(ln)
                continue
            # Otherwise: not metadata, not real content, not past 8 lines — skip
            # (catches bare subject lines like "Mathematics", "Science" etc.)
            if re.match(r'^[A-Za-z][A-Za-z\s]{1,30}$', s) and not re.search(r'[.?!,]', s):
                continue
        else:
            new_lines.append(ln)

    return '\n'.join(new_lines)



def clean_line(line):
    """Strip markdown formatting from a line."""
    line = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', line)
    line = re.sub(r'^#{1,6}\s*', '', line)
    return line.strip()


def create_exam_pdf(text, subject, chapter, board="",
                   answer_key=None, include_key=False, diagrams=None,
                   marks=None) -> bytes:
    """
    Clean, readable exam PDF using ReportLab.
    Preserves diagrams/images. Style mirrors the reference FPDF layout:
      - Bold centred title
      - Bold section headings (SECTION A / B / C / D)
      - Plain body text, justified
      - Pipe tables rendered as proper grid tables
      - Diagram placeholder boxes where AI placed [DIAGRAM:...] tags
      - Answer key on a new page if include_key=True
    """
    # ── Strip AI noise ────────────────────────────────────────────────
    text = _strip_ai_noise(text)
    if answer_key:
        answer_key = _strip_ai_noise(answer_key)

    register_fonts()
    R, B, I = _f("Reg"), _f("Bold"), _f("Ital")

    LM = BM = 17 * mm
    RM = 17 * mm
    TM = 13 * mm
    PW = A4[0] - LM - RM

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=LM, rightMargin=RM,
        topMargin=TM, bottomMargin=BM,
        title=f"{subject}{' – ' + chapter if chapter else ''}"
    )

    # ── Styles ────────────────────────────────────────────────────────
    def PS(name, font, size, bold=False, italic=False, align=TA_LEFT,
           leading=None, before=0, after=0, left=0, first=0):
        fn = B if bold else (I if italic else R)
        return ParagraphStyle(
            name=name, fontName=fn, fontSize=size,
            leading=leading or (size * 1.45),
            spaceBefore=before, spaceAfter=after,
            leftIndent=left, firstLineIndent=first,
            alignment=align, textColor=C_BODY
        )

    sTitle   = PS('Title',   R, 11, bold=True,  align=TA_CENTER, after=2)
    sMeta    = PS('Meta',    R,  8, align=TA_CENTER, after=1, before=0)
    sSecHdr  = PS('SecHdr',  R, 10, bold=True,  before=7, after=3)
    sPartHdr = PS('PartHdr', R,  9, bold=True,  before=4,  after=2)
    sInstr   = PS('Instr',   R,  8, italic=True, after=2, left=4)
    sQ       = PS('Q',       R,  9, align=TA_JUSTIFY, before=3, after=1, left=18, first=-18)
    sQCont   = PS('QCont',   R,  9, align=TA_JUSTIFY, before=1, after=1, left=18)
    sOpt     = PS('Opt',     R,  9, before=0, after=0, left=26)
    sKeyHdr  = PS('KeyHdr',  R, 11, bold=True,  align=TA_CENTER, before=4, after=3)
    sKeyQ    = PS('KeyQ',    R,  9, bold=True,  before=3, after=1, left=18, first=-18)
    sKeyStep = PS('KeyStep', R,  9, before=1,   after=1, left=18)
    sDiag    = PS('Diag',    R,  8, italic=True, before=1, after=2, left=4)
    sFooter  = PS('Footer',  R,  8, italic=True, align=TA_CENTER, before=6)
    sTableH  = ParagraphStyle('TH', fontName=B, fontSize=8,  leading=11,
                               textColor=white, alignment=TA_CENTER,
                               spaceBefore=0, spaceAfter=0, leftIndent=0)
    sTableC  = ParagraphStyle('TC', fontName=R, fontSize=8,  leading=11,
                               textColor=C_BODY, alignment=TA_CENTER,
                               spaceBefore=0, spaceAfter=0, leftIndent=0)

    elems = []

    # ── Header block ──────────────────────────────────────────────────
    title_str = f"Class 10 Model Paper  –  {subject}"
    if chapter:
        title_str += f"  –  {chapter}"
    elems.append(Paragraph(title_str, sTitle))

    meta_parts = []
    if board:          meta_parts.append(board)
    if marks:          meta_parts.append(f"Total Marks: {marks}")
    if meta_parts:
        elems.append(Paragraph("  |  ".join(meta_parts), sMeta))

    elems.append(HRFlowable(width="100%", thickness=1.2, color=C_NAVY,
                             spaceBefore=4, spaceAfter=8))

    # ── Helper: render a pipe table ───────────────────────────────────
    def render_table(rows):
        if not rows:
            return
        mc = max(len(r) for r in rows)
        norm = [r + [''] * (mc - len(r)) for r in rows]
        col_w = PW / mc
        data = []
        for ri, row in enumerate(norm):
            sty = sTableH if ri == 0 else sTableC
            data.append([Paragraph(_process(c.strip()), sty) for c in row])
        tbl = Table(data, colWidths=[col_w] * mc, repeatRows=1)
        cmds = [
            ('BOX',           (0,0),(-1,-1), 0.8, C_NAVY),
            ('LINEBELOW',     (0,0),(-1,-1), 0.4, C_LGREY),
            ('LINEBEFORE',    (1,0),(-1,-1), 0.4, C_LGREY),
            ('BACKGROUND',    (0,0),(-1,0),  C_NAVY),
            ('LINEBELOW',     (0,0),(-1,0),  1.0, C_ACCENT),
            ('TOPPADDING',    (0,0),(-1,-1), 4),
            ('BOTTOMPADDING', (0,0),(-1,-1), 4),
            ('LEFTPADDING',   (0,0),(-1,-1), 6),
            ('RIGHTPADDING',  (0,0),(-1,-1), 6),
            ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ]
        for ri in range(1, len(data)):
            bg = HexColor('#f4f6fb') if ri % 2 == 0 else white
            cmds.append(('BACKGROUND', (0,ri),(-1,ri), bg))
        tbl.setStyle(TableStyle(cmds))
        elems.append(Spacer(1, 4))
        elems.append(tbl)
        elems.append(Spacer(1, 6))

    # ── Helper: render a diagram placeholder or real SVG ─────────────
    def render_diagram(desc):
        if _NO_DIAG.match(desc):
            return
        drawing = None
        if diagrams:
            if desc in diagrams and diagrams[desc]:
                drawing = svg_to_best_image(diagrams[desc], width_pt=PW * 0.50)
            if drawing is None:
                desc_words = set(re.findall(r'\w+', desc.lower()))
                best_key, best_score = None, 0
                for dk, dv in diagrams.items():
                    if not dv:
                        continue
                    overlap = len(desc_words & set(re.findall(r'\w+', dk.lower())))
                    if overlap > best_score:
                        best_score, best_key = overlap, dk
                if best_key and best_score >= 2:
                    drawing = svg_to_best_image(diagrams[best_key], width_pt=PW * 0.50)

        elems.append(Paragraph(f'<i>Figure: {desc}</i>', sDiag))
        if drawing is not None:
            inner = Table([[drawing]], colWidths=[PW * 0.55])
            inner.setStyle(TableStyle([
                ('BOX',           (0,0),(-1,-1), 0.6, C_LGREY),
                ('BACKGROUND',    (0,0),(-1,-1), HexColor('#fafbfc')),
                ('TOPPADDING',    (0,0),(-1,-1), 6),
                ('BOTTOMPADDING', (0,0),(-1,-1), 6),
                ('LEFTPADDING',   (0,0),(-1,-1), 6),
                ('RIGHTPADDING',  (0,0),(-1,-1), 6),
                ('ALIGN',         (0,0),(-1,-1), 'CENTER'),
            ]))
            outer = Table([[inner]], colWidths=[PW])
            outer.setStyle(TableStyle([
                ('ALIGN',         (0,0),(-1,-1), 'CENTER'),
                ('TOPPADDING',    (0,0),(-1,-1), 2),
                ('BOTTOMPADDING', (0,0),(-1,-1), 4),
            ]))
            elems.append(outer)
        else:
            # Clean placeholder box
            hint = Paragraph('<i>Draw / paste diagram here</i>',
                             ParagraphStyle('_ph', fontName=I, fontSize=8,
                                            textColor=C_LGREY, alignment=TA_CENTER,
                                            leftIndent=0, firstLineIndent=0))
            ph = Table([[hint]], colWidths=[PW * 0.52])
            ph.setStyle(TableStyle([
                ('BOX',           (0,0),(-1,-1), 0.5, HexColor('#c8d5e5')),
                ('BACKGROUND',    (0,0),(-1,-1), HexColor('#f8fafc')),
                ('ROWHEIGHT',     (0,0),(-1,-1), 28 * mm - 20),
                ('TOPPADDING',    (0,0),(-1,-1), 6),
                ('BOTTOMPADDING', (0,0),(-1,-1), 6),
                ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
            ]))
            outer = Table([[ph]], colWidths=[PW])
            outer.setStyle(TableStyle([('ALIGN', (0,0),(-1,-1), 'CENTER'),
                                       ('TOPPADDING',(0,0),(-1,-1),2),
                                       ('BOTTOMPADDING',(0,0),(-1,-1),4)]))
            elems.append(outer)
        elems.append(Spacer(1, 4))

    # ── Main text renderer ────────────────────────────────────────────
    def render_block(raw_text, is_key=False):
        tbl_rows   = []
        in_table   = False
        pending_opts = []

        def flush_table():
            nonlocal tbl_rows, in_table
            if tbl_rows:
                render_table(tbl_rows)
            tbl_rows, in_table = [], False

        def flush_opts():
            nonlocal pending_opts
            if not pending_opts:
                return
            rows = []
            for k in range(0, len(pending_opts), 2):
                L = pending_opts[k]
                R_ = pending_opts[k+1] if k+1 < len(pending_opts) else ('', '')
                lp = Paragraph(f'<b>({L[0]})</b>  {L[1]}', sOpt)
                rp = Paragraph(f'<b>({R_[0]})</b>  {R_[1]}' if R_[0] else '', sOpt)
                rows.append([lp, rp])
            t = Table(rows, colWidths=[PW/2, PW/2])
            t.setStyle(TableStyle([
                ('TOPPADDING',    (0,0),(-1,-1), 1),
                ('BOTTOMPADDING', (0,0),(-1,-1), 1),
                ('LEFTPADDING',   (0,0),(-1,-1), 20),
                ('VALIGN',        (0,0),(-1,-1), 'TOP'),
            ]))
            elems.append(t)
            elems.append(Spacer(1, 3))
            pending_opts.clear()

        qS  = sKeyQ    if is_key else sQ
        ctS = sKeyStep if is_key else sQCont

        lines = raw_text.split('\n')
        i = 0
        while i < len(lines):
            raw  = lines[i].rstrip()
            line = re.sub(r'\\_', '_', re.sub(r'\\-', '-', raw))
            s    = line.strip()
            i   += 1

            # ── Table rows ───────────────────────────────────────────
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

            # ── Skip lines we always suppress ────────────────────────
            if _HDR_SKIP.match(s) or _FIG_JUNK.match(s):
                continue

            # ── Horizontal rule ──────────────────────────────────────
            if _is_hrule(line):
                flush_opts()
                elems.append(HRFlowable(width="100%", thickness=0.4,
                                        color=C_LGREY, spaceBefore=3, spaceAfter=3))
                continue

            # ── [DIAGRAM: ...] ───────────────────────────────────────
            if s.startswith('[DIAGRAM:') or s.lower().startswith('[draw'):
                flush_opts()
                desc = re.sub(r'^\[DIAGRAM:\s*', '', s, flags=re.I).rstrip(']').strip()
                render_diagram(desc)
                continue

            # ── Figure: label lines ──────────────────────────────────
            fig_m = re.match(r'^Figure\s*:\s*(.+)', s, re.I)
            if fig_m:
                flush_opts()
                elems.append(Paragraph(f'<i>Figure: {fig_m.group(1).strip()}</i>', sDiag))
                continue

            # ── Section heading: SECTION A / B / C / D ───────────────
            if re.match(r'^(SECTION|Section)\s+[A-Da-d](\s|[-:—(]|$)', s):
                flush_opts()
                elems.append(Spacer(1, 6))
                elems.append(HRFlowable(width="100%", thickness=0.6,
                                        color=C_NAVY, spaceBefore=2, spaceAfter=2))
                elems.append(Paragraph(f'<b>{s}</b>', sSecHdr))
                continue

            # ── Part heading inside section: Part I / II etc ─────────
            if re.match(r'^Part\s+(I{1,3}|IV|V?I{0,3}|[1-5])\b', s, re.I):
                flush_opts()
                elems.append(Paragraph(f'<b>{s}</b>', sPartHdr))
                continue

            # ── Parenthetical section instruction ────────────────────
            if (s.startswith('(') and
                    re.match(r'^\((?:Answer|All|Each|Attempt|Choose|Select|'
                             r'compulsory|Every|Note|Write|Questions?)\b', s, re.I)):
                flush_opts()
                elems.append(Paragraph(f'<i>{_process(s)}</i>', sInstr))
                continue

            # ── Answer Key section header ─────────────────────────────
            if is_key and re.match(r'^(Section|SECTION|Part|PART)\s+[A-Da-d]\b', s):
                flush_opts()
                elems.append(Spacer(1, 6))
                elems.append(Paragraph(f'<b>{s}</b>', sPartHdr))
                continue

            # ── MCQ options: (a) / (A) / (b) … ─────────────────────
            opt_m = re.match(r'^\s*[\(\[]\s*([a-dA-D])\s*[\)\]\.]?\s+(.+)', s)
            if opt_m and not re.match(r'^(Q\.?\s*)?\d+[\.)]\s', s):
                letter = opt_m.group(1).lower()
                val    = _process(opt_m.group(2))
                pending_opts.append((letter, val))
                if len(pending_opts) >= 4:
                    flush_opts()
                continue

            # Inline multi-option: (a) x  (b) y  (c) z  (d) w
            multi = re.findall(
                r'[\(\[]([a-dA-D])[\)\]\.]?\s+([^(\[]+?)(?=\s*[\(\[][a-dA-D][\)\]\.]|$)', s)
            if len(multi) >= 2 and not re.match(r'^(Q\.?\s*)?\d+[\.)]\s', s):
                flush_opts()
                opts = [(l.lower(), _process(v.strip())) for l, v in multi]
                rows = []
                for k in range(0, len(opts), 2):
                    L  = opts[k]
                    R_ = opts[k+1] if k+1 < len(opts) else ('','')
                    rows.append([
                        Paragraph(f'<b>({L[0]})</b>  {L[1]}', sOpt),
                        Paragraph(f'<b>({R_[0]})</b>  {R_[1]}' if R_[0] else '', sOpt)
                    ])
                t = Table(rows, colWidths=[PW/2, PW/2])
                t.setStyle(TableStyle([
                    ('TOPPADDING',(0,0),(-1,-1),1), ('BOTTOMPADDING',(0,0),(-1,-1),1),
                    ('LEFTPADDING',(0,0),(-1,-1),20), ('VALIGN',(0,0),(-1,-1),'TOP'),
                ]))
                elems.append(t)
                elems.append(Spacer(1, 3))
                continue

            # ── Numbered question: 1. / Q1. / 1) ────────────────────
            q_m = re.match(r'^(Q\.?\s*)?(\d+)[\.)]\s*(.+)', s)
            if q_m:
                flush_opts()
                qnum  = q_m.group(2)
                qbody = q_m.group(3)
                mk_m  = re.search(r'\[\s*(\d+)\s*[Mm]arks?\s*\]\s*$', qbody)
                mark_tag = ''
                if mk_m:
                    mark_tag = f'  <font color="{C_GREY.hexval()}" size="8">[{mk_m.group(1)}M]</font>'
                    qbody    = qbody[:mk_m.start()].strip()
                xml = (f'<font color="{C_STEEL.hexval()}"><b>{qnum}.</b></font>'
                       f'  {_process(qbody)}{mark_tag}')
                p = _safe_para(xml, qS)
                if p:
                    elems.append(p)
                continue

            # ── Sub-question: (a) / (i) ──────────────────────────────
            sub_m = re.match(r'^\s*[\(\[]\s*([a-z])\s*[\)]\s+(.+)', s)
            if sub_m:
                flush_opts()
                subS = PS('Sub', R,  9, before=2, after=1, left=30, first=-12)
                p = _safe_para(f'<b>({sub_m.group(1)})</b>  {_process(sub_m.group(2))}', subS)
                if p:
                    elems.append(p)
                continue

            # ── Default: plain body ──────────────────────────────────
            flush_opts()
            p = _safe_para(_process(s), ctS)
            if p:
                elems.append(p)

        flush_opts()
        if in_table:
            flush_table()

    # ── Render question paper ─────────────────────────────────────────
    text = _strip_leading_metadata(text, subject, board)
    render_block(text, is_key=False)

    # ── Footer ───────────────────────────────────────────────────────
    elems.append(Spacer(1, 8))
    elems.append(HRFlowable(width="100%", thickness=0.4, color=C_LGREY,
                             spaceBefore=2, spaceAfter=2))
    elems.append(Paragraph("— End of Question Paper —", sFooter))

    # ── Answer Key ───────────────────────────────────────────────────
    if include_key and answer_key and answer_key.strip():
        elems.append(PageBreak())
        elems.append(Paragraph(
            f'<b>ANSWER KEY  &amp;  SOLUTIONS</b>', sKeyHdr))
        elems.append(HRFlowable(width="100%", thickness=1.2, color=C_NAVY,
                                 spaceBefore=4, spaceAfter=8))
        render_block(answer_key, is_key=True)
        elems.append(Spacer(1, 8))
        elems.append(Paragraph("— End of Answer Key —", sFooter))

    # ── Page callback: thin top/bottom rules + page number ────────────
    def on_page(canvas, doc):
        W, H = A4
        lm = doc.leftMargin
        rm = W - doc.rightMargin
        canvas.saveState()
        canvas.setStrokeColor(C_NAVY)
        canvas.setLineWidth(0.8)
        canvas.line(lm, H - 9 * mm, rm, H - 9 * mm)
        canvas.setStrokeColor(HexColor('#c8d5e5'))
        canvas.setLineWidth(0.4)
        canvas.line(lm, 20, rm, 20)
        canvas.setFont(_f('Reg'), 7.5)
        canvas.setFillColor(C_GREY)
        canvas.drawCentredString((lm + rm) / 2, 9, f"Page {doc.page}")
        canvas.restoreState()

    doc.build(elems, onFirstPage=on_page, onLaterPages=on_page)
    pdf = buf.getvalue()
    buf.close()
    return pdf


_GEMINI_MODELS = [
    # Best quality with quota — try these first
    "gemini-2.5-flash",                # 8 RPM, 32 RPD on key 1
    "gemini-2.5-flash-lite",           # 6 RPM, 30 RPD on key 1
    "gemini-2.5-flash-lite-preview-06-17",  # alternate name for 2.5 flash lite

    # Gemma models — highest RPD, great fallback for structured output
    "gemma-3-4b-it",                   # 10 RPM, 60 RPD — solid quality
    "gemma-3-1b-it",                   # 16 RPM, 92 RPD — highest throughput
]
_PRIMARY_MODEL  = "gemini-2.5-flash"
_FALLBACK_MODEL = "gemma-3-4b-it"
_GEMINI_BASE     = "https://generativelanguage.googleapis.com/v1beta/models"

# LangChain chain — built lazily on first call so startup stays fast
_lc_chain        = None
_lc_chain_fb     = None  # fallback chain


def _get_lc_chain(model_name: str, api_key: str = None):
    """Build a LangChain chain for the given model."""
    key = api_key or GEMINI_KEY
    if not LANGCHAIN_AVAILABLE or not key:
        return None
    try:
        is_gemma = 'gemma' in model_name.lower()
        llm = ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=key,
            temperature=0.2,
            max_output_tokens=8192 if is_gemma else 16384,
            top_p=0.9  if is_gemma else 0.85,
            top_k=40,
            timeout=180,
            max_retries=1,  # fail fast — we have multiple models to try
        )
        system_msg = (
            "You are an expert Indian school exam paper setter with 20 years of experience. "
            "You follow instructions with military precision. "
            "Output ONLY the exam paper and answer key — no preamble, "
            "no commentary, no markdown fences. "
            "Start directly with the paper content."
        )
        # Gemma models don't support system role via ChatGoogleGenerativeAI —
        # prepend the instruction to the human message instead.
        if is_gemma:
            prompt_tpl = ChatPromptTemplate.from_messages([
                ("human", system_msg + "\n\n{prompt}"),
            ])
        else:
            prompt_tpl = ChatPromptTemplate.from_messages([
                ("system", system_msg),
                ("human", "{prompt}"),
            ])
        return prompt_tpl | llm | StrOutputParser()
    except Exception:
        return None


def discover_models():
    """Return model list for health endpoint."""
    keys = [k for k in [GEMINI_KEY, GEMINI_KEY_2, GEMINI_KEY_3] if k]
    return _GEMINI_MODELS if keys else []


def _try_one(model_name: str, api_key: str, prompt: str, all_errors: dict) -> tuple:
    """
    Try a single (model, key) combination.
    Returns (text_or_None, is_rate_limited, is_not_found).
    Tries LangChain first, falls back to plain REST.
    """
    label = f"key{[GEMINI_KEY, GEMINI_KEY_2, GEMINI_KEY_3].index(api_key) + 1 if api_key in [GEMINI_KEY, GEMINI_KEY_2, GEMINI_KEY_3] else '?'}"

    def _is_429(s): return "429" in s or "quota" in s.lower() or "RESOURCE_EXHAUSTED" in s
    def _is_404(s): return "404" in s or "NOT_FOUND" in s

    # ── LangChain attempt ─────────────────────────────────────────────
    if LANGCHAIN_AVAILABLE:
        chain = _get_lc_chain(model_name, api_key=api_key)
        if chain is not None:
            try:
                result = chain.invoke({"prompt": prompt})
                if result and result.strip():
                    return result.strip(), False, False
                all_errors[f"{model_name}({label}/lc)"] = "empty"
            except Exception as lc_err:
                err_str = str(lc_err)
                all_errors[f"{model_name}({label}/lc)"] = err_str[:100]
                if _is_404(err_str):
                    return None, False, True   # model dead on this key — skip REST too
                if _is_429(err_str):
                    return None, True, False   # quota exhausted on this key for this model

    # ── Plain REST fallback ───────────────────────────────────────────
    is_gemma = "gemma" in model_name.lower()
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature":     0.2,
            "maxOutputTokens": 8192 if is_gemma else 16384,
            "topP":            0.9  if is_gemma else 0.85,
            "topK":            40,
        },
    }
    url = f"{_GEMINI_BASE}/{model_name}:generateContent?key={api_key}"
    try:
        resp = _requests.post(url, json=payload, timeout=180)
        if resp.status_code == 200:
            data = resp.json()
            text = (data.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", "")).strip()
            if text:
                return text, False, False
            all_errors[f"{model_name}({label}/rest)"] = "empty"
            return None, False, False
        elif resp.status_code == 403:
            all_errors[f"{model_name}({label}/rest)"] = "403 forbidden"
            return None, False, False
        elif resp.status_code in (404, 400):
            all_errors[f"{model_name}({label}/rest)"] = f"HTTP {resp.status_code}"
            return None, False, True   # model not found
        elif resp.status_code == 429:
            all_errors[f"{model_name}({label}/rest)"] = "429 quota"
            return None, True, False   # rate limited
        else:
            all_errors[f"{model_name}({label}/rest)"] = f"HTTP {resp.status_code}"
            return None, False, False
    except Exception as e:
        all_errors[f"{model_name}({label}/rest)"] = f"exception:{e}"
        return None, False, False


def call_gemini(prompt: str):
    """
    Round-robin across all available API keys for each model in priority order.

    Strategy:
      For each model (best → worst quality):
        Try key1 → key2 → key3
      Move to next model only when all keys are exhausted/rate-limited for that model.

    This means:
      gemini-2.5-flash / key1  →  gemini-2.5-flash / key2  →  gemini-2.5-flash / key3
      gemini-2.5-flash-lite / key1  →  key2  →  key3
      gemma-3-4b-it / key1  →  key2  →  key3
      gemma-3-1b-it / key1  →  key2  →  key3
      ... (all models exhausted on all keys) → fallback paper

    Returns (text, error_or_None).
    """
    # Build list of active keys in order
    active_keys = [k for k in [GEMINI_KEY, GEMINI_KEY_2, GEMINI_KEY_3] if k]
    if not active_keys:
        return None, "No GEMINI_API_KEY set."

    all_errors   = {}
    # Track which (model, key_index) combos are rate-limited — don't retry them
    rate_limited = set()   # elements: (model_name, key_idx)
    not_found    = set()   # elements: model_name — 404 on any key means skip model on all keys

    for model_name in _GEMINI_MODELS:
        for ki, api_key in enumerate(active_keys):
            if model_name in not_found:
                break   # model is dead everywhere — skip all remaining keys
            if (model_name, ki) in rate_limited:
                continue  # this combo already 429'd — try next key

            print(f"[ExamCraft] Trying {model_name} / key{ki+1}…")
            text, is_rl, is_nf = _try_one(model_name, api_key, prompt, all_errors)

            if text:
                call_gemini._last_model_used = f"{model_name}/key{ki+1}"
                print(f"[ExamCraft] Success: {model_name} / key{ki+1}")
                return text, None

            if is_rl:
                rate_limited.add((model_name, ki))
                print(f"[ExamCraft] Rate-limited: {model_name} / key{ki+1} — trying next key")

            if is_nf:
                not_found.add(model_name)
                print(f"[ExamCraft] Not found: {model_name} — skipping on all keys")
                break   # no point trying other keys for a dead model

    summary = " | ".join(f"{k}={v}" for k, v in all_errors.items())
    return None, summary


# ═══════════════════════════════════════════════════════════════════════
# FALLBACK PAPER (used when Gemini is unavailable)
# ═══════════════════════════════════════════════════════════════════════
def build_local_paper(cls, subject, chapter, marks, difficulty):
    return f"""{subject or "Science"} — Model Question Paper
Subject: {subject or "Science"}   Class: {cls}
Total Marks: {marks}   Time Allowed: 3 Hours 15 Minutes

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
        "• Fill blanks: __________ (ten underscores, ALWAYS outside $…$, never inside math mode)\n"
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
    secC_note  = (
        f"Write EXACTLY {s['cC_given']} questions worth 4 marks each."
        + (f" Students will attempt any {s['cC_att']}." if s['cC_given'] > s['nC'] else " All are compulsory.")
    ) if s['nC'] > 0 else ""
    secD_note  = (
        f"Write EXACTLY {s['cD_given']} questions worth {s['dEach']} marks each."
        + (f" Students will attempt any {s['cD_att']}." if s['cD_given'] > s['nD'] else " All are compulsory.")
        + " Each Long Answer question MUST have an alternate OR question on a different sub-topic."
    ) if s['has_D'] else ""

    return f"""Create a complete model question paper for Class {cls} {subject}, {chap} chapter.
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
1. Every question MUST be strictly about "{chap}" — no questions from other chapters.
2. Question counts are EXACT — do NOT add or remove any questions.
3. Include one genuinely challenging question in each section.
4. End every question with its mark allocation in square brackets: [1 Mark], [2 Marks], [4 Marks].
5. Follow {board} syllabus strictly.
6. Output ONLY the questions and section headings. No hints in the question paper itself.
7. ⚠ DIAGRAMS — MANDATORY: For ANY geometry, circuit, graph, or figure-based question,
   place a [DIAGRAM: detailed description] tag on its own line immediately after the question.
   Examples:
     • Triangle question → [DIAGRAM: triangle ABC, altitude from A to BC, all sides and angles labelled]
     • Circuit question  → [DIAGRAM: circuit with 3Ω and 6Ω resistors in parallel, 12V battery]
   ⛔ NEVER write [DIAGRAM: Not applicable] or [DIAGRAM: None] — just omit the tag if no diagram needed.
   Include [DIAGRAM:] tags in at least 40% of Section B, C, D questions.
8. TABLES: Any question with data or comparisons — format as a pipe table (|col|col|...).
9. ⚠ DO NOT write any general instructions block at the top of the paper.

━━━ {notation.upper().split(chr(10))[0]} ━━━
{notation}

━━━ ANSWER KEY ━━━
After ALL questions are written, print this EXACT line alone on its own line:
ANSWER KEY

Then provide:
• Section A MCQs : Q1.(A)  Q2.(C)  … (one per question)
• Section A Fill : numbered answers
• Section A Match: matching pairs as a pipe table
• Sections B / C / D: full worked solutions for EVERY question.
  — Show every calculation step on a new line.
  — Diagram questions: repeat [DIAGRAM: …] with full description.

━━━ OUTPUT FORMAT ━━━
Start immediately with the paper — no preamble, no "Sure!", no commentary.
Use this EXACT layout:

SECTION A  ({s['totA']} x 1 = {s['totA']} Marks)

Part I — Multiple Choice Questions  [1 Mark each]
(Choose the correct answer from (A), (B), (C), (D).)

Part II — Fill in the Blank  [1 Mark each]
(Fill each blank with the most appropriate word or value.)

Part III — Match the Following  [1 Mark each]
(Match each item in Group A with the correct item in Group B.)

SECTION B  ({s['nB']} x 2 = {s['totB']} Marks)
(Answer all questions. Each carries 2 marks.)

{"SECTION C  (" + str(s['cC_given']) + " x 4 = " + str(s['cC_given']*4) + " Marks)" + chr(10) + "(" + ("Attempt any " + str(s['cC_att']) + " questions." if s['cC_given'] > s['nC'] else "Answer all questions.") + " Each carries 4 marks.)" if s['nC'] > 0 else ""}

{"SECTION D  (" + str(s['cD_given']) + " x " + str(s['dEach']) + " = " + str(s['cD_given']*s['dEach']) + " Marks)" + chr(10) + "(" + ("Attempt any " + str(s['cD_att']) + " questions." if s['cD_given'] > s['nD'] else "Answer all questions.") + " Each carries " + str(s['dEach']) + " marks.)" if s['has_D'] else ""}

"""


# SPLIT PAPER / KEY
# ═══════════════════════════════════════════════════════════════════════
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
def _call_gemini_for_svg(prompt: str) -> str | None:
    """
    SVG diagram generator: for each model (best→worst), try every API key.
    Queue: flash/key1 → flash/key2 → flash/key3 → flash-lite/key1 → flash-lite/key2 → ...
    Stops as soon as any combo returns a valid SVG.
    Dead models (404) are skipped for all remaining keys.
    """
    active_keys = [k for k in [GEMINI_KEY, GEMINI_KEY_2, GEMINI_KEY_3] if k]
    if not active_keys:
        return None

    models = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash-lite-preview-06-17",
        "gemma-3-4b-it",
        "gemma-3-1b-it",
    ]

    payload_base = {
        "generationConfig": {
            "temperature":     0.15,
            "maxOutputTokens": 4096,
            "topP":            0.9,
            "topK":            40,
        },
    }

    attempt = 0
    for model in models:
        model_dead = False
        for api_key in active_keys:
            attempt += 1
            payload = {**payload_base, "contents": [{"parts": [{"text": prompt}]}]}
            url = f"{_GEMINI_BASE}/{model}:generateContent?key={api_key}"
            try:
                resp = _requests.post(url, json=payload, timeout=35)
                if resp.status_code == 200:
                    text = (resp.json().get("candidates", [{}])[0]
                                      .get("content", {})
                                      .get("parts", [{}])[0]
                                      .get("text", "")).strip()
                    if text and "<svg" in text.lower():
                        print(f"[Diagram] SVG ok — attempt {attempt} ({model}/key{active_keys.index(api_key)+1})")
                        return text
                    print(f"[Diagram] attempt {attempt} ({model}): no <svg>, trying next key")
                elif resp.status_code in (429, 503):
                    print(f"[Diagram] attempt {attempt} ({model}/key{active_keys.index(api_key)+1}): rate-limited")
                elif resp.status_code in (400, 404):
                    print(f"[Diagram] attempt {attempt} ({model}): model unavailable — skipping model")
                    model_dead = True
                    break
                else:
                    print(f"[Diagram] attempt {attempt} ({model}): HTTP {resp.status_code}")
            except Exception as e:
                print(f"[Diagram] attempt {attempt} ({model}): {e}")
        if model_dead:
            continue   # all keys already skipped for this model

    print(f"[Diagram] all {attempt} attempts exhausted — no SVG")
    return None


def generate_diagram_svg(description: str) -> str | None:
    """
    Ask Gemini to produce a clean, accurate SVG for the given description.
    Returns the SVG string or None on failure.
    Uses a dedicated fast REST call (not the full call_gemini chain).
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
16. Right angles: mark with a 6x6 square at the corner vertex

ARROWS:
17. Draw arrowheads as filled triangles: <polygon points="x1,y1 x2,y2 x3,y3" fill="#111111"/>

GEOMETRY ACCURACY:
18. All measurements must be geometrically consistent
19. For circles: use <circle> elements. For arcs: use <path d="M... A..."/>
20. Leave at least 25px padding on all four sides of the viewBox

ALLOWED ELEMENTS ONLY:
21. You may ONLY use: <svg>, <g>, <line>, <circle>, <ellipse>, <rect>, <polygon>, <polyline>, <path>, <text>, <tspan>
22. Do NOT use: <image>, <use>, <defs>, <symbol>, <clipPath>, <filter>, <foreignObject>, <marker>, <pattern>, <mask>, CSS styles, JavaScript

Generate the SVG now:"""

    text = _call_gemini_for_svg(prompt)
    if not text:
        print(f"[Diagram] No response for: {description[:60]}")
        return None

    # Extract the SVG block — strip markdown fences if they crept in
    text = re.sub(r'```(?:svg|xml|html)?', '', text).strip()
    m = re.search(r'(<svg[\s\S]*?</svg>)', text, re.IGNORECASE)
    if not m:
        print(f"[Diagram] No <svg> block in response for: {description[:60]}")
        return None

    svg = m.group(1).strip()
    # Ensure background rect is present
    if '<rect x="0" y="0"' not in svg and 'fill="white"' not in svg[:300]:
        svg = svg.replace(
            '>', '><rect x="0" y="0" width="500" height="320" fill="white"/>', 1
        )
    print(f"[Diagram] Generated OK ({len(svg)} chars): {description[:60]}")
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
            # Avoid "Andhra Pradesh State Board State Board" if state already has "State Board"
            if "state board" in state.lower():
                board = state.strip()
            else:
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
                        "per_model_errors": api_error or "—",
                        "key_2_set": bool(GEMINI_KEY_2), "key_3_set": bool(GEMINI_KEY_3),
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

        # ── Build PDFs inline — no second API call needed ────────────
        # ── Diagram generation — sequential with generous per-diagram timeout ──
        # Each diagram is a separate Gemini call (~10-20s each).
        # Sequential is more reliable than parallel under tight quotas.
        diagrams = {}
        active_keys = [k for k in [GEMINI_KEY, GEMINI_KEY_2, GEMINI_KEY_3] if k]
        if active_keys:
            try:
                full_text = paper + "\n" + (key or "")
                diag_descs_raw = re.findall(
                    r'\[DIAGRAM:\s*([^\]]+)\]', full_text, re.IGNORECASE)
                unique_descs = list(dict.fromkeys(d.strip() for d in diag_descs_raw if d.strip()))
                if unique_descs:
                    from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeout
                    # Use up to 4 workers so diagrams generate in parallel but not all at once
                    max_w = max(1, min(4, len(unique_descs)))
                    with ThreadPoolExecutor(max_workers=max_w) as ex:
                        futures = {ex.submit(generate_diagram_svg, d): d for d in unique_descs}
                        # 90 seconds total wall-clock, 80 seconds per individual diagram
                        try:
                            for future in as_completed(futures, timeout=90):
                                d = futures[future]
                                try:
                                    svg = future.result(timeout=80)
                                    if svg:
                                        diagrams[d] = svg
                                        print(f"[ExamCraft] Diagram OK: {d[:60]}")
                                    else:
                                        print(f"[ExamCraft] Diagram empty: {d[:60]}")
                                except Exception as de:
                                    print(f"[ExamCraft] Diagram error ({d[:40]}): {de}")
                        except FutureTimeout:
                            print(f"[ExamCraft] Diagram wall-clock timeout — got {len(diagrams)}/{len(unique_descs)}")
            except Exception as e:
                print(f"[ExamCraft] Diagram generation outer error: {e}")

        marks_safe = str(marks or "100").strip()
        chapter_safe = chapter if chapter and chapter != "Full Syllabus" else ""

        pdf_b64 = pdf_key_b64 = None
        pdf_error_msg = None
        try:
            pdf_bytes = create_exam_pdf(
                paper, subject, chapter_safe,
                board=board, answer_key=key,
                include_key=False, diagrams=diagrams,
                marks=marks_safe)
            pdf_b64 = base64.b64encode(pdf_bytes).decode()
        except Exception as pdf_err:
            import traceback as _tb2
            pdf_error_msg = str(pdf_err)
            print(f"[PDF ERROR] create_exam_pdf failed: {pdf_error_msg}")
            print(_tb2.format_exc())
            # Try again with stripped/simplified text as fallback
            try:
                safe_paper = re.sub(r'[^\x00-\x7F\u0080-\u024F\u0370-\u03FF\u2200-\u22FF]', ' ', paper)
                pdf_bytes = create_exam_pdf(
                    safe_paper, subject, chapter_safe,
                    board=board, answer_key=None,
                    include_key=False, diagrams={},
                    marks=marks_safe)
                pdf_b64 = base64.b64encode(pdf_bytes).decode()
                pdf_error_msg = None  # Fallback succeeded
            except Exception as pdf_err2:
                pdf_b64 = None
                pdf_error_msg = f"PDF rendering failed: {pdf_err}. Fallback also failed: {pdf_err2}"

        if key and key.strip():
            try:
                pdf_key_bytes = create_exam_pdf(
                    paper, subject, chapter_safe,
                    board=board, answer_key=key,
                    include_key=True, diagrams=diagrams,
                    marks=marks_safe)
                pdf_key_b64 = base64.b64encode(pdf_key_bytes).decode()
            except Exception:
                pdf_key_b64 = None  # hide key button rather than download wrong file

        return jsonify({
            "success": True, "paper": paper, "answer_key": key,
            "api_error": api_error, "used_fallback": use_fallback,
            "board": board, "subject": subject, "chapter": chapter,
            "pdf_b64": pdf_b64,
            "pdf_key_b64": pdf_key_b64,  # null if no answer key — hides the button
            "pdf_error": pdf_error_msg,   # non-null only if PDF rendering failed
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
    return jsonify({
        "status": "ok",
        "gemini": "configured" if configured else "not configured",
        "gemini_key_2": "set" if GEMINI_KEY_2 else "not set",
        "gemini_key_3": "set" if GEMINI_KEY_3 else "not set",
        "key_strategy": "round-robin across all keys per model",
        "models_available": models,
    })


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