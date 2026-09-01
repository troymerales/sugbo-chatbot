"""
The knowledge base: SugboDoc-Documentation.md.

Loads the docs, splits them into sections (by `##` / `###` headings) for citation
and eval matching, and assembles the system prompt the answer model runs with.

The whole doc goes in the prompt every turn — it is ~8k tokens and fits
comfortably. No chunking, no embeddings, no retrieval (see §0 of the architecture
doc). This module is where that decision lives, so swapping in section-level
retrieval later is a local change.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass

import config


@dataclass(frozen=True)
class Section:
    slug: str          # github-style anchor, e.g. "void-a-payment"
    title: str         # heading text, e.g. "Void a payment"
    level: int         # 2 for ##, 3 for ###
    body: str          # text under the heading (until the next heading)

    def snippet(self, limit: int = 400) -> str:
        text = " ".join(self.body.split())
        return text[:limit] + ("…" if len(text) > limit else "")


def _slugify(title: str) -> str:
    s = title.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"\s+", "-", s)


@functools.lru_cache(maxsize=1)
def load_docs() -> str:
    try:
        return config.DOCS_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise FileNotFoundError(
            f"Documentation not found at {config.DOCS_PATH}. "
            "The bot has nothing to ground on."
        ) from exc


@functools.lru_cache(maxsize=1)
def sections() -> tuple[Section, ...]:
    """Every ## / ### section in the docs, in document order."""
    lines = load_docs().splitlines()
    out: list[Section] = []
    cur_title: str | None = None
    cur_level = 0
    buf: list[str] = []

    def flush():
        if cur_title is not None:
            out.append(
                Section(
                    slug=_slugify(cur_title),
                    title=cur_title,
                    level=cur_level,
                    body="\n".join(buf).strip(),
                )
            )

    for line in lines:
        m = re.match(r"^(#{2,3})\s+(.*)$", line)
        if m:
            flush()
            cur_level = len(m.group(1))
            cur_title = m.group(2).strip()
            buf = []
        else:
            buf.append(line)
    flush()
    return tuple(out)


_NON_TOPIC_TITLES = {"table of contents"}


def content_sections() -> tuple[Section, ...]:
    """Sections that carry real how-to content (drops the table of contents)."""
    return tuple(s for s in sections() if s.title.lower() not in _NON_TOPIC_TITLES)


def section_titles() -> list[str]:
    return [s.title for s in content_sections()]


def find_section(needle: str) -> Section | None:
    """Loose lookup by slug or title substring — used by the eval matcher."""
    needle_l = needle.strip().lower()
    for s in sections():
        if s.slug == needle_l or s.title.lower() == needle_l:
            return s
    for s in sections():
        if needle_l in s.title.lower() or needle_l in s.slug:
            return s
    return None


# --------------------------------------------------------------------------- #
# System prompt
# --------------------------------------------------------------------------- #

PERSONA = f"""You are the SugboDoc support assistant. SugboDoc is a cloud-based \
clinic and practice-management platform.

Answer strictly and only from the SugboDoc documentation provided below.

- When the user is trying to accomplish a task, give the numbered steps from the \
docs and name the section heading you took them from.
- Keep answers tight. Do not invent UI labels, fields, menu paths or features \
that are not in the documentation.
- If the documentation does not contain the answer, reply with exactly this \
sentence and nothing else that contradicts it:
  "{config.REFUSAL_MARKER}"
  then suggest the user submit a support ticket.
"""


@functools.lru_cache(maxsize=1)
def system_prompt() -> str:
    return (
        f"{PERSONA}\n\n"
        "===== SUGBODOC DOCUMENTATION =====\n\n"
        f"{load_docs()}\n\n"
        "===== END DOCUMENTATION ====="
    )
