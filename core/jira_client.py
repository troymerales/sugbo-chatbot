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

# Plain-text custom fields that hold the chat submitter's identity — the
# `reporter` system field needs a Jira accountId, so a chat user's name/email
# can't go there. Looked up by name at runtime; set to "" to skip one.
JIRA_SUBMITTER_FIELD = os.environ.get("JIRA_SUBMITTER_FIELD", "Submitter")
JIRA_SUBMITTER_EMAIL_FIELD = os.environ.get("JIRA_SUBMITTER_EMAIL_FIELD", "Submitter Email")
JIRA_SUBJECT_FIELD = os.environ.get("JIRA_SUBJECT_FIELD", "Subject")

_AUTH = (JIRA_EMAIL, JIRA_API_TOKEN)
_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}


def jira_configured() -> bool:
    return all((JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY))


def browse_url(key: str) -> str:
    return f"{JIRA_BASE_URL}/browse/{key}"


# --------------------------------------------------------------------------- #
# Reporter + custom-field lookup
# --------------------------------------------------------------------------- #

_ACCOUNT_ID_CACHE: dict[str, str | None] = {}
_ALL_FIELDS_CACHE: list[dict] | None = None


def resolve_account_id(query: str | None) -> str | None:
    """Best-effort: the Jira Cloud accountId for a name or email, or None.

    `/rest/api/3/user/search` matches on display name *and* email. Jira Cloud
    won't accept a bare name/email in the `reporter` field — it needs an
    accountId — and only works if the API-token user has *Modify Reporter*
    permission. Most people filing via the chat aren't Jira users at all, so a
    None result is normal; the name/email is still recorded in custom fields
    and the description.
    """
    if not query or not jira_configured():
        return None
    key = query.strip().lower()
    if key in _ACCOUNT_ID_CACHE:
        return _ACCOUNT_ID_CACHE[key]

    account_id: str | None = None
    try:
        resp = requests.get(
            f"{JIRA_BASE_URL}/rest/api/3/user/search",
            params={"query": query}, auth=_AUTH, headers=_HEADERS, timeout=15,
        )
        if resp.status_code == 200:
            users = resp.json() or []
            exact = [u for u in users
                     if (u.get("emailAddress") or "").lower() == key
                     or (u.get("displayName") or "").strip().lower() == key]
            if exact:
                account_id = exact[0].get("accountId")
            elif len(users) == 1:            # unambiguous partial match
                account_id = users[0].get("accountId")
    except requests.RequestException:
        pass

    _ACCOUNT_ID_CACHE[key] = account_id
    return account_id


def _field_id(name: str) -> str | None:
    """The Jira field id (e.g. `customfield_10050`) for a field named `name`,
    or None if the project doesn't have it / the field list can't be read."""
    global _ALL_FIELDS_CACHE
    if not name or not jira_configured():
        return None
    if _ALL_FIELDS_CACHE is None:
        try:
            resp = requests.get(f"{JIRA_BASE_URL}/rest/api/3/field",
                                auth=_AUTH, headers=_HEADERS, timeout=15)
            _ALL_FIELDS_CACHE = resp.json() if resp.status_code == 200 else []
        except requests.RequestException:
            _ALL_FIELDS_CACHE = []
    key = name.strip().lower()
    matches = sorted(
        (f for f in _ALL_FIELDS_CACHE if (f.get("name") or "").strip().lower() == key),
        key=lambda f: not f.get("custom", False),   # prefer a custom field
    )
    return matches[0].get("id") if matches else None


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
    *, submitter_name: str | None = None, due_date: str | None = None,
    urgency: str | None = None,
) -> str:
    lines = [summary, ""]
    if submitter_name:
        lines.append(f"Submitter: {submitter_name}")
    lines += [
        f"Submitter email: {contact}",
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
    submitter_name: str | None = None,
    due_date: str | None = None,
    urgency: str | None = None,
    extra_labels: list[str] | None = None,
) -> str:
    """Create a Jira issue and return its key (e.g. 'KAN-12').

    The chat submitter's name/email go to the project's plain-text `Submitter` /
    `Submitter Email` custom columns (and the description). The `reporter` system
    field is only set if the *email* matches a real Jira user — otherwise it
    stays the API-token user, which signals the ticket came from the assistant.
    `due_date` (YYYY-MM-DD) maps to `duedate`; `urgency` becomes a label.
    """
    submitter_name = (submitter_name or "").strip() or None
    label_cat = category.lower().replace("/", "-").replace(" ", "-") or "other"
    labels = ["sugbodoc-assistant", label_cat, *(extra_labels or [])]
    if urgency:
        labels.append(f"urgency-{urgency}")

    fields: dict = {
        "project": {"key": JIRA_PROJECT_KEY},
        "summary": (subject or "SugboDoc support request")[:250],
        "description": _adf(build_description(
            summary, category, contact, question_count, transcript,
            submitter_name=submitter_name, due_date=due_date, urgency=urgency,
        )),
        "issuetype": {"name": JIRA_ISSUE_TYPE},
        "labels": labels,
    }
    if due_date and _ISO_DATE.match(due_date):
        fields["duedate"] = due_date

    # `reporter` system field — only if the email is a real Jira user; the name
    # deliberately does NOT feed this (it bypasses the strict user format by
    # going to the plain-text `Submitter` field instead).
    account_id = resolve_account_id(contact)
    if account_id:
        fields["reporter"] = {"id": account_id}

    # Plain-text custom columns for the chat submitter's identity.
    for field_name, value in (
        (JIRA_SUBMITTER_FIELD, submitter_name),
        (JIRA_SUBMITTER_EMAIL_FIELD, contact or None),
        (JIRA_SUBJECT_FIELD, subject or None),
    ):
        fid = _field_id(field_name) if value else None
        if fid:
            fields[fid] = value

    resp = _create(fields)
    if resp.status_code == 400:
        body = resp.text
        dropped = [
            k for k in list(fields)
            if (k in _OPTIONAL_FIELDS or k.startswith("customfield_")) and k in body
        ]
        if dropped:
            for k in dropped:
                fields.pop(k, None)
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
