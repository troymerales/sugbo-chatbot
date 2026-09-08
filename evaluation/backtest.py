"""
Backtesting engine for the SugboDoc support chatbot.

The notebook (`jira_backtest.ipynb`) is the experiment surface; this module holds
the reusable pieces so the notebook stays readable and the logic is unit-tested.

Design rules (see evaluation/README.md):

  * The chatbot is the *production* one. `run_chatbot()` calls
    `core.bot.fresh_chat()` + `core.bot.respond()` — the exact path the Streamlit
    widget and FastAPI backend use. No prompt, model or retrieval setting is
    overridden here. The chatbot model is whatever `config.ANSWER_MODEL` is.

  * The evaluator is a *separate* role: a different model (default
    `config.JUDGE_MODEL`), its own strict prompt, and it never sees the
    historical `resolved` flag.

  * Everything is incremental and resumable. Results are keyed by `ticket_id`
    and appended to CSV after every batch; re-running only processes what is
    missing. A daily-quota error stops the run cleanly with partial results
    saved.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

import config
from core import bot, llm

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

PKG_DIR = Path(__file__).resolve().parent
DATA_DIR = PKG_DIR / "data"
RESULTS_DIR = PKG_DIR / "results"

# Real export goes here (git-ignored); the committed sample is the fallback so
# the notebook runs end-to-end on a fresh clone.
TICKETS_PATH = DATA_DIR / "jira_tickets.csv"
TICKETS_SAMPLE_PATH = DATA_DIR / "jira_tickets.sample.csv"

CLASSIFICATIONS = ("FULL", "PARTIAL", "HUMAN")

# Columns the chatbot must never see (would-be data leakage — see README §Leakage).
LEAKY_COLUMNS = ("resolved", "resolution", "status", "comments", "resolved_at")


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class BacktestConfig:
    """Everything that identifies one run. Persisted alongside the results."""

    run_id: str
    chatbot_model: str = config.ANSWER_MODEL          # read-only mirror of prod
    evaluator_model: str = config.JUDGE_MODEL
    batch_size: int = 50                              # chatbot-phase checkpoint cadence
    eval_batch_size: int = 15                         # tickets judged per evaluator call
    evaluator_temperature: float = 0.0
    max_workers: int = 1                              # 1 = strictly sequential
    limit: int | None = None                         # cap tickets (smoke tests)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def as_dict(self) -> dict:
        d = {
            "run_id": self.run_id,
            "chatbot_model": self.chatbot_model,
            "evaluator_model": self.evaluator_model,
            "batch_size": self.batch_size,
            "eval_batch_size": self.eval_batch_size,
            "evaluator_temperature": self.evaluator_temperature,
            "max_workers": self.max_workers,
            "limit": self.limit,
            "started_at": self.started_at,
        }
        d.update(production_chatbot_config())
        return d


def production_chatbot_config() -> dict:
    """Snapshot of the config that governs chatbot behaviour, for the record.

    Read straight from `config` and a throwaway `fresh_chat()` — never set here.
    """
    probe = bot.fresh_chat()
    return {
        "prod_answer_model": config.ANSWER_MODEL,
        "prod_utility_model": config.UTILITY_MODEL,
        "prod_chat_temperature": probe.temperature,
        "prod_verify_answers": config.VERIFY_ANSWERS,
        "prod_use_rag": config.USE_RAG,
        "prod_rag_top_k": config.RAG_TOP_K if config.USE_RAG else None,
        "prod_llm_backend": config.LLM_BACKEND,
        "prod_refusal_marker": config.REFUSAL_MARKER,
    }


# --------------------------------------------------------------------------- #
# 1. Load + validate the historical dataset
# --------------------------------------------------------------------------- #

# Real Jira CSV exports vary in header casing/wording. These map (lower-cased,
# stripped) source headers onto the canonical names the harness uses.
_ID_ALIASES = ("ticket_id", "issue id", "issue key", "issue_id", "issue_key", "key", "id")
_SUMMARY_ALIASES = ("summary", "title", "subject", "name")
# Outcome / later-known fields -> renamed to historical_* (kept for analysis,
# never shown to the chatbot or the evaluator).
_RESOLVED_ALIASES = ("resolved", "resolution", "resolution_status")
_STATUS_ALIASES = ("status", "state")
# Carried through for slicing (Graph 5) when present.
_PASSTHROUGH_ALIASES = {
    "issue_type": ("issue type", "issue_type", "type", "issuetype"),
    "priority": ("priority",),
    "project": ("project", "project key", "project name"),
    "category": ("category", "component", "components"),
    "created_at": ("created", "created_at", "created date"),
}


def resolve_tickets_path() -> Path:
    """Prefer a real export (any `jira_tickets*.csv` that is not the sample),
    else fall back to the committed sample."""
    if TICKETS_PATH.exists():
        return TICKETS_PATH
    reals = sorted(p for p in DATA_DIR.glob("jira_tickets*.csv")
                   if p.name != TICKETS_SAMPLE_PATH.name)
    return reals[0] if reals else TICKETS_SAMPLE_PATH


def _pick(cols_lower: dict[str, str], aliases: Iterable[str]) -> str | None:
    for a in aliases:
        if a in cols_lower:
            return cols_lower[a]
    return None


def load_tickets(path: str | Path | None = None) -> pd.DataFrame:
    """Load a historical Jira export and normalise its columns.

    Accepts common Jira CSV header variants (``Issue id`` / ``Key`` -> ``ticket_id``,
    ``Summary``/``Title`` -> ``summary``, ``Resolution``/``Status`` ->
    ``historical_resolved`` / ``historical_status``). Only ``ticket_id`` +
    ``summary`` are required. Extra columns (issue_type, priority, ...) are kept.
    """
    path = Path(path) if path else resolve_tickets_path()
    df = pd.read_csv(path, dtype=str).fillna("")
    cols_lower = {c.strip().lower(): c for c in df.columns}

    id_col = _pick(cols_lower, _ID_ALIASES)
    sum_col = _pick(cols_lower, _SUMMARY_ALIASES)
    if not id_col or not sum_col:
        raise ValueError(
            f"{path.name}: could not find an id column ({_ID_ALIASES}) and/or a "
            f"summary column ({_SUMMARY_ALIASES}). Columns present: {list(df.columns)}"
        )

    rename = {id_col: "ticket_id", sum_col: "summary"}
    res_col = _pick(cols_lower, _RESOLVED_ALIASES)
    if res_col:
        rename[res_col] = "historical_resolved"
    status_col = _pick(cols_lower, _STATUS_ALIASES)
    if status_col and status_col != res_col:
        rename[status_col] = "historical_status"
    for canon, aliases in _PASSTHROUGH_ALIASES.items():
        src = _pick(cols_lower, aliases)
        if src and src not in rename:
            rename[src] = canon
    df = df.rename(columns=rename)
    # drop any duplicate-named columns the rename may have collided
    df = df.loc[:, ~df.columns.duplicated()]

    df["ticket_id"] = df["ticket_id"].astype(str).str.strip()
    df["summary"] = df["summary"].astype(str).str.strip()
    if "historical_resolved" in df.columns:
        resolved = df["historical_resolved"].map(_coerce_bool)
        # Jira convention: a blank Resolution means unresolved — fall back to Status.
        if "historical_status" in df.columns:
            resolved = resolved.where(
                df["historical_resolved"].astype(str).str.strip() != "",
                df["historical_status"].map(_coerce_bool),
            )
        df["historical_resolved"] = resolved

    df.attrs["source_path"] = str(path)
    df.attrs["is_sample"] = path.name == TICKETS_SAMPLE_PATH.name
    return df.reset_index(drop=True)


def _coerce_bool(v) -> bool | None:
    s = str(v).strip().lower()
    if s in {"true", "1", "yes", "y", "resolved", "done", "closed", "fixed",
             "complete", "completed", "shipped"}:
        return True
    if s in {"false", "0", "no", "n", "unresolved", "open", "to do", "todo",
             "in progress", "backlog", "won't do", "wont do"}:
        return False
    return None


def validate_tickets(df: pd.DataFrame) -> dict:
    """Cheap data-quality report for Section 3 of the notebook."""
    report = {
        "rows": len(df),
        "unique_ticket_ids": df["ticket_id"].nunique(),
        "duplicate_ticket_ids": int(df["ticket_id"].duplicated().sum()),
        "blank_summaries": int((df["summary"].str.len() == 0).sum()),
        "blank_ticket_ids": int((df["ticket_id"].str.len() == 0).sum()),
        "columns": list(df.columns),
    }
    if "historical_resolved" in df.columns:
        vc = df["historical_resolved"].value_counts(dropna=False)
        report["historical_resolved_counts"] = {str(k): int(v) for k, v in vc.items()}
    # Raw outcome columns still carrying their original name (load_tickets renames
    # the ones it recognises to historical_*; anything left is a real risk).
    leaked = [c for c in df.columns
              if c.strip().lower() in LEAKY_COLUMNS and not c.startswith("historical_")]
    report["potential_leak_columns"] = leaked
    if "historical_status" in df.columns:
        vc = df["historical_status"].value_counts(dropna=False)
        report["historical_status_counts"] = {str(k): int(v) for k, v in vc.items()}
    return report


def chatbot_input(row: pd.Series) -> str:
    """Exactly what the chatbot receives for a ticket: the summary, nothing else.

    Deliberately isolated so it is obvious that no resolution/outcome data and no
    later-added context reaches the model.
    """
    return str(row["summary"]).strip()


# --------------------------------------------------------------------------- #
# 2. Run the production chatbot over one ticket
# --------------------------------------------------------------------------- #

def run_chatbot(summary: str, *, verify: bool | None = None) -> dict:
    """Send one historical ticket summary through the real chatbot pipeline.

    A fresh single-turn `Chat` per ticket — the same object the widget builds for
    a new conversation. Returns a plain dict (CSV/JSON friendly).

    `verify` temporarily overrides `config.VERIFY_ANSWERS` for this one call — only
    used by the verification-pass ablation (`run_backtest(..., verify_answers=...)`).
    Leave it `None` to match production.
    """
    started = time.time()
    _verify_saved = config.VERIFY_ANSWERS
    if verify is not None:
        config.VERIFY_ANSWERS = verify
    try:
        chat = bot.fresh_chat()
        result = bot.respond(chat, summary)
        return {
            "chatbot_response": result.text,
            "chatbot_refused": bool(result.refused),
            "grounding_checked": bool(result.grounding.checked),
            "grounding_supported": bool(result.grounding.supported),
            "grounding_reason": result.grounding.reason,
            "chatbot_model": chat.model,
            "chatbot_error": "",
            "latency_s": round(time.time() - started, 2),
        }
    except llm.QuotaError:
        raise
    except Exception as exc:  # noqa: BLE001 - record and move on
        return {
            "chatbot_response": "",
            "chatbot_refused": False,
            "grounding_checked": False,
            "grounding_supported": False,
            "grounding_reason": "",
            "chatbot_model": config.ANSWER_MODEL,
            "chatbot_error": f"{type(exc).__name__}: {exc}",
            "latency_s": round(time.time() - started, 2),
        }
    finally:
        config.VERIFY_ANSWERS = _verify_saved


# --------------------------------------------------------------------------- #
# 3. Evaluate one chatbot response  (separate role, separate prompt, strict)
# --------------------------------------------------------------------------- #

EVALUATOR_SYSTEM = """\
You are a strict support-operations reviewer. You decide whether an AI support \
assistant's reply to a helpdesk ticket could plausibly have RESOLVED that ticket \
with NO human agent involved.

You are given only:
  - the original ticket summary (what the user asked at the time)
  - the assistant's reply

You are NOT told whether the ticket was actually resolved. Do not guess or assume \
any outcome. Judge only the reply on its own merits.

Classify into exactly one of:

FULL     - The reply is correct, specific, and self-sufficient. A reasonable \
support workflow could end here: the user has what they need and no human must \
take any further action. Only for clear how-to / informational requests that the \
reply actually answers.

PARTIAL  - The reply gives real, on-topic help (troubleshooting steps, relevant \
information, a partial answer) but a human would still very likely need to step \
in to finish, verify, or act.

HUMAN    - The reply cannot reasonably close the ticket. Use this when the request \
needs privileged access, a manual change by staff, a decision, investigation, or \
data the assistant lacks; OR when the reply is a refusal / "I don't have that \
information"; OR when the reply is vague, generic, wrong, or hallucinated.

Rules:
  - A refusal or "not enough information" reply is always HUMAN.
  - Bug reports, incidents, access/permission requests, billing/subscription \
changes, data migrations, and report requests are HUMAN unless the reply fully \
and correctly resolves them without staff action.
  - Be conservative. If in doubt between two labels, pick the one requiring more \
human involvement.

Return ONLY a JSON object, no prose, no markdown:
{"classification": "FULL" | "PARTIAL" | "HUMAN", "reason": "<one or two sentences>"}
"""

_EVAL_USER_TEMPLATE = """\
TICKET SUMMARY:
{summary}

ASSISTANT REPLY:
{response}

Classify now. JSON only.
"""


def _parse_eval_json(raw: str) -> dict | None:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        obj = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return None
    cls = str(obj.get("classification", "")).strip().upper()
    if cls not in CLASSIFICATIONS:
        return None
    return {"classification": cls, "reason": str(obj.get("reason", "")).strip()}


def evaluate_response(
    summary: str,
    chatbot_response: str,
    *,
    model: str | None = None,
    temperature: float = 0.0,
) -> dict:
    """Judge one response. Retries a malformed reply once, then falls back to
    HUMAN (the conservative label) so the pipeline always terminates."""
    model = model or config.JUDGE_MODEL
    if not str(chatbot_response).strip():
        return {
            "classification": "HUMAN",
            "evaluation_reason": "No chatbot response was produced for this ticket.",
            "evaluator_model": model,
            "evaluator_fallback": True,
        }

    prompt = _EVAL_USER_TEMPLATE.format(summary=summary, response=chatbot_response)
    for attempt in range(2):
        raw = llm.generate(
            prompt,
            system=EVALUATOR_SYSTEM,
            model=model,
            temperature=temperature,
            json_mode=True,
        )
        parsed = _parse_eval_json(raw)
        if parsed:
            return {
                "classification": parsed["classification"],
                "evaluation_reason": parsed["reason"],
                "evaluator_model": model,
                "evaluator_fallback": False,
            }
    return {
        "classification": "HUMAN",
        "evaluation_reason": (
            "Evaluator did not return a valid classification after 2 attempts; "
            "defaulted to HUMAN (conservative)."
        ),
        "evaluator_model": model,
        "evaluator_fallback": True,
    }


# --------------------------------------------------------------------------- #
# 3b. Batched evaluator  — many tickets per call to spare the daily quota
# --------------------------------------------------------------------------- #
#
# The evaluator is *our* component, not the production chatbot, so there is no
# fidelity constraint on how it is prompted. Judging N tickets in one request
# cuts evaluator calls ~Nx. Guardrails: every verdict must echo its ticket_id,
# the count and id-set are validated, and any missing / malformed / bad-label
# item is re-judged individually via evaluate_response() (which itself falls
# back to HUMAN). So a lazy batch degrades to the single-item path, never to
# silently dropped tickets.

EVALUATOR_BATCH_SYSTEM = EVALUATOR_SYSTEM.rsplit("Return ONLY", 1)[0] + """\
You will be given SEVERAL tickets, each with an id. Judge each one independently
on its own merits, using the rules above.

Return ONLY a JSON array — no prose, no markdown — with exactly one object per
ticket, in any order:
[{"ticket_id": "<id>", "classification": "FULL" | "PARTIAL" | "HUMAN", "reason": "<one or two sentences>"}]
"""

_BATCH_ITEM_TEMPLATE = """\
----- TICKET {ticket_id} -----
SUMMARY: {summary}
ASSISTANT REPLY: {response}
"""


def _render_batch_prompt(items: list[dict]) -> str:
    body = "\n".join(
        _BATCH_ITEM_TEMPLATE.format(
            ticket_id=it["ticket_id"], summary=it["summary"], response=it["chatbot_response"]
        )
        for it in items
    )
    return (
        f"Judge the following {len(items)} tickets. Return a JSON array with one "
        f"object per ticket, each echoing its ticket_id.\n\n{body}\n\nJSON array only."
    )


def _parse_batch_json(raw: str, expected_ids: set[str]) -> dict[str, dict]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
    try:
        start, end = text.index("["), text.rindex("]") + 1
        arr = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return {}
    out: dict[str, dict] = {}
    for obj in arr if isinstance(arr, list) else []:
        if not isinstance(obj, dict):
            continue
        tid = str(obj.get("ticket_id", "")).strip()
        cls = str(obj.get("classification", "")).strip().upper()
        if tid in expected_ids and cls in CLASSIFICATIONS:
            out[tid] = {"classification": cls, "reason": str(obj.get("reason", "")).strip()}
    return out


def evaluate_batch(
    items: list[dict],
    *,
    model: str | None = None,
    temperature: float = 0.0,
) -> dict[str, dict]:
    """Judge a list of ``{ticket_id, summary, chatbot_response}`` in one call.

    Returns ``{ticket_id: verdict}`` for every input item. Items with an empty
    response, and any the batch call drops or mislabels, are resolved through
    ``evaluate_response`` individually.
    """
    model = model or config.JUDGE_MODEL
    verdicts: dict[str, dict] = {}

    answered = []
    for it in items:
        if str(it.get("chatbot_response", "")).strip():
            answered.append(it)
        else:
            verdicts[it["ticket_id"]] = {
                "classification": "HUMAN",
                "evaluation_reason": "No chatbot response was produced for this ticket.",
                "evaluator_model": model,
                "evaluator_fallback": True,
            }

    if answered:
        expected = {it["ticket_id"] for it in answered}
        raw = llm.generate(
            _render_batch_prompt(answered),
            system=EVALUATOR_BATCH_SYSTEM,
            model=model,
            temperature=temperature,
            json_mode=True,
        )
        parsed = _parse_batch_json(raw, expected)
        for tid, v in parsed.items():
            verdicts[tid] = {
                "classification": v["classification"],
                "evaluation_reason": v["reason"],
                "evaluator_model": model,
                "evaluator_fallback": False,
            }
        # stragglers -> individual judgement (never left unjudged)
        for it in answered:
            if it["ticket_id"] not in verdicts:
                verdicts[it["ticket_id"]] = evaluate_response(
                    it["summary"], it["chatbot_response"],
                    model=model, temperature=temperature,
                )
    return verdicts


# --------------------------------------------------------------------------- #
# 4. Incremental persistence + resumable batch drivers
# --------------------------------------------------------------------------- #

def _load_done_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        return set(pd.read_csv(path, dtype=str)["ticket_id"].str.strip())
    except (pd.errors.EmptyDataError, KeyError):
        return set()


def _append_rows(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(path, mode="a", header=not path.exists(), index=False)


def _read_csv_or_empty(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=str)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _batches(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), max(size, 1)):
        yield items[i:i + size]


def run_backtest(
    tickets: pd.DataFrame,
    cfg: BacktestConfig,
    *,
    responses_path: Path | None = None,
    verify_answers: bool | None = None,
    progress: Callable[[str], None] = print,
) -> pd.DataFrame:
    """Phase 1: chatbot responses for every ticket not already done.

    Safe to interrupt and re-run. Returns the full responses frame from disk.

    `verify_answers` overrides `config.VERIFY_ANSWERS` for the whole run — for the
    ablation only. Point `responses_path` at a separate file (e.g.
    ``chatbot_responses_noverify.csv``) so it doesn't mix with the production run.
    """
    responses_path = responses_path or (RESULTS_DIR / "chatbot_responses.csv")
    done = _load_done_ids(responses_path)

    todo = tickets[~tickets["ticket_id"].isin(done)].copy()
    if cfg.limit is not None:
        todo = todo.head(cfg.limit)

    progress(
        f"[backtest] {len(done)} already done, {len(todo)} to process "
        f"(model={cfg.chatbot_model}, batch={cfg.batch_size}, workers={cfg.max_workers})"
    )

    rows_iter = list(todo.itertuples(index=False))
    cols = list(todo.columns)
    processed = 0
    try:
        for bi, batch in enumerate(_batches(rows_iter, cfg.batch_size), start=1):
            batch_rows = _run_chatbot_batch(batch, cols, cfg, verify_answers)
            _append_rows(responses_path, batch_rows)
            processed += len(batch_rows)
            progress(f"[backtest] batch {bi}: +{len(batch_rows)} (total {len(done) + processed})")
    except llm.QuotaError as exc:
        progress(f"[backtest] STOPPED on quota — {processed} new rows saved. Resume later.\n{exc}")
    except llm.LLMError as exc:
        progress(f"[backtest] STOPPED on a model error — {processed} new rows saved. "
                 f"Resume to continue.\n{exc}")

    out = _read_csv_or_empty(responses_path)
    # Return only the tickets this call was asked about — not the whole accumulated
    # file — so the evaluator phase judges exactly this ticket set.
    if not out.empty:
        out = out[out["ticket_id"].isin(tickets["ticket_id"])].reset_index(drop=True)
    return out


def _run_chatbot_batch(batch: list, cols: list[str], cfg: BacktestConfig,
                       verify_answers: bool | None = None) -> list[dict]:
    def one(rec) -> dict:
        row = pd.Series(rec, index=cols)
        out = run_chatbot(chatbot_input(row), verify=verify_answers)
        out.update(
            ticket_id=row["ticket_id"],
            summary=row["summary"],
            run_id=cfg.run_id,
            answered_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        return out

    if cfg.max_workers <= 1:
        return [one(r) for r in batch]

    # Concurrency is only an infrastructure-level speed-up: each ticket still
    # gets its own fresh single-turn Chat, so chatbot behaviour is unchanged.
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=cfg.max_workers) as pool:
        futs = {pool.submit(one, r): r for r in batch}
        for fut in as_completed(futs):
            results.append(fut.result())
    return results


def run_evaluation(
    responses: pd.DataFrame,
    cfg: BacktestConfig,
    *,
    evaluations_path: Path | None = None,
    progress: Callable[[str], None] = print,
) -> pd.DataFrame:
    """Phase 2: classify every response not already judged. Resumable."""
    evaluations_path = evaluations_path or (RESULTS_DIR / "evaluations.csv")
    done = _load_done_ids(evaluations_path)

    todo = responses[~responses["ticket_id"].isin(done)].copy()
    progress(f"[evaluate] {len(done)} already judged, {len(todo)} to judge "
             f"(model={cfg.evaluator_model}, {cfg.eval_batch_size}/call)")

    if "chatbot_response" not in todo.columns:
        todo["chatbot_response"] = ""
    items = todo[["ticket_id", "summary", "chatbot_response"]].fillna("").to_dict("records")
    processed = 0
    try:
        # One evaluator call per eval-batch; persist right after so a quota stop
        # mid-run never loses a completed batch.
        for bi, batch in enumerate(_batches(items, cfg.eval_batch_size), start=1):
            verdicts = evaluate_batch(
                batch, model=cfg.evaluator_model, temperature=cfg.evaluator_temperature,
            )
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            rows = [
                {**v, "ticket_id": tid, "run_id": cfg.run_id, "evaluated_at": now}
                for tid, v in verdicts.items()
            ]
            _append_rows(evaluations_path, rows)
            processed += len(rows)
            fb = sum(1 for v in verdicts.values() if v.get("evaluator_fallback"))
            progress(f"[evaluate] call {bi}: +{len(rows)} judged"
                     f"{f' ({fb} fell back to single)' if fb else ''} "
                     f"(total {len(done) + processed})")
    except llm.QuotaError as exc:
        progress(f"[evaluate] STOPPED on quota — {processed} new rows saved. Resume later.\n{exc}")
    except llm.LLMError as exc:
        progress(f"[evaluate] STOPPED on a model error — {processed} new rows saved. "
                 f"Resume to continue.\n{exc}")

    return _read_csv_or_empty(evaluations_path)


# --------------------------------------------------------------------------- #
# 5. Merge + metrics
# --------------------------------------------------------------------------- #

_DOC_STOP = set(
    "a an the to i want so that of in on for with my our as be can could would how do "
    "does is are was were and or at it this these those also able more new not".split()
)


def _doc_tokens(s: str) -> set[str]:
    import re

    return {w for w in re.findall(r"[a-z]+", str(s).lower())
            if w not in _DOC_STOP and len(w) > 2}


def doc_overlap_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Rule-based, **no-LLM** proxy for 'how close is this ticket to anything
    documented': token overlap between each ticket summary and every KB section.

    NOT the chatbot's retrieval (production runs full-context). It's a transparent
    signal for the failure analysis and the `likely_misses` check. Returns
    `ticket_id, doc_overlap (0..1), nearest_doc_sections`.
    """
    from core import knowledge

    secs = [(s.title, _doc_tokens(s.title + " " + s.body))
            for s in knowledge.content_sections()]
    rows = []
    for r in frame.itertuples(index=False):
        q = _doc_tokens(getattr(r, "summary", ""))
        scored = sorted(((len(q & t) / len(q) if q else 0.0, title)
                         for title, t in secs), reverse=True)
        rows.append({
            "ticket_id": r.ticket_id,
            "doc_overlap": round(scored[0][0], 3) if scored else 0.0,
            "nearest_doc_sections": "; ".join(
                f"{title} ({v:.0%})" for v, title in scored[:3] if v > 0
            ) or "(no section overlaps)",
        })
    return pd.DataFrame(rows)


def likely_misses(results: pd.DataFrame, *, min_overlap: float = 0.25) -> pd.DataFrame:
    """Refused tickets whose summary has high lexical overlap with the docs — the
    documentation may well cover these, so the refusal is a candidate *miss*
    (retrieval / prompt problem), not an appropriate decline. Actionable output.
    """
    if "doc_overlap" not in results.columns or "chatbot_refused" not in results.columns:
        return pd.DataFrame()
    refused = _truthy(results["chatbot_refused"])
    hit = pd.to_numeric(results["doc_overlap"], errors="coerce").fillna(0) >= min_overlap
    cols = [c for c in ("ticket_id", "classification", "doc_overlap",
                        "nearest_doc_sections", "summary") if c in results.columns]
    return (results[refused & hit][cols]
            .sort_values("doc_overlap", ascending=False).reset_index(drop=True))


def build_results(
    tickets: pd.DataFrame,
    responses: pd.DataFrame,
    evaluations: pd.DataFrame,
    *,
    add_doc_overlap: bool = False,
) -> pd.DataFrame:
    """One row per evaluated ticket: ticket metadata + response + classification.

    `add_doc_overlap` also merges the rule-based `doc_overlap` /
    `nearest_doc_sections` columns (no LLM — see `doc_overlap_frame`).
    """
    keep_tickets = [c for c in tickets.columns if c not in ("summary",)]
    merged = (
        tickets[keep_tickets]
        .merge(responses.drop(columns=["run_id"], errors="ignore"),
               on="ticket_id", how="inner")
        .merge(evaluations[["ticket_id", "classification", "evaluation_reason",
                            "evaluator_model", "evaluator_fallback"]],
               on="ticket_id", how="inner")
    )
    if "historical_resolved" in merged.columns:
        merged["historical_resolved"] = merged["historical_resolved"].map(_coerce_bool)
    merged["summary_length"] = merged["summary"].str.len().astype(int)
    if add_doc_overlap and "summary" in merged.columns:
        try:
            ov = doc_overlap_frame(merged[["ticket_id", "summary"]])
            merged = merged.merge(ov, on="ticket_id", how="left")
        except Exception:  # noqa: BLE001 — enrichment is best-effort
            pass
    return merged


def compare_verification(with_verify: pd.DataFrame,
                         without_verify: pd.DataFrame) -> pd.DataFrame:
    """Side-by-side of the two ablation runs (VERIFY_ANSWERS on vs off), keyed by
    ticket_id. Shows where the verification pass changed a drafted answer into a
    refusal — and lets you judge whether those were real hallucinations or
    over-caution.
    """
    a = with_verify[["ticket_id", "chatbot_refused", "chatbot_response"]].rename(
        columns={"chatbot_refused": "refused_verify_on", "chatbot_response": "resp_verify_on"})
    b = without_verify[["ticket_id", "chatbot_refused", "chatbot_response"]].rename(
        columns={"chatbot_refused": "refused_verify_off", "chatbot_response": "resp_verify_off"})
    m = a.merge(b, on="ticket_id", how="inner")
    m["downgraded_by_verify"] = (
        _truthy(m["refused_verify_on"]) & ~_truthy(m["refused_verify_off"])
    )
    return m


def wilson_ci(successes: int, n: int, *, z: float = 1.959963985) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion (default z = 1.96 → 95%).

    Used for the deflection rate: with n=33 and 2 successes the normal
    approximation is useless, and this is the standard fix. Returns (low, high),
    each rounded to 4 dp and clamped to [0, 1].
    """
    if n <= 0:
        return (0.0, 0.0)
    import math

    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def _truthy(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})


def _nonblank(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip().str.lower()
    return ~s.isin({"", "nan", "none"})


def calculate_metrics(results: pd.DataFrame, cfg: BacktestConfig | None = None) -> dict:
    """Headline numbers. `potential_deflection_rate` = FULL / evaluated."""
    total = len(results)
    counts = results["classification"].value_counts().to_dict()
    full = int(counts.get("FULL", 0))
    partial = int(counts.get("PARTIAL", 0))
    human = int(counts.get("HUMAN", 0))

    metrics = {
        "total_tickets": total,
        "full": full,
        "partial": partial,
        "human": human,
        "potential_deflection_rate": round(full / total, 4) if total else 0.0,
        "deflection_ci95_low": wilson_ci(full, total)[0],
        "deflection_ci95_high": wilson_ci(full, total)[1],
        "partial_assistance_rate": round(partial / total, 4) if total else 0.0,
        "human_required_rate": round(human / total, 4) if total else 0.0,
        "evaluator_fallback_count": int(
            _truthy(results.get("evaluator_fallback", pd.Series(dtype=str))).sum()
        ),
        "chatbot_error_count": int(
            _nonblank(results.get("chatbot_error", pd.Series(dtype=str))).sum()
        ),
    }

    # --- cost + latency, reported as first-class results -------------------- #
    verify_on = bool(cfg and cfg.as_dict().get("prod_verify_answers", True))
    eval_bs = int(cfg.eval_batch_size) if cfg else 15
    metrics["est_chatbot_calls"] = total * (2 if verify_on else 1)
    metrics["est_evaluator_calls"] = -(-total // max(eval_bs, 1)) if total else 0
    lat = pd.to_numeric(results.get("latency_s", pd.Series(dtype=float)), errors="coerce").dropna()
    if len(lat):
        metrics["latency_s_p50"] = round(float(lat.quantile(0.50)), 2)
        metrics["latency_s_p95"] = round(float(lat.quantile(0.95)), 2)
        metrics["latency_s_mean"] = round(float(lat.mean()), 2)
        metrics["chatbot_wall_time_s"] = round(float(lat.sum()), 1)

    # --- likely misses: refused, but the docs seem to cover it ------------- #
    lm = likely_misses(results)
    metrics["likely_miss_count"] = int(len(lm))
    if len(lm):
        metrics["likely_miss_ticket_ids"] = [str(x) for x in lm["ticket_id"].tolist()]

    if "historical_resolved" in results.columns:
        metrics["historical_resolved_true"] = int(results["historical_resolved"].eq(True).sum())
        metrics["historical_resolved_false"] = int(results["historical_resolved"].eq(False).sum())
    if cfg is not None:
        metrics["run"] = cfg.as_dict()
        metrics["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return metrics


def save_metrics(metrics: dict, path: Path | None = None) -> Path:
    path = path or (RESULTS_DIR / "summary_metrics.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return path


def save_results(results: pd.DataFrame, path: Path | None = None) -> Path:
    path = path or (RESULTS_DIR / "backtest_results.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    front = [c for c in ("ticket_id", "summary", "historical_resolved",
                         "chatbot_response", "classification", "evaluation_reason")
             if c in results.columns]
    ordered = results[front + [c for c in results.columns if c not in front]]
    ordered.to_csv(path, index=False)
    return path


# --------------------------------------------------------------------------- #
# 6. Analysis helpers (return frames; the notebook draws them)
# --------------------------------------------------------------------------- #

def breakdown_table(results: pd.DataFrame) -> pd.DataFrame:
    out = (results["classification"].value_counts()
           .reindex(list(CLASSIFICATIONS)).fillna(0).astype(int)
           .rename_axis("classification").reset_index(name="count"))
    total = out["count"].sum()
    out["percent"] = (out["count"] / total * 100).round(1) if total else 0.0
    return out


def resolved_crosstab(results: pd.DataFrame) -> pd.DataFrame | None:
    if "historical_resolved" not in results.columns:
        return None
    ct = pd.crosstab(
        results["classification"].reindex(results.index),
        results["historical_resolved"].map({True: "resolved", False: "unresolved"}),
    )
    return ct.reindex(list(CLASSIFICATIONS)).fillna(0).astype(int)


def length_vs_classification(results: pd.DataFrame) -> pd.DataFrame:
    return results[["classification", "summary_length"]].copy()


def by_category(results: pd.DataFrame, column: str) -> pd.DataFrame | None:
    """Deflection breakdown by any categorical column (issue_type, priority...)."""
    if column not in results.columns or results[column].astype(str).str.len().eq(0).all():
        return None
    ct = pd.crosstab(results[column], results["classification"])
    for c in CLASSIFICATIONS:
        if c not in ct.columns:
            ct[c] = 0
    ct = ct[list(CLASSIFICATIONS)]
    ct["total"] = ct.sum(axis=1)
    ct["deflection_%"] = (ct["FULL"] / ct["total"] * 100).round(1)
    return ct.sort_values("total", ascending=False)


# --------------------------------------------------------------------------- #
# 7. Manual validation sample + evaluator agreement
# --------------------------------------------------------------------------- #

def sample_for_manual_review(
    results: pd.DataFrame, n: int = 50, *, seed: int = 42, path: Path | None = None
) -> pd.DataFrame:
    """Stratified-ish random sample for a human to independently label."""
    n = min(n, len(results))
    sample = results.sample(n=n, random_state=seed)[
        ["ticket_id", "summary", "chatbot_response", "classification", "evaluation_reason"]
    ].rename(columns={"classification": "llm_evaluation", "evaluation_reason": "llm_reason"})
    sample["human_evaluation"] = ""   # reviewer fills: FULL | PARTIAL | HUMAN
    sample["human_reason"] = ""
    # Filled by score_manual_review() once human labels exist: was the
    # LLM-as-a-judge label right? ("yes"/"no", blank until a human labels the row)
    sample["judge_correct"] = ""
    path = path or (RESULTS_DIR / "manual_review_sample.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(path, index=False)
    return sample


def score_manual_review(reviewed: pd.DataFrame) -> pd.DataFrame:
    """Fill the ``judge_correct`` column: did the LLM judge match the human?

    Returns the frame with ``judge_correct`` set to ``"yes"`` / ``"no"`` for every
    row that has a valid human label, blank otherwise.
    """
    df = reviewed.copy()
    human = df["human_evaluation"].astype(str).str.strip().str.upper()
    judge = df["llm_evaluation"].astype(str).str.strip().str.upper()
    labelled = human.isin(CLASSIFICATIONS)
    df["judge_correct"] = ""
    df.loc[labelled, "judge_correct"] = (
        (human[labelled] == judge[labelled]).map({True: "yes", False: "no"})
    )
    return df


def evaluator_agreement(reviewed: pd.DataFrame) -> dict:
    """Compare LLM vs human labels on a reviewed manual sample.

    Expects columns ``llm_evaluation`` and ``human_evaluation``; rows with a
    blank human label are ignored.
    """
    df = score_manual_review(reviewed)
    df["human_evaluation"] = df["human_evaluation"].astype(str).str.strip().str.upper()
    df["llm_evaluation"] = df["llm_evaluation"].astype(str).str.strip().str.upper()
    df = df[df["human_evaluation"].isin(CLASSIFICATIONS)]
    if df.empty:
        return {"reviewed": 0, "note": "no human labels found yet"}

    agree = (df["llm_evaluation"] == df["human_evaluation"]).mean()
    confusion = pd.crosstab(df["human_evaluation"], df["llm_evaluation"]) \
        .reindex(index=list(CLASSIFICATIONS), columns=list(CLASSIFICATIONS)).fillna(0).astype(int)
    return {
        "reviewed": int(len(df)),
        "judge_correct": int((df["judge_correct"] == "yes").sum()),
        "judge_incorrect": int((df["judge_correct"] == "no").sum()),
        "agreement_rate": round(float(agree), 4),
        "cohens_kappa": round(_cohens_kappa(df["human_evaluation"], df["llm_evaluation"]), 4),
        "confusion_matrix": confusion,  # rows = human, cols = llm
    }


def _cohens_kappa(a: pd.Series, b: pd.Series) -> float:
    labels = list(CLASSIFICATIONS)
    n = len(a)
    if n == 0:
        return 0.0
    po = (a.values == b.values).mean()
    pe = sum((a.eq(l).mean()) * (b.eq(l).mean()) for l in labels)
    return 0.0 if pe == 1 else (po - pe) / (1 - pe)


# --------------------------------------------------------------------------- #
# 8. Failure-pattern tagging  (secondary analysis, kept apart from FULL/PARTIAL/HUMAN)
# --------------------------------------------------------------------------- #

FAILURE_PATTERNS = {
    "requires_system_access": ("access", "permission", "privileg", "admin", "credential", "login"),
    "requires_manual_change": ("manually", "staff", "on our end", "backend", "configure for", "we will"),
    "requires_human_approval": ("approv", "decision", "authorize", "sign off", "confirm with"),
    "requires_investigation": ("investigat", "look into", "debug", "reproduce", "check the logs", "root cause"),
    "insufficient_information": ("not enough information", "don't have", "cannot determine", "need more detail"),
    "incorrect_or_hallucinated": ("incorrect", "wrong", "hallucinat", "not in the doc", "fabricat", "made up"),
    "ambiguous_request": ("ambiguous", "unclear", "vague", "generic", "too broad"),
    "out_of_scope": ("out of scope", "not covered", "bug", "incident", "outage", "migration", "integration", "api"),
}


def failure_patterns(results: pd.DataFrame) -> pd.DataFrame:
    """Tag the evaluator's reason text for HUMAN/PARTIAL rows into coarse buckets.

    Rule-based and transparent — no extra model call, and independent of the
    primary classification.
    """
    subset = results[results["classification"].isin(["HUMAN", "PARTIAL"])]
    rows = []
    for _, r in subset.iterrows():
        text = f"{r.get('evaluation_reason', '')} {r.get('chatbot_response', '')}".lower()
        tags = [name for name, kws in FAILURE_PATTERNS.items() if any(k in text for k in kws)]
        rows.append({"ticket_id": r["ticket_id"], "classification": r["classification"],
                     "patterns": tags or ["unclassified"]})
    tagged = pd.DataFrame(rows)
    if tagged.empty:
        return tagged
    counts = (tagged.explode("patterns").groupby("patterns").size()
              .sort_values(ascending=False).reset_index(name="count"))
    return counts


def examples_by_class(results: pd.DataFrame, classification: str, n: int = 3,
                      *, seed: int = 0) -> pd.DataFrame:
    subset = results[results["classification"] == classification]
    cols = [c for c in ("ticket_id", "summary", "chatbot_response", "evaluation_reason")
            if c in subset.columns]
    return subset.sample(n=min(n, len(subset)), random_state=seed)[cols]
