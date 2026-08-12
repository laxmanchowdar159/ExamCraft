"""
core/fonts.py
DejaVu font registration for ReportLab (adds Unicode/Greek glyph
support that the built-in Helvetica lacks). Registration is
memoised — safe to call from anywhere, runs once per process.
"""
import os
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from core.config import FONT_DIR, SYS_FONT_DIR

_fonts_registered = False


def register_fonts():
    global _fonts_registered
    if _fonts_registered:
        return
    fdir  = str(FONT_DIR)
    sys_d = SYS_FONT_DIR

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

