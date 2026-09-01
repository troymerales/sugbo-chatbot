"""
Offline, deterministic stand-in for the model. Selected by config.LLM_BACKEND
== "mock" (set with `--mock` on the scripts, or LLM_BACKEND=mock in the env).

It is NOT smart. It does just enough to exercise every code path without an API
key or quota:
  - answers   -> naive word-overlap retrieval over the doc sections
  - the JSON utility calls (verify / triage / draft / judge / label / gen) are
    recognised by their system prompt and return well-formed JSON
  - embeddings -> hashed bag-of-words vectors (real lexical cosine similarity)

Good for: unit tests, the FastAPI demo, wiring up the analytics loop. Not for:
measuring answer quality — that needs the real model.
"""

from __future__ import annotations

import hashlib
import json
import math
import re

import config
from core import knowledge

_EMBED_DIM = 256


# --------------------------------------------------------------------------- #
# generate
# --------------------------------------------------------------------------- #

def _last_user_text(contents: list[dict]) -> str:
    for c in reversed(contents):
        if c["role"] == "user":
            return c["text"]
    return contents[-1]["text"] if contents else ""


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _retrieve(question: str) -> tuple[float, knowledge.Section | None]:
    q = set(_tokens(question)) - {"how", "do", "i", "the", "a", "to", "in", "of", "is", "my"}
    best_score, best = 0.0, None
    for sec in knowledge.content_sections():
        body_tokens = set(_tokens(sec.title + " " + sec.body))
        overlap = len(q & body_tokens)
        score = overlap / (len(q) or 1)
        if score > best_score:
            best_score, best = score, sec
    return best_score, best


def _mock_answer(question: str) -> str:
    score, sec = _retrieve(question)
    if score < 0.34 or sec is None:
        return (
            f"{config.REFUSAL_MARKER}. You can submit a support ticket and our "
            "team will follow up.  [mock backend]"
        )
    steps = "\n".join(
        line for line in sec.body.splitlines()
        if re.match(r"\s*\d+\.", line) or line.strip().startswith("-")
    )[:800]
    return f"From **{sec.title}** in the documentation:\n\n{steps or sec.snippet()}\n\n[mock backend]"


def _q_from_transcript(text: str) -> str:
    users = re.findall(r"^User:\s*(.+)$", text, flags=re.MULTILINE)
    return users[0] if users else text


def generate(*, contents: list[dict], system: str | None, json_mode: bool) -> str:
    sys = (system or "").lower()
    prompt = _last_user_text(contents)

    if "fact-checker" in sys:  # grounding.verify
        supported = config.REFUSAL_MARKER.lower() in prompt.lower() or "from **" in prompt.lower()
        return json.dumps({
            "supported": bool(supported) or True,
            "unsupported_claims": [],
            "reason": "mock: not actually checked",
        })

    if "triage failed support" in sys:  # failure_capture.triage
        q = _q_from_transcript(prompt).lower()
        if any(w in q for w in ("mobile", "iphone", "android", "api", "webhook", "cost", "price", "hipaa", "legal")):
            label = "out_of_scope"
        elif any(w in q for w in ("error", "not working", "broken", "missing button", "won't", "cannot click")):
            label = "product_bug"
        else:
            label = "docs_gap"
        return json.dumps({"label": label, "confidence": 0.5, "rationale": "mock triage"})

    if "draft a support ticket" in sys:  # ticketing.draft_ticket
        q = _q_from_transcript(prompt)
        return json.dumps({
            "subject": q[:70] or "SugboDoc support request",
            "category": "Other",
            "summary": f"User asked: {q}. The assistant had no documented answer. [mock]",
        })

    if "grading a sugbodoc" in sys:  # eval_run.judge
        exp_refuse = "expected behaviour: refuse" in prompt.lower()
        answered_refusal = config.REFUSAL_MARKER.lower() in prompt.lower()
        if exp_refuse:
            c = 1.0 if answered_refusal else 0.1
        else:
            c = 0.25 if answered_refusal else 0.85
        return json.dumps({"correctness": c, "groundedness": 1.0 if answered_refusal else 0.8,
                           "notes": "mock judge — not a real grade"})

    if "write test questions" in sys:  # eval_gen
        return json.dumps({"cases": [
            {"question": "Mock question about this section?", "must_include": ["Add", "Submit"]},
        ]})

    if "summarise the shared unmet need" in sys:  # analytics_cluster label
        return json.dumps({
            "label": "mock cluster label",
            "gap": "mock: the docs are missing something about these questions",
            "suggested_sections": [knowledge.section_titles()[0]] if knowledge.section_titles() else [],
        })

    if "maintain the sugbodoc user documentation" in sys:  # docs_loop
        return ("### Verdict\nneeds-more-info — mock backend cannot draft real docs.\n\n"
                "### Proposed doc change\n(Run with the real model to draft this.)\n\n"
                "### Eval case to add first\n{\"id\": \"gen-mock\", \"question\": \"...\", "
                "\"expected_behavior\": \"answer\"}")

    # default: it's a user question
    return _mock_answer(prompt)


# --------------------------------------------------------------------------- #
# embed  — hashed bag-of-words, L2-normalised (deterministic, lexical cosine)
# --------------------------------------------------------------------------- #

def _embed_one(text: str) -> list[float]:
    vec = [0.0] * _EMBED_DIM
    for tok in _tokens(text):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % _EMBED_DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed(texts: list[str]) -> list[list[float]]:
    return [_embed_one(t) for t in texts]
