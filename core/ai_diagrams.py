"""
core/ai_diagrams.py
Generates SVG diagrams for [DIAGRAM: ...] tags found in a paper.

Speed strategy: the old code gave diagram generation up to 90 seconds
of wall-clock time *after* the paper text was already done, on top of
whatever the text generation itself took. This version shares one
hard budget (core.config.BUDGET_DIAGRAM_SECONDS) across ALL diagrams
combined, running them concurrently — a paper with 6 diagrams doesn't
take 6x as long, it takes roughly one diagram's worth of time. Any
diagram that doesn't finish inside the budget is simply skipped (the
PDF falls back to a labelled placeholder box), which is a better
trade than blocking the whole paper for minutes.
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from core.config import ACTIVE_KEYS, GEMINI_API_BASE, BUDGET_DIAGRAM_SECONDS

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
    best_score, best_ctx = 0, "educational diagram for a Class 10 Indian school exam paper with all important parts clearly labelled and described"
    for key, ctx in _DIAG_CONTEXT.items():
        pattern = r'\b' + re.escape(key) + r'\b'
        if re.search(pattern, dl):
            score = len(key)
            if score > best_score:
                best_score, best_ctx = score, ctx
    return best_ctx


_DIAGRAM_MODEL = "gemini-2.5-flash-lite"   # fast + cheap, good enough for line-art SVG
_ATTEMPT_TIMEOUT = 15


def _build_prompt(description: str) -> str:
    ctx = _get_diag_context(description)
    return f"""You are a professional technical illustrator producing diagrams for a Class 10 Indian school exam paper.

DIAGRAM TO DRAW: "{description}"
DIAGRAM TYPE: {ctx}

Output ONLY raw SVG. No markdown fences, no explanation.
Start with exactly: <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 520" width="800" height="520">
First child must be: <rect x="0" y="0" width="800" height="520" fill="white"/>
End with: </svg>

STYLE: structural lines stroke="#111111" stroke-width="2"; dimension lines stroke="#333333" stroke-width="1";
construction lines dashed stroke="#555555" stroke-dasharray="5,3"; shape fills "white"; arrowheads as filled
<polygon> triangles fill="#111111".

LABELS: font-family="Arial, Helvetica, sans-serif" font-size="15" fill="#111111" for all labels (font-size="13" for
secondary labels). Every important point/line/angle/measurement must be labelled, placed clear of lines. Right
angles marked with a 6x6 square.

ONLY use: <svg> <g> <line> <circle> <ellipse> <rect> <polygon> <polyline> <path> <text> <tspan>.
Never use: <image> <use> <defs> <symbol> <clipPath> <filter> <foreignObject> <marker> <pattern> <mask>, CSS, JS.
Leave 25px padding on all sides. Generate the SVG now:"""


def _one_diagram_call(description: str, api_key: str):
    description = re.sub(r'\[DIAGRAM:[^\]]*\]', '', description, flags=re.IGNORECASE)
    description = re.sub(r'[\x00-\x1f\x7f]', ' ', description)
    description = re.sub(r'\s+', ' ', description).strip()[:300]
    if not description:
        return None

    prompt = _build_prompt(description)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.15, "maxOutputTokens": 4096, "topP": 0.92, "topK": 40},
    }
    url = f"{GEMINI_API_BASE}/{_DIAGRAM_MODEL}:generateContent?key={api_key}"
    try:
        resp = requests.post(url, json=payload, timeout=_ATTEMPT_TIMEOUT)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None

    text = (resp.json().get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", "")).strip()
    if not text:
        return None

    text = re.sub(r'```(?:svg|xml|html)?', '', text).strip()
    m = re.search(r'(<svg[\s\S]*?</svg>)', text, re.IGNORECASE)
    if not m:
        return None
    svg = m.group(1).strip()

    has_visual = any(tag in svg for tag in ('<line', '<circle', '<rect', '<polygon', '<polyline', '<path', '<ellipse'))
    has_label = '<text' in svg
    if not has_visual or not has_label or len(svg) < 400:
        return None
    if '<rect x="0" y="0"' not in svg and 'fill="white"' not in svg[:300]:
        svg = svg.replace('>', '><rect x="0" y="0" width="800" height="520" fill="white"/>', 1)
    return svg


def generate_diagrams(descriptions: list[str]) -> dict:
    """
    Generate SVGs for every unique diagram description, in parallel,
    inside a single shared time budget. Returns {description: svg}
    for whichever ones completed in time.
    """
    if not descriptions or not ACTIVE_KEYS:
        return {}

    unique = list(dict.fromkeys(d.strip() for d in descriptions if d.strip()))
    if not unique:
        return {}

    diagrams = {}
    deadline = time.monotonic() + BUDGET_DIAGRAM_SECONDS
    max_workers = min(6, len(unique))

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(_one_diagram_call, desc, ACTIVE_KEYS[i % len(ACTIVE_KEYS)]): desc
            for i, desc in enumerate(unique)
        }
        remaining = max(1, deadline - time.monotonic())
        try:
            for future in as_completed(futures, timeout=remaining):
                desc = futures[future]
                try:
                    svg = future.result()
                    if svg:
                        diagrams[desc] = svg
                except Exception:
                    pass
        except TimeoutError:
            pass  # budget exhausted — return whatever finished

    return diagrams
