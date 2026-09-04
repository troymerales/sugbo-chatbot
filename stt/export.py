"""
Render a stored note to shareable formats: Markdown, plain text, and (if
reportlab is installed) PDF.
"""

from __future__ import annotations

import io
from typing import Any

from stt.schemas import SECTIONS


def _fmt_dt(value: str) -> str:
    return (value or "").replace("T", " ").replace("+00:00", " UTC")


def _lines(note: dict[str, Any]) -> list[str]:
    soap = note.get("soap") or {}
    extract = note.get("extract") or {}
    review = note.get("review") or {}
    out: list[str] = []

    title = note.get("title") or f"SOAP Note #{note.get('id', '?')}"
    out += [f"# {title}", ""]
    meta = [
        f"Created: {_fmt_dt(note.get('created_at', ''))}",
        f"Updated: {_fmt_dt(note.get('updated_at', ''))}",
    ]
    if note.get("patient_ref"):
        meta.append(f"Patient ref: {note['patient_ref']}")
    if note.get("duration_s"):
        meta.append(f"Audio: {float(note['duration_s']):.0f}s")
    if note.get("whisper_model"):
        meta.append(f"ASR model: {note['whisper_model']}")
    if note.get("soap_model"):
        meta.append(f"SOAP model: {note['soap_model']}")
    out += ["  \n".join(meta), ""]

    out += ["## SOAP", ""]
    for section in SECTIONS:
        out += [f"### {section}", soap.get(section) or "_(empty)_", ""]

    if isinstance(extract, dict) and any(extract.values()):
        out += ["## Structured data", ""]
        for key, val in extract.items():
            if not val:
                continue
            label = key.replace("_", " ").capitalize()
            if isinstance(val, list):
                if val and isinstance(val[0], dict):
                    val = ", ".join(f"{d.get('name', '')}: {d.get('value', '')}" for d in val)
                else:
                    val = ", ".join(str(v) for v in val)
            out.append(f"- **{label}:** {val}")
        out.append("")

    if review:
        out += ["## Grounding review", ""]
        out.append(f"- Grounding score: {review.get('grounding_score', '?')}/5")
        out.append(f"- Completeness score: {review.get('completeness_score', '?')}/5")
        for s in review.get("unsupported_statements") or []:
            out.append(f"- Unsupported: {s}")
        for s in review.get("missing_elements") or []:
            out.append(f"- Missing: {s}")
        if review.get("summary"):
            out += ["", review["summary"]]
        out.append("")

    out += ["## Transcript", "", note.get("transcript") or "_(none)_", ""]
    return out


def to_markdown(note: dict[str, Any]) -> str:
    return "\n".join(_lines(note)).strip() + "\n"


def to_text(note: dict[str, Any]) -> str:
    import re

    md = to_markdown(note)
    md = re.sub(r"^#{1,6}\s*", "", md, flags=re.MULTILINE)
    md = md.replace("**", "").replace("_(empty)_", "(empty)").replace("  \n", "\n")
    return md


def pdf_available() -> bool:
    try:
        import reportlab  # noqa: F401

        return True
    except ImportError:
        return False


def to_pdf(note: dict[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, title=note.get("title") or "SOAP Note")
    styles = getSampleStyleSheet()
    flow = []
    for line in _lines(note):
        if not line:
            flow.append(Spacer(1, 6))
            continue
        if line.startswith("### "):
            flow.append(Paragraph(line[4:], styles["Heading3"]))
        elif line.startswith("## "):
            flow.append(Paragraph(line[3:], styles["Heading2"]))
        elif line.startswith("# "):
            flow.append(Paragraph(line[2:], styles["Title"]))
        else:
            safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            safe = safe.replace("**", "").replace("  \n", "<br/>")
            flow.append(Paragraph(safe, styles["BodyText"]))
    doc.build(flow)
    return buf.getvalue()
