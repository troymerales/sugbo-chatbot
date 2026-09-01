"""
FastAPI backend — the same conversation flow as app.py, exposed as JSON so it can
sit behind an existing website instead of Streamlit.

    pip install -r requirements-service.txt
    python -m api.db_init             # once, if DATABASE_URL is set
    uvicorn api.service:app --reload
    #  open http://127.0.0.1:8000  for the bundled demo widget

Endpoints:
    GET  /                                                   -> the dashboard mockup + chat widget
    GET  /documentation                                      -> the docs viewer page
    GET  /widget/config                                      -> {greeting, documentation_url}
    GET  /healthz
    POST /chat            {conversation_id?, message}        -> state
    POST /feedback        {conversation_id, helpful}         -> state
    POST /tell-me-more    {conversation_id}                  -> state
    GET  /ticket/draft?conversation_id=...                   -> {subject, category, summary, duplicate?}
    POST /ticket          {conversation_id, email, subject, summary, category?}   -> state
    POST /ticket/link-duplicate   {conversation_id}          -> state
    GET    /session/{conversation_id}                        -> state (for the widget to resume)
    DELETE /session/{conversation_id}

Every state response carries the full `messages` list; the widget renders new
messages by diffing against what it has already shown, so terminal replies like
"Great — glad I could help!" appear with no special-casing.

Session store:
  * DATABASE_URL set   -> the `conversations` PostgreSQL table (db.py). Survives
                          restarts; several uvicorn workers share it.
  * DATABASE_URL unset -> an in-process dict (`_MEM`). Fine for a single-process
                          demo. The row / entry is dropped once the conversation
                          reaches a terminal stage (it is then in `chat_logs`).
"""

from __future__ import annotations

import base64
import html
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import config
from api import db
from core import engine, jira_client, knowledge
from core.llm import QuotaError


@asynccontextmanager
async def lifespan(_: FastAPI):
    if db.enabled():
        db.init_db()
        swept = db.delete_stale_conversations(24)
        if swept:
            print(f"[startup] cleared {swept} stale conversation row(s)")
    yield


app = FastAPI(title="SugboDoc Support API", lifespan=lifespan)

# Demo-open CORS. Lock `allow_origins` to your site's origin before shipping.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-process fallback session store, used only when no DATABASE_URL is configured.
_MEM: dict[str, engine.Conversation] = {}


# --------------------------------------------------------------------------- #
# Session store  (Postgres via db.py, or the _MEM dict)
# --------------------------------------------------------------------------- #

def _load(conversation_id: str | None) -> engine.Conversation | None:
    if not conversation_id:
        return None
    if db.enabled():
        data = db.load_conversation(conversation_id)
        return engine.deserialize(data) if data else None
    return _MEM.get(conversation_id)


def _save(conv: engine.Conversation) -> None:
    # A finished conversation lives in chat_logs now — don't keep a live row.
    if conv.stage == "done":
        _drop(conv.id)
        return
    if db.enabled():
        db.save_conversation(
            conversation_id=conv.id, stage=conv.stage, started_at=conv.started_at,
            question_count=conv.question_count, state=engine.serialize(conv),
        )
    else:
        _MEM[conv.id] = conv


def _drop(conversation_id: str) -> bool:
    if db.enabled():
        return db.delete_conversation(conversation_id)
    return _MEM.pop(conversation_id, None) is not None


def _count() -> int:
    return db.count_conversations() if db.enabled() else len(_MEM)


def _get(conversation_id: str) -> engine.Conversation:
    conv = _load(conversation_id)
    if conv is None:
        raise HTTPException(404, "unknown conversation_id (it may have expired)")
    return conv


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #

class ChatIn(BaseModel):
    conversation_id: str | None = None
    message: str


class FeedbackIn(BaseModel):
    conversation_id: str
    helpful: bool


class ConvIn(BaseModel):
    conversation_id: str


class TicketIn(BaseModel):
    conversation_id: str
    email: str
    subject: str
    summary: str
    name: str = ""               # submitter's name → Jira reporter / custom field
    category: str = "Other"
    needed_by: str = ""          # "when do you need this?" — YYYY-MM-DD from the date picker, or ""


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@app.get("/healthz")
def healthz() -> dict:
    return {
        "status": "ok",
        "backend": config.LLM_BACKEND,
        "answer_model": config.ANSWER_MODEL,
        "jira_configured": jira_client.jira_configured(),
        "session_store": "postgres" if db.enabled() else "memory",
        "active_sessions": _count(),
    }


@app.post("/chat")
def chat(body: ChatIn) -> dict:
    conv = _load(body.conversation_id) or engine.start(body.conversation_id)
    try:
        return engine.ask(conv, body.message)
    except QuotaError as exc:
        raise HTTPException(503, str(exc))
    finally:
        _save(conv)


@app.post("/feedback")
def feedback(body: FeedbackIn) -> dict:
    conv = _get(body.conversation_id)
    try:
        return engine.feedback(conv, body.helpful)
    finally:
        _save(conv)


@app.post("/tell-me-more")
def tell_me_more(body: ConvIn) -> dict:
    conv = _get(body.conversation_id)
    try:
        return engine.tell_me_more(conv)
    finally:
        _save(conv)


@app.get("/ticket/draft")
def ticket_draft(conversation_id: str) -> dict:
    conv = _get(conversation_id)
    try:
        return engine.ticket_draft(conv)
    finally:
        _save(conv)


@app.post("/ticket")
def ticket(body: TicketIn) -> dict:
    conv = _get(body.conversation_id)
    if not (body.email.strip() and body.subject.strip() and body.summary.strip()):
        raise HTTPException(422, "email, subject and summary are required")
    try:
        return engine.submit_ticket(
            conv, email=body.email.strip(), subject=body.subject.strip(),
            summary=body.summary.strip(), category=body.category,
            needed_by=body.needed_by.strip(), name=body.name.strip(),
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    finally:
        _save(conv)


@app.post("/ticket/link-duplicate")
def link_duplicate(body: ConvIn) -> dict:
    conv = _get(body.conversation_id)
    try:
        return engine.link_duplicate(conv)
    finally:
        _save(conv)


@app.get("/session/{conversation_id}")
def get_session(conversation_id: str) -> dict:
    """Return the current state of a live conversation so the widget can resume
    it after a page reload. 404 once the conversation has ended."""
    conv = _get(conversation_id)
    return engine._state(conv)


@app.delete("/session/{conversation_id}")
def end_session(conversation_id: str) -> dict:
    conv = _load(conversation_id)
    if conv:
        engine.log_abandoned(conv)
        _drop(conversation_id)
    return {"ended": bool(conv)}


# --------------------------------------------------------------------------- #
# Widget config + documentation viewer
# --------------------------------------------------------------------------- #

@app.get("/widget/config")
def widget_config() -> dict:
    return {
        "greeting": engine.GREETING,
        "documentation_url": "/documentation",
        "backend": config.LLM_BACKEND,
    }


_DOC_PAGE_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SugboDoc Documentation</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.0.8/purify.min.js"></script>
<style>
  :root{--indigo:#3b41d6;--ink:#1f2430;--muted:#6b7280;--line:#e6e7ef;--bg:#f4f5fb;}
  *{box-sizing:border-box;}
  body{margin:0;font:15px/1.65 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    color:var(--ink);background:var(--bg);}
  header{background:var(--indigo);color:#fff;padding:14px 24px;display:flex;
    align-items:center;gap:14px;position:sticky;top:0;z-index:5;}
  header b{font-size:16px;}
  header a{color:#fff;text-decoration:none;opacity:.9;font-size:13px;margin-left:auto;}
  header a:hover{opacity:1;text-decoration:underline;}
  .layout{display:grid;grid-template-columns:288px 1fr;max-width:1180px;margin:0 auto;}
  nav#toc{position:sticky;top:52px;align-self:start;height:calc(100vh - 52px);
    overflow-y:auto;padding:18px 12px;border-right:1px solid var(--line);background:#fff;}
  nav#toc a{display:block;padding:5px 10px;border-radius:7px;color:#3a4152;
    text-decoration:none;font-size:13.5px;}
  nav#toc a:hover{background:#f2f3fb;}
  nav#toc a.active{background:#eef0fe;color:var(--indigo);font-weight:600;}
  nav#toc a.lvl3{padding-left:24px;font-size:12.5px;color:var(--muted);}
  nav#toc a.lvl4{padding-left:38px;font-size:12px;color:var(--muted);}
  main#doc{padding:28px 40px;min-width:0;background:#fff;}
  main#doc h1{font-size:26px;margin:.4em 0 .5em;}
  main#doc h2{font-size:20px;margin:1.5em 0 .4em;padding-top:8px;border-top:1px solid var(--line);}
  main#doc h3{font-size:16px;margin:1.2em 0 .3em;}
  main#doc code{background:#eef0f5;border-radius:4px;padding:1px 5px;font-size:.9em;}
  main#doc pre{background:#1f2430;color:#f4f5fb;padding:14px;border-radius:10px;overflow-x:auto;}
  main#doc pre code{background:transparent;padding:0;}
  main#doc table{border-collapse:collapse;width:100%;margin:1em 0;}
  main#doc th,main#doc td{border:1px solid var(--line);padding:7px 10px;text-align:left;}
  main#doc img{max-width:100%;}
  main#doc :target{scroll-margin-top:64px;}
  @media (max-width:820px){.layout{grid-template-columns:1fr;}nav#toc{display:none;}}
</style>
</head>
<body>
<header>
  <b>&#128196; SugboDoc Documentation</b>
  <span style="opacity:.8;font-size:13px">the source the assistant answers from</span>
  <a href="/">&larr; back to dashboard</a>
</header>
<div class="layout">
  <nav id="toc">__NAV__</nav>
  <main id="doc"></main>
</div>
<script>
const MD = new TextDecoder().decode(
  Uint8Array.from(atob("__DOC_B64__"), c => c.charCodeAt(0))
);
function slugify(t){
  return t.trim().toLowerCase().replace(/[^\w\s-]/g,"").replace(/\s+/g,"-");
}
const doc = document.getElementById("doc");
if (window.marked) marked.setOptions({ breaks: false, gfm: true });
doc.innerHTML = (window.DOMPurify ? DOMPurify.sanitize : (x=>x))(
  (window.marked ? marked.parse : (x=>x))(MD)
);
const heads = [...doc.querySelectorAll("h1,h2,h3,h4")];
heads.forEach(h => h.id = slugify(h.textContent));

const links = new Map([...document.querySelectorAll("#toc a")].map(a =>
  [a.getAttribute("href").slice(1), a]));
const obs = new IntersectionObserver(entries => {
  entries.filter(e => e.isIntersecting).forEach(e => {
    links.forEach(a => a.classList.remove("active"));
    const a = links.get(e.target.id);
    if (a) a.classList.add("active");
  });
}, { rootMargin: "-64px 0px -70% 0px" });
heads.forEach(h => obs.observe(h));
</script>
</body>
</html>"""


@app.get("/documentation", response_class=HTMLResponse)
def documentation() -> str:
    """Render docs/SugboDoc-Documentation.md with a clickable section nav."""
    try:
        md = knowledge.load_docs()
    except FileNotFoundError:
        return "<h1>Documentation not found</h1><p>docs/SugboDoc-Documentation.md is missing.</p>"
    nav = "\n".join(
        f'<a class="lvl{s.level}" href="#{s.slug}">{html.escape(s.title)}</a>'
        for s in knowledge.content_sections()
    )
    doc_b64 = base64.b64encode(md.encode("utf-8")).decode("ascii")
    return (_DOC_PAGE_TEMPLATE
            .replace("__NAV__", nav)
            .replace("__DOC_B64__", doc_b64))


# --------------------------------------------------------------------------- #
# Bundled demo widget
# --------------------------------------------------------------------------- #

_WIDGET = (config.ROOT / "web" / "index.html")


@app.get("/", response_class=HTMLResponse)
def widget() -> str:
    if _WIDGET.exists():
        return _WIDGET.read_text(encoding="utf-8")
    return "<p>Demo widget missing. The API is still up at <code>/docs</code>.</p>"
