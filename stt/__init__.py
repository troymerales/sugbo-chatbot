"""
Bisaya/Cebuano speech -> SOAP note pipeline (the "Consultation Transcript" side
of SugboDoc).

Ported from the standalone `stt_soap` repo. Pure Python — no Streamlit, no
FastAPI, and (unlike the original) no `torch` / `transformers`: transcription is
a hosted call (Gemini multimodal by default, the fine-tuned Whisper checkpoint
via the HF Inference API as an opt-in backend). The Streamlit pages live in
`pages/` and share helpers in `stt_ui.py`.

    audio -> stt.asr.transcribe -> transcript
          -> stt.soap.generate_soap_note   (Gemini, structured)
          -> stt.extract.extract_clinical_facts
          -> stt.review.review_soap_note
          -> stt.notes_db  (SQLite; the "Past Notes" page)
    stt.evaluation scores the pipeline against trial/.
"""
