"""
core/svg_render.py
Turns an SVG string (produced by core/ai_diagrams.py) into something
ReportLab can drop into a PDF: either a rasterised PNG (if
wkhtmltoimage happens to be on PATH — it never is on serverless, so
this is effectively always skipped) or a pure-Python vector
re-drawing via reportlab.graphics. No network calls happen here —
this is pure CPU-bound rendering and is not part of the request's
latency budget in any meaningful way.
"""
import os
import re
import tempfile
from io import BytesIO

_WKHTML_AVAILABLE = False  # wkhtmltoimage is not present on serverless hosts


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
