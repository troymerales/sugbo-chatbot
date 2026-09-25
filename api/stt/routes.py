"""
The Bisaya speech -> SOAP workflow as JSON, over the `stt/` library.

Mirrors what pages/1_Consultation_Transcript.py walks a user through:
transcribe -> SOAP -> extract -> review -> save, plus notes CRUD and export.
Each step is its own call so a client can show progress and let the user edit
between stages, exactly as the Streamlit page does.
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from stt import asr, audio, export, extract, notes_db, review, soap

router = APIRouter(prefix="/stt", tags=["stt"])


class TranscriptIn(BaseModel):
    transcript: str
    context: str | None = None


class ReviewIn(BaseModel):
    transcript: str
    note: dict


class NoteIn(BaseModel):
    fields: dict


@router.get("/health")
def stt_health() -> dict:
    """Whether the hosted ASR endpoint is reachable. SOAP generation only needs
    Gemini, so the two can be down independently."""
    return {"asr_available": asr.is_available(), "pdf_export": export.pdf_available()}


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty upload")
    mime = file.content_type or "audio/wav"
    result = asr.transcribe(data, mime,
                            duration_s=audio.duration_seconds(data, file.filename or ""))
    return {
        "text": result.text,
        "duration_s": getattr(result, "duration_s", None),
        "warnings": list(getattr(result, "warnings", []) or []),
    }


@router.post("/soap")
def make_soap(body: TranscriptIn) -> dict:
    note = soap.generate_soap_note(body.transcript, context=body.context)
    return note.model_dump() if hasattr(note, "model_dump") else dict(note)


@router.post("/extract")
def make_extract(body: TranscriptIn) -> dict:
    facts = extract.extract_clinical_facts(body.transcript)
    return facts.model_dump() if hasattr(facts, "model_dump") else dict(facts)


@router.post("/review")
def run_review(body: ReviewIn) -> dict:
    verdict = review.review_soap_note(body.transcript, body.note)
    return verdict.model_dump() if hasattr(verdict, "model_dump") else dict(verdict)


@router.get("/notes")
def list_notes(search: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    return {"notes": notes_db.list_notes(search=search, limit=limit, offset=offset)}


@router.post("/notes")
def create_note(body: NoteIn) -> dict:
    return {"id": notes_db.create_note(**body.fields)}


@router.get("/notes/{note_id}")
def get_note(note_id: int) -> dict:
    note = notes_db.get_note(note_id)
    if note is None:
        raise HTTPException(404, "note not found")
    return note


@router.put("/notes/{note_id}")
def update_note(note_id: int, body: NoteIn) -> dict:
    if notes_db.get_note(note_id) is None:
        raise HTTPException(404, "note not found")
    notes_db.update_note(note_id, **body.fields)
    return {"updated": note_id}


@router.delete("/notes/{note_id}")
def delete_note(note_id: int) -> dict:
    notes_db.delete_note(note_id)
    return {"deleted": note_id}


@router.get("/notes/{note_id}/export")
def export_note(note_id: int, fmt: str = Query("md", pattern="^(md|txt|pdf)$")) -> Response:
    note = notes_db.get_note(note_id)
    if note is None:
        raise HTTPException(404, "note not found")
    if fmt == "pdf":
        if not export.pdf_available():
            raise HTTPException(503, "reportlab is not installed")
        return Response(export.to_pdf(note), media_type="application/pdf")
    body = export.to_markdown(note) if fmt == "md" else export.to_text(note)
    return Response(body, media_type="text/plain; charset=utf-8")
