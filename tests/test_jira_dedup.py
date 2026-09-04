"""Ticket dedup — cosine of a draft vs. recent open Jira issues (mock embeddings)."""

from __future__ import annotations

import config
from core import jira_dedup


def test_returns_none_when_jira_not_configured(monkeypatch):
    monkeypatch.setattr(jira_dedup.jira_client, "jira_configured", lambda: False)
    assert jira_dedup.find_duplicate("cannot void a payment", "the button is greyed out") is None


def test_flags_a_close_match(monkeypatch):
    monkeypatch.setattr(jira_dedup.jira_client, "jira_configured", lambda: True)
    monkeypatch.setattr(
        jira_dedup.jira_client, "list_recent_open_issues",
        lambda *a, **k: [
            {"key": "KAN-10", "summary": "Void payment button greyed out",
             "description": "user cannot void a payment, the button is disabled"},
            {"key": "KAN-11", "summary": "Immunization schedule export fails",
             "description": "CSV export of the immunization schedule errors out"},
        ],
    )
    monkeypatch.setattr(config, "DEDUP_SIMILARITY_THRESHOLD", 0.3)
    dup = jira_dedup.find_duplicate("Cannot void a payment",
                                    "The void button is greyed out and disabled")
    assert dup is not None and dup.key == "KAN-10"


def test_no_match_below_threshold(monkeypatch):
    monkeypatch.setattr(jira_dedup.jira_client, "jira_configured", lambda: True)
    monkeypatch.setattr(
        jira_dedup.jira_client, "list_recent_open_issues",
        lambda *a, **k: [{"key": "KAN-11", "summary": "totally unrelated thing",
                          "description": "nothing to do with the draft"}],
    )
    monkeypatch.setattr(config, "DEDUP_SIMILARITY_THRESHOLD", 0.95)
    assert jira_dedup.find_duplicate("void a payment", "button greyed out") is None


def test_empty_issue_list_is_safe(monkeypatch):
    monkeypatch.setattr(jira_dedup.jira_client, "jira_configured", lambda: True)
    monkeypatch.setattr(jira_dedup.jira_client, "list_recent_open_issues", lambda *a, **k: [])
    assert jira_dedup.find_duplicate("x", "y") is None
