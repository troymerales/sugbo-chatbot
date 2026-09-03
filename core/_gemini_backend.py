"""
The real Gemini backend. Only llm.py imports this, and only when
config.LLM_BACKEND == "gemini". Kept separate so the mock path never touches the
SDK or needs an API key.
"""

from __future__ import annotations

import functools

from google import genai
from google.genai import types

import config


@functools.lru_cache(maxsize=1)
def _client() -> genai.Client:
    # MERGE SEAM #2 — in the umbrella "SugboDoc" app, replace this body with
    #   `from core.gemini import client; return client()`
    # so the whole app shares one Gemini client + key. Nothing else in this file
    # or in llm.py needs to change (same google-genai SDK, same call shape).
    key = config.get_api_key()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to .env (see .env.example).")
    return genai.Client(api_key=key)


def _to_contents(contents: list[dict]) -> list[types.Content]:
    return [
        types.Content(role=c["role"], parts=[types.Part(text=c["text"])])
        for c in contents
    ]


def generate(*, contents: list[dict], system: str | None, model: str,
             temperature: float, json_mode: bool) -> str:
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        response_mime_type="application/json" if json_mode else None,
    )
    resp = _client().models.generate_content(
        model=model, contents=_to_contents(contents), config=cfg
    )
    return (resp.text or "").strip()


def generate_stream(*, contents: list[dict], system: str | None, model: str,
                    temperature: float):
    """Yield answer text chunks as the model produces them. Same call as
    generate() but with the streaming endpoint — used by llm.Chat.send_stream()
    for the Streamlit widget. No json_mode: streaming is only for user answers."""
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
    )
    for chunk in _client().models.generate_content_stream(
        model=model, contents=_to_contents(contents), config=cfg
    ):
        text = getattr(chunk, "text", None)
        if text:
            yield text


def embed(texts: list[str], model: str) -> list[list[float]]:
    resp = _client().models.embed_content(model=model, contents=texts)
    return [list(e.values) for e in resp.embeddings]
