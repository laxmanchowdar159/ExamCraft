"""
app.py
ExamCraft — Flask routes only. Every real piece of work is delegated
to a module under core/:

  core.config       env vars, paths, model list, time budgets
  core.prompts      builds the paper-generation prompt
  core.ai_text      fast parallel Gemini call for paper text
  core.ai_diagrams  fast parallel Gemini calls for SVG diagrams
  core.pdf_engine   ReportLab PDF layout
  core.svg_render   SVG -> PDF-embeddable image
  core.fonts        DejaVu font registration
  core.fallback     offline template used only if Gemini is unreachable
  core.splitter     paper / answer-key text splitting
  core.mailer       optional error-alert emails

See core/config.py for the time budgets that keep /generate under
~30-40 seconds instead of the old ~3 minutes.
"""
import os
import re
import json
import base64
import traceback as _tb
from io import BytesIO

from flask import Flask, render_template, request, jsonify, send_file

from core.config import (
    GEMINI_KEY, GEMINI_KEY_2, GEMINI_KEY_3, ACTIVE_KEYS,
    GEMINI_MODELS, DATA_DIR, BUDGET_TOTAL_SECONDS,
)
from core.prompts import build_prompt
from core.ai_text import generate_paper_text
from core.ai_diagrams import generate_diagrams
from core.pdf_engine import create_exam_pdf
from core.fallback import build_local_paper
from core.splitter import split_key
from core.mailer import send_error_email, _capture_user_choices

app = Flask(__name__, template_folder="templates",
            static_folder="static", static_url_path="/static")


# ═══════════════════════════════════════════════════════════════════════
# SECURITY HEADERS — applied to every response
# ═══════════════════════════════════════════════════════════════════════
@app.after_request
def apply_security_headers(response):
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "connect-src 'self'; "
        "img-src 'self' data:; "
        "media-src 'none'; object-src 'none'; frame-src 'none'; "
        "frame-ancestors 'none'; worker-src 'none'; manifest-src 'none'; "
        "base-uri 'self'; form-action 'self';"
    )
    response.headers["Content-Security-Policy"] = csp
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), gyroscope=(), "
        "accelerometer=(), magnetometer=(), usb=(), midi=(), payment=(), "
        "fullscreen=(self), picture-in-picture=(), display-capture=(), "
        "screen-wake-lock=(), web-share=(), clipboard-read=(), "
        "clipboard-write=(self), ambient-light-sensor=(), battery=(), "
        "bluetooth=(), serial=(), nfc=(), hid=()"
    )
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers.pop("Server", None)
    response.headers["X-Powered-By"] = "ExamCraft"
    return response


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════
def _resolve_board(data: dict) -> str:
    exam_type        = (data.get("examType") or "").strip()
    state            = (data.get("state") or "").strip()
    competitive_exam = (data.get("competitiveExam") or "").strip()
    if exam_type == "state-board" and state:
        return state.strip() if "state board" in state.lower() else f"{state} State Board"
    if exam_type == "competitive" and competitive_exam:
        return competitive_exam
    return (data.get("board") or "AP State Board").strip()


def _looks_truncated(text: str) -> bool:
    """A quick heuristic: does the paper end mid-sentence / mid-LaTeX?"""
    if not text:
        return True
    last = text.rstrip().split("\n")[-1].strip()
    if last.count("$") % 2 == 1:
        return True
    terminal_chars = ".,:;!?)]}\u2014\u2026'\""
    if last and last[-1] not in terminal_chars and not last.endswith("Marks]"):
        if len(last) > 10:
            return True
    return False


def _extract_diagram_descriptions(full_text: str) -> list:
    return [d.strip() for d in re.findall(r'\[DIAGRAM:\s*([^\]]+)\]', full_text, re.IGNORECASE) if d.strip()]


def _build_both_pdfs(paper, subject, chapter_safe, board, key, diagrams, marks_safe):
    """Build the no-key and with-key PDFs concurrently - pure CPU work,
    so running them on two threads overlaps most of the layout cost."""
    from concurrent.futures import ThreadPoolExecutor

    def _no_key():
        return create_exam_pdf(paper, subject, chapter_safe, board=board,
                                answer_key=None, include_key=False,
                                diagrams=diagrams, marks=marks_safe)

    def _with_key():
        if not (key and key.strip()):
            return None
        return create_exam_pdf(paper, subject, chapter_safe, board=board,
                                answer_key=key, include_key=True,
                                diagrams=diagrams, marks=marks_safe)

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_plain = ex.submit(_no_key)
        f_key = ex.submit(_with_key)
        pdf_bytes = None
        pdf_error_msg = None
        try:
            pdf_bytes = f_plain.result()
        except Exception as e:
            pdf_error_msg = str(e)
            try:
                safe_paper = re.sub(r'[^\x00-\x7F\u0080-\u024F\u0370-\u03FF\u2200-\u22FF]', ' ', paper)
                pdf_bytes = create_exam_pdf(safe_paper, subject, chapter_safe, board=board,
                                             answer_key=None, include_key=False,
                                             diagrams={}, marks=marks_safe)
                pdf_error_msg = None
            except Exception as e2:
                pdf_error_msg = f"PDF rendering failed: {e}. Fallback also failed: {e2}"

        try:
            pdf_key_bytes = f_key.result()
        except Exception:
            pdf_key_bytes = None

    return pdf_bytes, pdf_key_bytes, pdf_error_msg


# ═══════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    data = {}
    try:
        data             = request.get_json(force=True) or {}
        class_name       = (data.get("class") or "").strip()
        subject          = (data.get("subject") or "").strip()
        chapter          = (data.get("chapter") or "").strip()
        marks            = (data.get("marks") or "100").strip()
        difficulty       = (data.get("difficulty") or "Medium").strip()
        exam_type        = (data.get("examType") or "").strip()
        suggestions      = (data.get("suggestions") or "").strip()
        board            = _resolve_board(data)

        if not subject and (data.get("scope") == "all" or data.get("all_chapters")):
            subject = "Mixed Subjects"

        use_fallback = str(data.get("use_fallback", "false")).lower() in ("true", "1", "yes")

        prompt = data.get("prompt") or build_prompt(
            class_name, subject, chapter, board, exam_type, difficulty, marks, suggestions)

        generated_text = None
        api_error = None
        model_used = None

        if not use_fallback:
            generated_text, model_used, api_error = generate_paper_text(prompt)

        if not generated_text:
            if use_fallback or not ACTIVE_KEYS:
                generated_text = build_local_paper(class_name, subject, chapter, marks, difficulty)
                use_fallback = True
            else:
                user_choices = _capture_user_choices(data)
                user_choices["board_resolved"] = board
                send_error_email(
                    error_type="AI Generation Failed - No Output",
                    error_msg=api_error or "Gemini returned no usable response within the time budget.",
                    user_choices=user_choices,
                    extra_context={
                        "gemini_key_set": bool(GEMINI_KEY),
                        "models_tried": str(GEMINI_MODELS),
                        "per_model_errors": api_error or "-",
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

        # If the response looks cut off, ship it trimmed to the last
        # complete question rather than paying for a second full
        # generation call (that used to add another 60-90s on its own).
        if _looks_truncated(paper) and not use_fallback:
            trimmed = re.split(r'\n(?=\d+\.\s)', paper)
            if len(trimmed) > 1:
                paper = '\n'.join(trimmed[:-1]).rstrip()

        # ── Diagrams: one shared budget, run in parallel ────────────
        diagrams = {}
        if ACTIVE_KEYS:
            full_text = paper + "\n" + (key or "")
            descs = _extract_diagram_descriptions(full_text)
            if descs:
                diagrams = generate_diagrams(descs)

        marks_safe = str(marks or "100").strip()
        chapter_safe = chapter if chapter and chapter != "Full Syllabus" else ""

        pdf_bytes, pdf_key_bytes, pdf_error_msg = _build_both_pdfs(
            paper, subject, chapter_safe, board, key, diagrams, marks_safe)

        pdf_b64 = base64.b64encode(pdf_bytes).decode() if pdf_bytes else None
        pdf_key_b64 = base64.b64encode(pdf_key_bytes).decode() if pdf_key_bytes else None

        return jsonify({
            "success": True, "paper": paper, "answer_key": key,
            "api_error": api_error, "used_fallback": use_fallback,
            "board": board, "subject": subject, "chapter": chapter,
            "model_used": model_used,
            "pdf_b64": pdf_b64,
            "pdf_key_b64": pdf_key_b64,
            "pdf_error": pdf_error_msg,
        })

    except Exception as e:
        tb_str = _tb.format_exc()
        send_error_email(
            error_type="Unhandled Exception in /generate",
            error_msg=str(e),
            traceback_str=tb_str,
            user_choices=_capture_user_choices(data),
            extra_context={"endpoint": "/generate", "gemini_key_set": bool(GEMINI_KEY)},
        )
        return jsonify({"success": False, "error": str(e), "trace": tb_str}), 500


@app.route("/download-pdf", methods=["POST"])
def download_pdf():
    data = {}
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
        if ACTIVE_KEYS:
            full_text = paper_text + "\n" + (answer_key or "")
            descs = _extract_diagram_descriptions(full_text)
            if descs:
                diagrams = generate_diagrams(descs)

        pdf_bytes = create_exam_pdf(
            paper_text, subject, chapter, board=board, answer_key=answer_key,
            include_key=include_key, diagrams=diagrams, marks=marks)

        parts = [p for p in [board, subject, chapter] if p]
        filename = ("_".join(parts) + ".pdf").replace(" ", "_").replace("/", "-")
        return send_file(BytesIO(pdf_bytes), as_attachment=True,
                          download_name=filename, mimetype="application/pdf")
    except Exception as e:
        tb_str = _tb.format_exc()
        send_error_email(
            error_type="PDF Generation / Download Failed",
            error_msg=str(e),
            traceback_str=tb_str,
            user_choices={
                "subject": data.get("subject", "-"), "chapter": data.get("chapter", "-"),
                "board": data.get("board", "-"), "marks": data.get("marks", "-"),
                "include_key": data.get("includeKey", False),
                "paper_length": len(data.get("paper", "")),
                "key_length": len(data.get("answer_key", "")),
            },
            extra_context={"endpoint": "/download-pdf"},
        )
        return jsonify({"success": False, "error": str(e), "trace": tb_str}), 500


@app.route("/health")
def health():
    configured = bool(ACTIVE_KEYS)
    return jsonify({
        "status": "ok",
        "gemini": "configured" if configured else "not configured",
        "gemini_key_2": "set" if GEMINI_KEY_2 else "not set",
        "gemini_key_3": "set" if GEMINI_KEY_3 else "not set",
        "key_strategy": "parallel race across models/keys, bounded by core.config.BUDGET_TEXT_SECONDS",
        "models_available": GEMINI_MODELS if configured else [],
    })


@app.route("/chapters")
def chapters():
    try:
        data_path = DATA_DIR / "curriculum.json"
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
