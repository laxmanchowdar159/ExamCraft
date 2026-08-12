"""
core/pdf_engine.py
Renders a finished paper (question text + optional answer key +
diagram SVGs) into a print-ready A4 PDF using ReportLab. This is
pure CPU-bound layout work — no network calls — so it is fast and
deterministic; it is not where the old 3-minute latency came from.
"""
import os
import re
from io import BytesIO

from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY, TA_RIGHT
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.units import mm

from core.fonts import _f, register_fonts
from core.svg_render import svg_to_best_image


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
    # ── AI hallucination patterns that leak into paper text ───────
    r'|Note\s*:\s*(Draw|Sketch|Label|Students\s+(are|should|must|can))'
    r'|\[Students\s+(are|should)\s+(expected|required|asked)'
    r'|Draw\s+the\s+following\s+diagram'
    r'|See\s+figure\s+(below|above|given|provided)'
    r'|As\s+shown\s+(in\s+the\s+figure|above|below)'
    r'|Refer\s+to\s+the\s+(diagram|figure)\s+(given|above|below|provided)'
    r'|\(Diagram\s+(not\s+shown|provided|given|here)\)'
    r'|Draw\s+a\s+(neat|labelled|clean)\s+diagram'
    r'|Draw\s+and\s+label'
    r'|Sketch\s+the\s+following'
    r'|Label\s+the\s+following\s+(diagram|figure|parts)'
    r'|Using\s+a\s+ruler\s+and\s+compass'
    r'|With\s+the\s+help\s+of\s+a\s+(diagram|figure|graph|chart)'
    r'|Students\s+must\s+(draw|sketch|label|include)'
    r'|\([\s]*[Dd]raw\s+(here|in\s+the\s+space|neat\s+diagram|it)[\s]*\)'
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
    # Trim trailing closing remarks — but only clear AI filler, never real content
    # Walk backwards max 5 lines (not 10) to avoid eating real content
    end_idx = len(lines)
    for i in range(len(lines) - 1, max(len(lines) - 5, 0) - 1, -1):
        s = lines[i].strip()
        if not s:
            continue  # skip blank lines, don't use them to shrink end_idx
        elif _closing_pat.match(s):
            end_idx = i  # only cut at actual closing phrases
        else:
            break  # hit real content — stop trimming
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
                drawing = svg_to_best_image(diagrams[desc], width_pt=PW * 0.55)
            if drawing is None:
                # Stopwords excluded from overlap — only meaningful content words count
                _STOP = {'a','an','the','with','and','or','of','in','on','at','to',
                         'for','from','by','is','are','all','its','their','this',
                         'that','showing','labelled','labeled','drawn','diagram',
                         'figure','here','above','below','see','given','draw'}
                desc_words = set(re.findall(r'\w+', desc.lower())) - _STOP
                best_key, best_score = None, 0
                for dk, dv in diagrams.items():
                    if not dv:
                        continue
                    dk_words = set(re.findall(r'\w+', dk.lower())) - _STOP
                    overlap = len(desc_words & dk_words)
                    # Score must be at least 3 meaningful-word overlap AND
                    # at least 40% of the shorter description's words must match
                    # to prevent wrong-diagram substitution
                    min_words = min(len(desc_words), len(dk_words))
                    if min_words > 0 and overlap >= 3 and overlap / min_words >= 0.55:
                        if overlap > best_score:
                            best_score, best_key = overlap, dk
                if best_key:
                    drawing = svg_to_best_image(diagrams[best_key], width_pt=PW * 0.55)

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
                # Strip any nested [DIAGRAM:...] tags inside the description
                desc = re.sub(r'\[DIAGRAM:[^\]]*\]', '', desc, flags=re.I).strip()
                # Strip prompt-injection attempts: truncate if too long
                desc = re.sub(r'[\x00-\x1f]', ' ', desc)[:300].strip()
                if desc:
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


