"""
Jira ticket creation for the SugboDoc assistant.

Outbound only — the assistant never reads from Jira. Shared by app.py and the
standalone test scripts so the ticket-creation path is exercised the same way
everywhere.
"""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "").rstrip("/")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")
JIRA_PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "")
JIRA_ISSUE_TYPE = os.environ.get("JIRA_ISSUE_TYPE", "Task")

_AUTH = (JIRA_EMAIL, JIRA_API_TOKEN)
_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}


def jira_configured() -> bool:
    return all((JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY))


def _adf(text: str) -> dict:
    """Minimal Atlassian Document Format: one paragraph per line, blank line -> spacer."""
    paras = []
    for line in (raw.rstrip() for raw in text.split("\n")):
        if line:
            paras.append({"type": "paragraph",
                          "content": [{"type": "text", "text": line}]})
        else:
            paras.append({"type": "paragraph"})  # empty line = visual gap
    if not any(p.get("content") for p in paras):
        paras = [{"type": "paragraph",
                  "content": [{"type": "text", "text": "(no details)"}]}]
    return {"type": "doc", "version": 1, "content": paras}


def build_description(
    summary: str, category: str, contact: str, question_count: int, transcript: str
) -> str:
    return (
        f"{summary}\n\n"
        f"Reporter email: {contact}\n"
        f"Suggested category: {category}\n"
        f"Questions asked before ticket: {question_count}\n\n"
        f"--- Conversation transcript ---\n{transcript}"
    )


def create_issue(
    *,
    subject: str,
    category: str,
    summary: str,
    contact: str,
    transcript: str,
    question_count: int,
) -> str:
    """Create a Jira issue and return its key (e.g. 'KAN-12')."""
    label_cat = category.lower().replace("/", "-").replace(" ", "-") or "other"
    payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "summary": (subject or "SugboDoc support request")[:250],
            "description": _adf(
                build_description(summary, category, contact, question_count, transcript)
            ),
            "issuetype": {"name": JIRA_ISSUE_TYPE},
            "labels": ["sugbodoc-assistant", label_cat],
        }
    }
    resp = requests.post(
        f"{JIRA_BASE_URL}/rest/api/3/issue",
        json=payload, auth=_AUTH, headers=_HEADERS, timeout=20,
    )
    if resp.status_code >= 300:
        raise RuntimeError(f"Jira API {resp.status_code}: {resp.text[:500]}")
    return resp.json()["key"]


def browse_url(key: str) -> str:
    return f"{JIRA_BASE_URL}/browse/{key}"
