"""
Jira integration for the SugboDoc assistant.

Mostly outbound: the bot creates tickets, it does not answer from them. The only
reads are (a) dedup — pulling recent open issues to compare against a draft, and
(b) the docs loop — pulling recently resolved issues that might have outdated a
doc. Both are batch, never per-turn. See §3 / §4 of the architecture doc.
"""

from __future__ import annotations

import os
import re

import requests

import config  # loads .env

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")
JIRA_PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "")
JIRA_ISSUE_TYPE = os.environ.get("JIRA_ISSUE_TYPE", "Task")

_AUTH = (JIRA_EMAIL, JIRA_API_TOKEN)
_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}


def jira_configured() -> bool:
    return all((JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY))


def browse_url(key: str) -> str:
    return f"{JIRA_BASE_URL}/browse/{key}"


# --------------------------------------------------------------------------- #
# Reporter lookup
# --------------------------------------------------------------------------- #

_ACCOUNT_ID_CACHE: dict[str, str | None] = {}


def resolve_account_id(email: str | None) -> str | None:
    """Best-effort: the Jira Cloud accountId for `email`, or None.

    Jira Cloud won't accept an email in the `reporter` field — it needs an
    accountId — and only works if the API-token user has *Modify Reporter*
    permission. Most people filing via the chat aren't Jira users at all, so a
    None result is normal; the email is still recorded in the description.
    """
    if not email or not jira_configured():
        return None
    key = email.strip().lower()
    if key in _ACCOUNT_ID_CACHE:
        return _ACCOUNT_ID_CACHE[key]

    account_id: str | None = None
    try:
        resp = requests.get(
            f"{JIRA_BASE_URL}/rest/api/3/user/search",
            params={"query": email}, auth=_AUTH, headers=_HEADERS, timeout=15,
        )
        if resp.status_code == 200:
            users = resp.json() or []
            exact = [u for u in users
                     if (u.get("emailAddress") or "").lower() == key]
            if exact:
                account_id = exact[0].get("accountId")
            elif len(users) == 1:            # email hidden by privacy settings
                account_id = users[0].get("accountId")
    except requests.RequestException:
        pass

    _ACCOUNT_ID_CACHE[key] = account_id
    return account_id


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #

def _adf(text: str) -> dict:
    """Minimal Atlassian Document Format: one paragraph per line, blank = spacer."""
    paras: list[dict] = []
    for raw in text.split("\n"):
        line = raw.rstrip()
        if line:
            paras.append({"type": "paragraph",
                          "content": [{"type": "text", "text": line}]})
        else:
            paras.append({"type": "paragraph"})
    if not any(p.get("content") for p in paras):
        paras = [{"type": "paragraph",
                  "content": [{"type": "text", "text": "(no details)"}]}]
    return {"type": "doc", "version": 1, "content": paras}


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def build_description(
    summary: str, category: str, contact: str, question_count: int, transcript: str,
    *, due_date: str | None = None, urgency: str | None = None,
) -> str:
    lines = [
        summary, "",
        f"Reporter email: {contact}",
        f"Suggested category: {category}",
    ]
    if due_date:
        lines.append(f"Target date: {due_date}")
    if urgency:
        lines.append(f"Requested urgency: {urgency}")
    lines += [
        f"Questions asked before ticket: {question_count}",
        "",
        "--- Conversation transcript ---",
        transcript,
    ]
    return "\n".join(lines)


def _create(fields: dict) -> requests.Response:
    return requests.post(
        f"{JIRA_BASE_URL}/rest/api/3/issue",
        json={"fields": fields}, auth=_AUTH, headers=_HEADERS, timeout=20,
    )


# Fields Jira may reject (missing from the create screen, no permission, bad
# format). If a 400 names one, we drop it and retry so the ticket still files.
_OPTIONAL_FIELDS = ("reporter", "duedate", "priority")


def create_issue(
    *,
    subject: str,
    category: str,
    summary: str,
    contact: str,
    transcript: str,
    question_count: int,
    due_date: str | None = None,
    urgency: str | None = None,
    extra_labels: list[str] | None = None,
) -> str:
    """Create a Jira issue and return its key (e.g. 'KAN-12').

    `contact` is the user's email — recorded in the description and, when it
    matches a Jira user we may set as reporter, used for the `reporter` field.
    `due_date` (YYYY-MM-DD) maps to `duedate`; `urgency` becomes a label.
    """
    label_cat = category.lower().replace("/", "-").replace(" ", "-") or "other"
    labels = ["sugbodoc-assistant", label_cat, *(extra_labels or [])]
    if urgency:
        labels.append(f"urgency-{urgency}")

    fields: dict = {
        "project": {"key": JIRA_PROJECT_KEY},
        "summary": (subject or "SugboDoc support request")[:250],
        "description": _adf(build_description(
            summary, category, contact, question_count, transcript,
            due_date=due_date, urgency=urgency,
        )),
        "issuetype": {"name": JIRA_ISSUE_TYPE},
        "labels": labels,
    }
    if due_date and _ISO_DATE.match(due_date):
        fields["duedate"] = due_date
    account_id = resolve_account_id(contact)
    if account_id:
        fields["reporter"] = {"id": account_id}

    resp = _create(fields)
    if resp.status_code == 400:
        body = resp.text
        dropped = [f for f in _OPTIONAL_FIELDS if f in fields and f in body]
        if dropped:
            for f in dropped:
                fields.pop(f, None)
            resp = _create(fields)
    if resp.status_code >= 300:
        raise RuntimeError(f"Jira API {resp.status_code}: {resp.text[:500]}")
    return resp.json()["key"]


# --------------------------------------------------------------------------- #
# Batch reads (dedup + docs loop only)
# --------------------------------------------------------------------------- #

def _search(jql: str, *, fields: list[str], max_results: int = 100) -> list[dict]:
    resp = requests.get(
        f"{JIRA_BASE_URL}/rest/api/3/search/jql",
        params={"jql": jql, "fields": ",".join(fields), "maxResults": max_results},
        auth=_AUTH, headers=_HEADERS, timeout=30,
    )
    if resp.status_code == 404:
        # Older Cloud sites still use the /search endpoint.
        resp = requests.get(
            f"{JIRA_BASE_URL}/rest/api/3/search",
            params={"jql": jql, "fields": ",".join(fields), "maxResults": max_results},
            auth=_AUTH, headers=_HEADERS, timeout=30,
        )
    if resp.status_code >= 300:
        raise RuntimeError(f"Jira search {resp.status_code}: {resp.text[:400]}")
    return resp.json().get("issues", [])


def _plain_text_from_adf(node: dict | None) -> str:
    if not node:
        return ""
    if node.get("type") == "text":
        return node.get("text", "")
    return "".join(_plain_text_from_adf(c) for c in node.get("content", []) or [])


def list_recent_open_issues(days: int = 30, limit: int = 100) -> list[dict]:
    """[{key, summary, description}] — open assistant-filed issues, newest first."""
    jql = (
        f'project = "{JIRA_PROJECT_KEY}" AND labels = "sugbodoc-assistant" '
        f'AND statusCategory != Done AND created >= -{days}d ORDER BY created DESC'
    )
    issues = _search(jql, fields=["summary", "description"], max_results=limit)
    return [
        {
            "key": it["key"],
            "summary": it["fields"].get("summary", ""),
            "description": _plain_text_from_adf(it["fields"].get("description")),
        }
        for it in issues
    ]


def list_resolved_issues(days: int = 30, limit: int = 100) -> list[dict]:
    """[{key, summary, description, resolved}] — recently resolved issues."""
    jql = (
        f'project = "{JIRA_PROJECT_KEY}" AND statusCategory = Done '
        f'AND resolved >= -{days}d ORDER BY resolved DESC'
    )
    issues = _search(jql, fields=["summary", "description", "resolutiondate"], max_results=limit)
    return [
        {
            "key": it["key"],
            "summary": it["fields"].get("summary", ""),
            "description": _plain_text_from_adf(it["fields"].get("description")),
            "resolved": it["fields"].get("resolutiondate", ""),
        }
        for it in issues
    ]
