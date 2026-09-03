# Merging the support assistant into the umbrella "SugboDoc" app

This repo is a **standalone Streamlit app** (`streamlit run streamlit_app.py`)
*and* a **drop-in package** for the umbrella multipage app
(`github.com/troymerales/stt_soap` → "SugboDoc"). This file is the checklist for
the second use.

The umbrella, as described:

```
streamlit_app.py                     eClinic dashboard (static replica, iframe) + a dead 💬 button (assistant.js)
pages/1_Consultation_Transcript.py    speech-to-text SOAP page
pages/… (Notes, Evaluation, …)
core/                                pure-Python shared package, ZERO `import streamlit`
  config.py                          reads st.secrets, falls back to os.environ
  gemini.py                          one Gemini client — secret GEMINI_API_KEY, model gemini-3.6-flash
requirements.txt                     one file
.streamlit/secrets.toml              one file
```

The assistant becomes **a shared floating widget** on the Homepage and the
Consultation Transcript page (and any other page you add the one-liner to).

---

## 1. What to copy

| From this repo | To the umbrella | Notes |
|---|---|---|
| `assistant/` (whole package) | `assistant/` | The Streamlit layer. `widget.py`, `session.py`, `ticket_dialog.py`, `styles.py`. |
| `core/*.py` except none — copy all: `bot` `knowledge` `llm` `grounding` `engine` `failure_capture` `ticketing` `jira_client` `jira_dedup` `chatlog` `retrieval` `_gemini_backend` `_mock_backend` `cli` | `core/` | No filename clash with the umbrella's `core/config.py` / `core/gemini.py`. Merge the two `core/__init__.py` docstrings by hand. |
| `config.py` (repo root) | `core/chatbot_config.py` | **Rename on copy** — the umbrella already has a `core/config.py` that does a different job. |
| `api/db.py` `api/db_init.py` `api/schema.sql` | `api/` | Only needed if you want chat-log persistence to Supabase (recommended). `db.py` is import-clean; nothing pulls FastAPI. |
| `docs/SugboDoc-Documentation.sample.md` (and your private `docs/SugboDoc-Documentation.md` if you use it) | `docs/` | The knowledge base the assistant is grounded on. `config.DOCS_PATH` picks up the private file automatically if present. |
| `evaluation/` `analytics/` | optional | The offline eval + docs-improvement loop. Batch/local only — not imported by any page. Needs `requirements-analytics.txt` extras. |

**Do NOT copy:** `streamlit_app.py`, `app.py`, `api/service.py`, `web/`,
`Dockerfile`, `docker-compose.yml`, `render.yaml`, `.github/workflows/`,
`.streamlit/config.toml`, `study/`, `requirements*.txt`. Those are the
standalone repo's own delivery/deploy shells.

---

## 2. The two seams (the only code edits)

### SEAM #1 — secrets → env

`assistant/bootstrap.py` copies `st.secrets` into `os.environ` so `core/` never
imports Streamlit. The umbrella's `core/config.py` already does this.

- **Delete** `assistant/bootstrap.py`.
- In `assistant/session.py`, `assistant/widget.py`, `assistant/ticket_dialog.py`
  there is **no** import of `bootstrap` — nothing to change there.
- Wherever the umbrella loads secrets at startup (its `streamlit_app.py` or a
  shared helper), make sure it runs **before** the first page imports
  `assistant.widget`. If the umbrella doesn't have a startup secret-load yet,
  keep `bootstrap.py` and call `load_secrets()` at the top of each page.

### SEAM #2 — the Gemini client

`core/_gemini_backend.py::_client()` builds its own `genai.Client`. Point it at
the umbrella's shared client:

```python
@functools.lru_cache(maxsize=1)
def _client() -> genai.Client:
    from core.gemini import client        # the umbrella's shared client
    return client()
```

Nothing else changes — same `google-genai` SDK, same call shape, and
`core/llm.py` is untouched.

### The `import config` rename

This repo's `core/*` modules do `import config` (root module). After copying
`config.py` → `core/chatbot_config.py`, run one search-replace across the copied
files:

```bash
# from the umbrella repo root, on the files you copied in:
grep -rl '^import config$' core/ assistant/ api/ evaluation/ analytics/ \
  | xargs sed -i 's/^import config$/from core import chatbot_config as config/'
```

(`assistant/*` import `config` as `import config` too — same rename.) Then align
the model default: in `core/chatbot_config.py` set
`ANSWER_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")` to match the
umbrella, or just set `GEMINI_MODEL` in secrets.

---

## 3. Secrets to add to `.streamlit/secrets.toml`

The assistant reuses `GEMINI_API_KEY` — already there. Add:

```toml
# Jira — outbound support-ticket creation
JIRA_BASE_URL   = "https://your-domain.atlassian.net"
JIRA_EMAIL      = "you@example.com"
JIRA_API_TOKEN  = "your-atlassian-api-token"
JIRA_PROJECT_KEY = "KAN"
JIRA_ISSUE_TYPE = "Task"

# Chat-log persistence (recommended — keeps the analytics/eval loop alive).
# Supabase Session-pooler URL. Run `python -m api.db_init` once after setting it.
DATABASE_URL = "postgresql://postgres.<ref>:<pass>@aws-0-<region>.pooler.supabase.com:5432/postgres"

# Optional
# VERIFY_ANSWERS = "1"     # keep the verification pass on (default)
# LLM_BACKEND    = "mock"  # offline canned answers, no key / quota
```

On Streamlit Community Cloud, paste the same TOML into **App → Settings →
Secrets**. `assistant/bootstrap.py` / the umbrella's `core/config.py` maps every
key to an environment variable of the same name.

---

## 4. Wire the widget into pages

At the **bottom** of `streamlit_app.py` (the Homepage) and
`pages/1_Consultation_Transcript.py` — and any other page you want it on:

```python
from assistant.widget import render_floating_assistant

render_floating_assistant()
```

One shared conversation follows the user across pages (state is in
`st.session_state`, keys prefixed `asst_`). Call it once per page; calling it on
a page that already rendered it is a harmless no-op-ish re-render.

If you'd rather not repeat the import, add a helper next to the umbrella's other
shared UI (e.g. `ui/chrome.py`):

```python
def page_chrome():
    ...                                   # existing header / nav
    from assistant.widget import render_floating_assistant
    render_floating_assistant()
```

---

## 5. Replace the umbrella's dead 💬 button

The umbrella's `streamlit_app.py` renders a decorative floating 💬 button that
belonged to the old `assistant.js`. Remove it so there aren't two:

- delete `assistant.js` (or whatever static file holds the old button/handler),
- remove the `<button …>💬</button>` (and any related CSS) from the dashboard
  replica HTML that gets passed to `st.components.v1.html`,
- the real widget from `render_floating_assistant()` now occupies the same
  bottom-right corner (`assistant/styles.py` pins it there).

The dashboard iframe and the widget live in different layers (iframe vs. the
main Streamlit document), so the widget floats over the iframe with no conflict.

---

## 6. `requirements.txt` delta

The umbrella needs these on top of what it already has (it already has
`streamlit`, `google-genai`, `python-dotenv`):

```
requests>=2.31
SQLAlchemy>=2.0          # only if you set DATABASE_URL (chat-log persistence)
psycopg[binary]>=3.1     # ditto
```

`numpy` / `scikit-learn` are **not** needed by the widget — only by
`analytics/analytics_cluster.py` (batch). Add them only if you run that job in
the same environment.

---

## 7. Post-merge checklist

- [ ] `assistant/` + the `core/*` modules copied; `core/__init__.py` docstrings merged.
- [ ] `config.py` → `core/chatbot_config.py`; `import config` rename applied.
- [ ] SEAM #1: `bootstrap.py` deleted (or kept + called per page); secrets load before `assistant.widget` import.
- [ ] SEAM #2: `_gemini_backend._client()` points at `core/gemini.py`.
- [ ] Jira + (optional) `DATABASE_URL` in `.streamlit/secrets.toml`; `python -m api.db_init` run if using Postgres.
- [ ] `GEMINI_MODEL` aligned to `gemini-3.6-flash`.
- [ ] `render_floating_assistant()` at the bottom of the Homepage + Consultation Transcript page.
- [ ] Old 💬 button + `assistant.js` removed.
- [ ] `LLM_BACKEND=mock streamlit run streamlit_app.py` — widget answers, thumbs-down offers a ticket, ticket dialog opens.
- [ ] With a real key: one real question streams a grounded answer; an off-docs question refuses and offers a ticket.
- [ ] `pytest` (copy `tests/test_assistant.py` + `tests/_assistant_app.py` + `tests/conftest.py` if the umbrella runs the suite).
