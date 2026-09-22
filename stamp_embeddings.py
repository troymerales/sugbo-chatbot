"""Stamp embeddings.json so core/retrieval.py will reuse it.

The file holds one Gemini vector per documentation section. Those vectors say
nothing about where they came from, so retrieval only trusts the file when it
carries the fingerprint of the docs, backend and embedding model it was built
under — otherwise a docs edit would leave it silently indexing stale text.

Run this after regenerating the vectors (study/rag_notebook.ipynb), or any time
you edit the documentation or change GEMINI_EMBED_MODEL:

    python stamp_embeddings.py

Without a matching stamp the file is ignored and every section is embedded
through the API again on the next cold start.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys

import config
from core import knowledge, retrieval


def main() -> int:
    path = config.EMBEDDINGS_SEED_PATH
    if not path.exists():
        print(f"no embeddings file at {path}", file=sys.stderr)
        return 1

    payload = json.loads(path.read_text(encoding="utf-8"))
    # Accept the notebook's flat {slug: vector} shape and an already-stamped file.
    vectors = payload.get("vectors", payload)

    secs = knowledge.content_sections()
    missing = [s.slug for s in secs if s.slug not in vectors]
    if missing:
        print(
            f"{path.name} covers {len(secs) - len(missing)} of {len(secs)} sections; "
            f"missing e.g. {missing[:3]}. Regenerate it before stamping.",
            file=sys.stderr,
        )
        return 1

    dims = {len(vectors[s.slug]) for s in secs}
    if len(dims) != 1:
        print(f"inconsistent vector dimensions: {sorted(dims)}", file=sys.stderr)
        return 1

    stamped = json.dumps(
        {
            "fingerprint": retrieval.fingerprint(),
            "backend": config.LLM_BACKEND,
            "model": config.EMBED_MODEL,
            "docs": config.DOCS_PATH.name,
            "created": dt.date.today().isoformat(),
            "vectors": vectors,
        }
    )

    # Via a temp file: a half-written seed would lose vectors that cost real quota.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(stamped, encoding="utf-8")
    os.replace(tmp, path)

    print(f"stamped {path.name}")
    print(f"  fingerprint : {retrieval.fingerprint()}")
    print(f"  backend     : {config.LLM_BACKEND}")
    print(f"  model       : {config.EMBED_MODEL}")
    print(f"  docs        : {config.DOCS_PATH.name}")
    print(f"  sections    : {len(secs)} @ {dims.pop()} dims")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
