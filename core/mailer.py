"""
core/mailer.py
Optional error-alert emails. Never raises — a failure to send an
alert must never take down a request.
"""
import os
import smtplib
import socket
import platform
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from core.config import (
    ALERT_RECIPIENT as _ALERT_RECIPIENT,
    SMTP_EMAIL as _SMTP_EMAIL,
    SMTP_PASSWORD as _SMTP_PASSWORD,
    SMTP_HOST as _SMTP_HOST,
    SMTP_PORT as _SMTP_PORT,
)


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

