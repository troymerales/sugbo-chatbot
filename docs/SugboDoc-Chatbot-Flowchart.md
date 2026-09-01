# Building the SugboDoc Assistant — Chatbot Development Flowchart

A build plan for a **documentation support chatbot** that answers user questions strictly
from the product docs. When it *can't* answer, it captures that failure and turns it into
either a **Jira ticket** (on the user's say-so) or a **docs-update task** — so the knowledge
base gets better over time.

## The data flow in one picture

```mermaid
flowchart LR
    U[User] <--> BOT[Chatbot<br/>reads docs only]
    BOT -->|chat failed| CAP[Failure capture]
    CAP -->|user opts in| TIX[Generate + append<br/>Jira ticket]
    CAP --> QUEUE[(Doc-gap queue)]
    TIX -.resolved / triaged.-> QUEUE
    QUEUE --> UPD[Docs update<br/>human + LLM]
    UPD --> DOCS[(SugboDoc-Documentation.md)]
    DOCS --> BOT

    style CAP fill:#2b6cb0,stroke:#1a365d,color:#fff
    style QUEUE fill:#2b6cb0,stroke:#1a365d,color:#fff
    style UPD fill:#2b6cb0,stroke:#1a365d,color:#fff
```

**Jira is outbound only.** The bot never retrieves tickets. The only thing it reads is
`SugboDoc-Documentation.md`.

Two constraints drive every choice:

1. **Highlight real data science skill — but stay honest.** No classical technique used just
   to show theory when a simpler or better modern tool wins. Section 8 lists what was
   deliberately *not* used and why.
2. **Minimal / zero cost.** The LLM is **Google Gemini** on the free tier. The per-turn
   budget is deliberately just *answer + one verification pass*; failure triage and ticket
   drafting were originally model calls but are now rule-based / deterministic. Jira's REST
   API is free with any account and is called only when a ticket is actually submitted.
   *Trade-off:* the free tier caps daily requests per model — the batch jobs (eval, cluster,
   docs loop) stop cleanly on a `QuotaError` and are meant to run in small passes or with
   billing enabled. Swapping in local Ollama is a one-file change in `llm.py`.

> **As built:** this document is the design rationale. Section 12 maps every stage below to
> the module that implements it, with the command to run it.

---

## 0. Architecture decision — the docs fit in context, so RAG is opt-in

`SugboDoc-Documentation.md` is ~8k tokens. Any model worth using has an 8k+ context window.
So by default the whole doc goes in the prompt, every turn — **no chunking, no vector
store**. A `USE_RAG=1` toggle (`core/retrieval.py`) switches the *answer* prompt to
embedding-cosine section retrieval (top-`RAG_TOP_K`); the verification pass and the eval
judge still see the full docs, so the two modes are interchangeable and the eval scorecard
records which one produced it. Turn it on around 5–10× the current doc size.

```mermaid
flowchart TD
    Q[How big are the docs?] --> A{Fit comfortably in<br/>the model context?}
    A -->|yes — default| F1[Full doc in prompt<br/>no retrieval]
    A -->|USE_RAG=1 / docs 5–10x| F2[Top-K section retrieval<br/>llm.embed + cosine]
    F1 --> GEN[Gemini — grounded answer]
    F2 --> GEN
    GEN --> VER[Verification pass + eval judge<br/>always see the full docs]
    VER --> EVAL[Evaluation harness<br/>scores both modes]

    style F1 fill:#2f855a,stroke:#1a4731,color:#fff
    style EVAL fill:#2b6cb0,stroke:#1a365d,color:#fff
```

The data science in this project is **not** in the retrieval stack. It's in (a) detecting
when a chat failed, (b) generating a useful ticket, and (c) mining failures to prioritise
doc work. Those are §2, §3, §6, §7.

---

## 1. Inference path (per turn) — deliberately simple

```mermaid
flowchart TD
    U[User question] --> H[Prepend last few turns]
    H --> P[Prompt = full docs<br/>+ answer rules + question]
    P --> GEN[Gemini answer model<br/>answer + cite section]
    GEN --> VER[Verification pass<br/>Gemini utility model:<br/>is every sentence in the docs?]
    VER -->|supported| ANS[Answer + section link]
    VER -->|unsupported / no basis| REFUSE["I don't have enough<br/>information in my records"]
    ANS --> FB[Ask: was this helpful?]
    REFUSE --> OFFER[Offer: submit a ticket?<br/>or route to human support]
    FB -->|no| OFFER
    FB -->|yes| DONE[Log success]
    OFFER --> CAP[Failure capture — §2]
    DONE --> LOG[(Chat log)]
    CAP --> LOG

    style VER fill:#2b6cb0,stroke:#1a365d,color:#fff
    style OFFER fill:#2b6cb0,stroke:#1a365d,color:#fff
```

**Why a separate verification pass** — small local models are weak at self-policing "I don't
know". A second, independent Gemini call that checks the draft answer against the docs catches
hallucinations a frontier model would catch inline. Tune its strictness on the eval set (§6). Implemented in `grounding.py`.

**Data science work here**

- The grounding/refusal rubric and few-shot refusal examples in the prompt
- Verification-pass threshold tuning (precision/recall of "this answer is unsupported")
- Latency profiling — two local calls per turn on CPU can be slow

---

## 2. Failure capture — when did the chat fail, and what do we do with it?

```mermaid
flowchart TD
    subgraph Detect
        S1[Bot refused<br/>'not enough information'] --> FAIL
        S2[Thumbs-down] --> FAIL
        S3[User re-asks same thing<br/>2+ times] --> FAIL
        S4[User says 'wrong' / 'not helpful'] --> FAIL
    end
    FAIL[Flag conversation as failed] --> Q[(Doc-gap queue)]
    FAIL --> ASK[Offer the user a ticket]
    ASK -->|yes| GEN[Ticket generation — §3]
    ASK -->|no| Q

    style FAIL fill:#2b6cb0,stroke:#1a365d,color:#fff
```

**Detection: rules only.** The strong signals — the bot's own refusal and a thumbs-down —
need no ML and cover most cases; the softer ones (repeated re-asking, "not helpful"
phrasing) are rules too. Only train a dissatisfaction classifier once the logs have a few
hundred labelled conversations *and* the rules are visibly missing failures.

**Triage was removed.** An LLM triage call (docs-gap / product-bug / out-of-scope) used to
run on every failed chat; it was cut to keep per-conversation model cost to *answer + one
verification pass*. Every failed chat still lands in the doc-gap queue; the ticket is an
extra branch.

**Data science work here**

- Failure-signal design and precision/recall of each signal against human-labelled chats
- Deciding when the rules stop being enough (missed-failure rate over time)

---

## 3. Ticket generation & Jira append (only on user confirmation)

```mermaid
flowchart TD
    C[Failed conversation<br/>+ user said yes] --> DRAFT[Default draft — no model call:<br/>subject = first question]
    DRAFT --> DEDUP[Check recent open tickets<br/>embed + cosine similarity<br/>the ONE time Jira is read]
    DEDUP -->|near-duplicate exists| LINK[Show user the existing ticket]
    DEDUP -->|new| REVIEW[User fills email, subject, summary<br/>+ picks a due date]
    REVIEW --> CREATE["POST /rest/api/3/issue<br/>+ reporter (from email), duedate,<br/>urgency label · drop-and-retry on 400"]
    CREATE --> ID[Return ticket ID to user]
    ID --> LOG[(Log: ticket ID, due_date)]

    style DEDUP fill:#2b6cb0,stroke:#1a365d,color:#fff
```

**The dedup step is the only Jira read in the whole system** — and it's per *submission*,
not per request. Pull the last ~100 open tickets, embed their summaries, compare to the
draft. Stops the queue filling with ten copies of the same bug.

The ticket draft was an LLM call; it's now a deterministic default (subject from the user's
first question, summary left to the user) to save cost. The due date comes from a date
picker — no free-text parsing — and urgency is derived from how soon it is.

**Data science work here**

- Duplicate-detection threshold tuning (precision/recall of "this is a dup")

---

## 4. Docs maintenance loop — "every time I want to update the docs"

```mermaid
flowchart TD
    Q[(Doc-gap queue)] --> CLUS[Cluster the failed questions<br/>HDBSCAN over embeddings]
    CLUS --> RANK[Rank clusters<br/>frequency x how-stuck-the-user-was]
    JIRA[Resolved Jira tickets<br/>bugs fixed / features shipped] --> RANK
    RANK --> PICK[Pick the top gaps this cycle]
    PICK --> DRAFT[Gemini drafts the doc change<br/>grounded in the failed chats + ticket]
    DRAFT --> HUMAN[Human reviews & edits]
    HUMAN --> MERGE[Update SugboDoc-Documentation.md]
    MERGE --> RESCORE[Re-run eval harness]
    RESCORE -->|no regression| SHIP[Ship new docs]
    RESCORE -->|regression| HUMAN

    style CLUS fill:#2b6cb0,stroke:#1a365d,color:#fff
    style RANK fill:#2b6cb0,stroke:#1a365d,color:#fff
    style RESCORE fill:#2b6cb0,stroke:#1a365d,color:#fff
```

This runs on your schedule — weekly, or whenever the queue is worth a pass. Resolved Jira
tickets feed in here (a fixed bug or shipped feature often means a doc is now wrong), which
is the *indirect* path from Jira back to the bot: **Jira → docs → bot**, never Jira → bot.

**Data science work here**

- Clustering failed questions, labelling clusters, ranking by impact
- For each doc change: add a matching eval case *before* merging, so the fix is verified
- Regression tracking — the frozen scorecard re-run on every docs edit

---

## 5. Docs preparation (one-time, already mostly done)

```mermaid
flowchart LR
    V[Tutorial video] --> W[Re-transcribe: faster-whisper<br/>local, free, beats the raw ASR]
    RAW[existing transcript.txt] --> LP[One LLM cleanup pass<br/>Ollama, one-time + glossary]
    W --> LP
    CH[chapters.txt] --> SEG[Split by chapter marks<br/>already human-segmented]
    LP --> SEG
    SEG --> DOC[SugboDoc-Documentation.md<br/>the single source of truth]

    style DOC fill:#2f855a,stroke:#1a4731,color:#fff
```

`chapters.txt` is already a human topic segmentation; the curated markdown is the KB. No
spell-correction pipeline, no TextTiling — see §8.

---

## 6. Evaluation harness — the data science centrepiece

Nothing here is at risk of being "outperformed by another tech" — measurement is what tells
you which tech wins.

```mermaid
flowchart TD
    subgraph Build the eval set
        L[Real questions from logs] --> ES[Gold set:<br/>question + expected doc section<br/>+ ideal answer + expected behaviour]
        S[Synthetic questions<br/>generated from each doc section] --> ES
        HU[Human review of a sample] --> ES
        NEG[Out-of-scope questions<br/>the bot MUST refuse] --> ES
    end

    ES --> A1[Answer correctness & completeness]
    ES --> A2[Groundedness — every claim in the docs]
    ES --> A3[Correct refusal<br/>says 'not enough info' when it should]
    ES --> A4[Ticket-draft quality<br/>edit distance, acceptance rate]
    ES --> A5[Triage accuracy<br/>docs-gap vs bug vs out-of-scope]

    A1 --> J[LLM-as-judge<br/>gemini-2.5-pro, NOT the answer model<br/>+ rubric]
    A2 --> J
    A3 --> J
    J --> CAL[Calibrate vs 40–60 human labels<br/>report Cohen's kappa]
    CAL --> CARD[Scorecard per config]
    A4 --> CARD
    A5 --> CARD
    CARD --> CMP[Compare configs<br/>bootstrap CIs, not point estimates]
    CMP --> GATE{Ship?}

    style J fill:#2b6cb0,stroke:#1a365d,color:#fff
    style CAL fill:#2b6cb0,stroke:#1a365d,color:#fff
    style CMP fill:#2b6cb0,stroke:#1a365d,color:#fff
    style A3 fill:#2b6cb0,stroke:#1a365d,color:#fff
```

**Data science skills exercised**

- Eval-set design, including a **dedicated "must refuse" slice** — the hallucination guard
  is only as good as its test set
- Generation-quality metrics that aren't just vibes: **ticket-draft edit distance and
  acceptance rate**, refusal precision/recall
- LLM-as-judge done properly — rubric, calibration against human labels, Cohen's κ. Use a **different, stronger** model than the answer model for judging (here `gemini-2.5-pro` judging a `gemini-3.6-flash` answerer); keep a fixed 40–60 question human panel per release and report Cohen's κ
- Config comparison with **bootstrap confidence intervals**; multiple-comparison awareness
- Frozen scorecard re-run on every prompt / docs change

**Zero cost:** the custom harness in `eval_run.py` (deterministic checks + LLM-judge +
bootstrap CIs + `--calibrate` for Cohen's κ); human labels in a CSV.

---

## 7. Analytics — mine the failures

```mermaid
flowchart TD
    LOG[(Chat logs)] --> EMB[Embed failed questions<br/>Gemini embeddings]
    EMB --> CLU[Cluster — HDBSCAN]
    CLU --> LBL[Label clusters = real unmet needs]
    LBL --> IMP[Impact score<br/>frequency x severity x recency]
    IMP --> B1[Top clusters → doc-gap queue §4]
    IMP --> B2[Bug-shaped clusters → proactive Jira ticket]
    LOG --> KPI[KPIs<br/>answer rate, refusal rate,<br/>thumbs-up rate, ticket-submit rate,<br/>repeat-question rate]
    KPI --> DRIFT[Weekly: is the question mix shifting?]

    style CLU fill:#2b6cb0,stroke:#1a365d,color:#fff
    style IMP fill:#2b6cb0,stroke:#1a365d,color:#fff
```

Clustering real failed questions is the best way to see *what users actually can't get
answered* and where to spend doc effort. Cheap, unsupervised, not replaced by anything
better.

**Data science skills** — embedding + density clustering, cluster labelling, impact
scoring, coverage-gap analysis, drift checks, product analytics (answer rate, containment,
repeat-question rate).

---

## 8. Techniques deliberately NOT used (and why)

| Not used | Textbook reason to use it | Why it loses here |
|---|---|---|
| **Per-request Jira retrieval / RAG over tickets** | "Feed operational context into every answer" | The bot answers from docs; tickets are a *write* target. Reading tickets per turn adds latency, a sync pipeline, and stale-status risk for zero benefit. Jira reaches the bot only via **Jira → docs → bot**. |
| Vector DB for the docs (default) | "RAG needs embeddings" | Docs are ~8k tokens — the whole thing fits in the prompt. `USE_RAG=1` enables a lightweight local retrieval path (`llm.embed` + cosine, no ChromaDB/FAISS needed) for when the corpus grows; the eval harness scores both modes. |
| Dissatisfaction / sentiment classifier (day one) | Detect failed chats | The bot's own refusal + a thumbs-down button catch most failures with zero ML. Train a classifier only once rules are demonstrably missing failures. |
| Classifier for suggested Jira issue type | Auto-file with the right type | Let the LLM suggest it in the draft; the reviewer corrects it. Track accuracy, don't train a model for a field a human approves anyway. |
| Cross-encoder reranker | Best-in-class reranking | Nothing to rerank — no retrieval in the inference path. |
| TextTiling / embedding topic segmentation | Automatic passage boundaries | `chapters.txt` is already a human segmentation. |
| SymSpell / Levenshtein + seq2seq punctuation restoration | Clean noisy ASR | Re-running Whisper fixes it at the source; one LLM pass handles the rest. |
| NLI entailment model for groundedness | Verify answers are supported | A rubric-based Ollama verification pass is simpler and reuses infra you already have. |
| Fine-tuning / LoRA the local model | Better grounding on your domain | No labelled data yet; hardened prompt + verification pass + tight scope get you further first. Revisit once §7 has produced a few hundred graded answers. |

---

## 9. Zero-cost / local stack

| Layer | Free choice | Note |
|---|---|---|
| Glue / notebooks | Python, `pandas`, `scikit-learn` | — |
| Generation LLM | **Ollama** — small model (~3–4B) for verification + triage, mid model (~8–14B) for answers & ticket drafts | `ollama serve`; keep both pulled |
| LLM-as-judge | **Ollama** — largest model your hardware runs, different from the answer model | expect a weaker judge; keep a human panel |
| Embeddings (dedup + clustering) | Ollama (`nomic-embed-text`) or `sentence-transformers` (`bge-small-en`) | CPU-fine; used offline, not per turn |
| Jira write | Jira Cloud REST API + `requests` | free with any account; called only on ticket submit |
| Re-transcription | `faster-whisper` | one-time, CPU-fine for a ~1 h video |
| NLP | `spaCy`, `nltk` | glossary mining, PII redaction |
| Clustering / analytics | `hdbscan`, `umap-learn` | the failure-mining loop |
| Eval | `promptfoo` (native Ollama provider) or a small custom harness | — |
| Serving | FastAPI + Ollama on one host | chat data stays local |
| Experiment tracking | git + the markdown scorecard; local `mlflow` if you want a UI | — |
| Hardware | ~16 GB RAM for a 14B model at Q4; GPU optional | the one real cost of this path |

---

## 10. Milestone sequence

```mermaid
flowchart LR
    M0[M0<br/>Clean docs<br/>+ 80–120 Q&A eval set<br/>incl. 'must refuse' slice] --> M1[M1<br/>Inference bot<br/>full docs + verification pass]
    M1 --> M2[M2<br/>Eval harness + scorecard]
    M2 --> M3[M3<br/>Failure capture + thumbs feedback<br/>logging live]
    M3 --> M4[M4<br/>Ticket generation + Jira append<br/>with human review]
    M4 --> M5[M5<br/>Failure clustering<br/>→ docs maintenance loop]
    M5 --> M6[M6<br/>Triage model / retrieval<br/>only if the scorecard demands it]
```

Ship a measurable baseline at **M1**; stand up evaluation at **M2** before anything else —
every later change is judged against the frozen scorecard.

---

## 11. Skills-to-stage map

| Stage | Data science competency on display |
|---|---|
| §0 architecture choice | Recognising the docs fit in context — knowing when retrieval is premature |
| §2 failure capture | Failure-signal design, precision/recall per signal, triage classification, knowing when rules beat a model |
| §3 ticket generation | Generation-quality metrics (edit distance, acceptance rate), embedding dedup, threshold tuning |
| §4 docs maintenance | Failure clustering, impact ranking, eval-case-before-merge discipline, regression tracking |
| §6 evaluation | Eval-set design (incl. refusal slice), LLM-judge calibration (κ) with a local judge, bootstrap inference, frozen scorecard |
| §7 analytics | Embedding clustering (HDBSCAN), impact scoring, coverage-gap analysis, drift checks, product analytics |
| §1 inference | Prompt/rubric design measured against eval, verification-pass tuning to compensate for a weaker base model |
| §8 scoping | Judgement about what to leave out — *no per-request Jira retrieval, no vector DB, no classifier for data a human approves* |

The strongest signal is §6 and §8: a rigorous evaluation harness, and the discipline to keep
the inference path trivial and put the intelligence into the feedback loop that improves the
docs.

---

## 12. As built — file map

Every stage above is implemented. Package layout: `core/` (library), `api/` (FastAPI +
Postgres), `evaluation/`, `analytics/`, `scripts/`; `config.py` and `app.py` at the root.
**`docs/PROJECT.md` is the detailed walkthrough** (every file + key functions); this is the index.

### `core/` — the library (imported by everything)

| File | Responsibility | Stage |
|---|---|---|
| `config.py` *(root)* | Paths, model names, thresholds, feature toggles (`USE_RAG`, `LLM_BACKEND`, `DATABASE_URL`), one-time `.env` load | — |
| `core/llm.py` | The one model interface: `generate`, `new_chat`/`Chat.send`, `embed`; SQLite response cache; offline mode; quota-aware `retry` + `QuotaError` | — |
| `core/_gemini_backend.py` | Real Gemini SDK calls (lazy-imported by `llm.py`) | — |
| `core/_mock_backend.py` | Offline deterministic stand-in — no API key / quota | — |
| `core/knowledge.py` | Load docs, split into 60+ `Section`s, assemble the system prompt (full docs, or RAG sections) | §0, §5 |
| `core/retrieval.py` | `USE_RAG` mode: embed sections (`llm.embed`) + cosine rank → top-K | §0 |
| `core/bot.py` | `respond()` — the one answer path: (RAG re-ground) → answer model → verification → refuse-or-answer | §1 |
| `core/grounding.py` | The verification pass (`verify()` → `GroundingVerdict`), always vs full docs | §1 |
| `core/failure_capture.py` | Rule-based `detect_failures()` (no model call — triage was removed for cost) | §2 |
| `core/ticketing.py` | `default_draft()` (no model call — subject = first question), `as_iso_date()` / `urgency_for_date()` for the due-date picker | §3 |
| `core/jira_client.py` | Outbound `create_issue()` — ADF description, `labels`, `duedate` (from a date picker), `reporter` (resolved from the user's email via `resolve_account_id`), drop-and-retry if Jira rejects an optional field; batch reads `list_recent_open_issues` / `list_resolved_issues` | §3, §4 |
| `core/jira_dedup.py` | `find_duplicate()` — embed draft vs open tickets, cosine (the one Jira read) | §3 |
| `core/chatlog.py` | Append/load finished conversations — `logs/chats.jsonl`, or the `chat_logs` table when `DATABASE_URL` is set; + `logs/chats.csv` mirror | feeds §6, §7 |
| `api/db.py` | SQLAlchemy engine + `conversations` / `chat_logs` models — opt-in Postgres persistence for `api/service.py` | §1–§3 |
| `api/db_init.py` / `api/schema.sql` | Create / check / reset the DB schema | setup |
| `core/engine.py` | UI-independent conversation state machine (`chat → feedback → offer_ticket → done`); `serialize()` / `deserialize()` for the session store | §1–§3 |
| `core/cli.py` | Shared `--mock` / `--offline` / `--no-cache` flags for the batch scripts | — |

### Entry points

| Command | What it does | Stage |
|---|---|---|
| `streamlit run app.py` | Streamlit demo UI: full inference path + feedback loop + modal ticket flow + logging | §1–§3 |
| `uvicorn api.service:app` | FastAPI backend — serves the dashboard mockup + floating chat widget (`/`), a markdown docs viewer with section nav (`/documentation`), and the JSON API (`/chat`, `/feedback`, `/tell-me-more`, `/ticket*`, `GET\|DELETE /session/{id}`, `/widget/config`, `/healthz`). Sessions in memory, or Postgres if `DATABASE_URL` is set. Widget shows the greeting on open and renders every reply by diffing `state.messages` | §1–§3 |
| `python -m api.db_init` | Create the `conversations` / `chat_logs` schema (`--check`, `--drop`) | setup |
| `python -m evaluation.eval_run` | Run the pipeline over `eval_set.jsonl`, LLM-judge, write `eval_scorecard.md/.json` (bootstrap CIs; records full-context vs RAG). `--calibrate` → Cohen's κ; `--no-judge` / `--mock` / `--offline` | §6 |
| `python -m evaluation.eval_gen` | Draft synthetic eval questions from each doc section → `evaluation/eval_generated.jsonl` | §6 |
| `python -m analytics.analytics_kpis` | Containment / thumbs / refusal / repeat-question KPIs from the log (no model calls) | §7 |
| `python -m analytics.analytics_cluster` | Embed failed questions → HDBSCAN → label → impact score → `logs/doc_gap_queue.json` | §7 |
| `python -m analytics.docs_loop` | Top gaps + resolved Jira → model drafts a doc change → `doc_proposals/` | §4 |
| `python -m analytics.seed_demo_log` | Write synthetic conversations so the analytics/loop scripts are demoable | — |
| `python -m scripts.llm_cache` | Inspect / `--clear` the response cache | — |
| `python -m core.chatlog` | Rebuild `logs/chats.csv` from the primary store (a flat CSV mirror is also written on every log) | — |
| `python -m scripts.jira_check` | Standalone connectivity + createmeta field check (`--create-test` files a throwaway) | setup |
| `pytest` | 62 offline tests (mock backend, tmp paths; DB tests use throwaway SQLite) | — |

### Data files

| File | Tracked? | Notes |
|---|---|---|
| `docs/SugboDoc-Documentation.md` | gitignored | the single source of truth |
| `docs/system-prompt.md` | gitignored | original prompt (see note below) |
| `evaluation/eval_set.jsonl` | yes | 90 hand-authored cases; 61 answerable + 29 must-refuse |
| `evaluation/eval_scorecard.md` | yes | committed baseline — diff it on every prompt/docs change (marks backend + retrieval mode; a `mock` card is a plumbing check, not a score) |
| `evaluation/eval_scorecard.json` | gitignored | machine-readable scorecard + per-case detail |
| `web/index.html` | yes | static SugboDoc dashboard mockup + floating chat widget, served by `api/service.py` |
| `logs/chats.jsonl` | gitignored | append-only conversation log (unless `DATABASE_URL` → `chat_logs` table) |
| `logs/chats.csv` | gitignored | flat one-row-per-conversation mirror, written on every log regardless of store |
| `api/schema.sql` | yes | raw DDL for the Postgres backend — mirror of `api/db.py` |
| `logs/llm_cache.sqlite` | gitignored | response cache (warm it once, then `--offline`) |
| `logs/doc_gap_queue.json` | gitignored | impact-ranked output of `analytics_cluster.py` |
| `doc_proposals/*.md` | gitignored | draft doc changes for human review |

### The loop, end to end

```mermaid
flowchart LR
    APP[app.py / service.py] -->|every conversation| LOG[(chat log — chats.jsonl or chat_logs table)]
    LOG --> KPI[analytics_kpis.py]
    LOG --> CLU[analytics_cluster.py] --> Q[(doc_gap_queue.json)]
    JIRA[resolved Jira issues] --> DL[docs_loop.py]
    Q --> DL --> PROP[doc_proposals/*.md]
    PROP -->|human edits + merges| DOCS[(SugboDoc-Documentation.md)]
    DOCS --> EVAL[eval_run.py] --> CARD[(eval_scorecard.md)]
    CARD -->|no regression| DOCS
    DOCS --> APP

    style CLU fill:#2b6cb0,stroke:#1a365d,color:#fff
    style EVAL fill:#2b6cb0,stroke:#1a365d,color:#fff
    style DL fill:#2b6cb0,stroke:#1a365d,color:#fff
```

### First run

```
pip install -r requirements-dev.txt
pytest                                   # 62 offline tests (~2s)

cp .env.example .env                     # add GEMINI_API_KEY (+ JIRA_* for ticketing)
streamlit run app.py                     #  or:  LLM_BACKEND=mock streamlit run app.py

# offline demo of the maintenance side (no API needed with --mock):
python -m analytics.seed_demo_log
python -m analytics.analytics_kpis
python -m analytics.analytics_cluster --mock
python -m analytics.docs_loop --mock

# the JSON backend + dashboard mockup + widget:
pip install -r requirements-service.txt
uvicorn api.service:app --reload         #  http://127.0.0.1:8000  (sessions in memory)

# ...or persist sessions + chat logs to PostgreSQL:
export DATABASE_URL=postgresql://user:pass@localhost:5432/sugbodoc
python -m api.db_init                    # create conversations + chat_logs
uvicorn api.service:app --reload

# try RAG mode:
USE_RAG=1 python -m evaluation.eval_run --mock --no-judge --limit 10
```

**Free-tier note:** Gemini caps requests/day per model. `eval_run.py` is ~2 calls/case
(≈180 for the full 90-case set); run it with `--limit`, `--no-judge`, enable billing, or
point `GEMINI_MODEL` / `GEMINI_JUDGE_MODEL` at models that still have quota. Every response
is cached to `logs/llm_cache.sqlite`, so a second run of the same config is free — and
`--offline` will then serve entirely from that cache. Every batch script stops cleanly on
`QuotaError` (the eval writes a partial scorecard). `--mock` skips the API entirely.

---

## Note on `system-prompt.md`

The prompt you saved has an **"Operational Awareness (Jira Integration)"** clause that
assumes retrieved Jira tickets appear in `<retrieved_context>`. Under this architecture the
bot never sees tickets, so that clause is dead weight — it can be dropped, and the
`<retrieved_context>` block simplifies to doc passages only. Say the word and I'll trim it.
