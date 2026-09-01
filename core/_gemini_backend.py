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


def embed(texts: list[str], model: str) -> list[list[float]]:
    resp = _client().models.embed_content(model=model, contents=texts)
    return [list(e.values) for e in resp.embeddings]
