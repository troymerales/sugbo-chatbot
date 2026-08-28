"""
End-to-end test of the ticket-creation path (jira_client.create_issue).

Builds a realistic failed-conversation transcript and files it as a real Jira
issue — the same call app.py's modal makes. Delete the issue in Jira afterwards.

Run:
    python jira_test_ticket.py
"""

from __future__ import annotations

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from jira_client import browse_url, create_issue, jira_configured

SAMPLE_TRANSCRIPT = """\
User: How do I void a payment?
Assistant: On the patient's Bills and Payment card, click View all, open the \
deposit, click the three dots and choose Void. (See "Void a payment".)
User: I only see View and Refund on the three dots, there's no Void
Assistant: Void should appear for card and cash deposits that haven't been \
settled. If only Refund shows, the deposit may already be settled.
User: it's a cash deposit from today though, still no void option
Assistant: I don't have anything else in my records about that case."""


def main() -> None:
    if not jira_configured():
        raise SystemExit("Jira not configured — fill in JIRA_* in .env")

    key = create_issue(
        subject="Void option missing for same-day cash deposit",
        category="Billing",
        summary=(
            "User cannot void a cash deposit created today. The three-dot menu on "
            "the deposit only shows View and Refund, not Void. Documentation says "
            "Void should be available for unsettled cash/card deposits."
        ),
        contact="qa.tester@example.com",
        transcript=SAMPLE_TRANSCRIPT,
        question_count=3,
    )
    print(f"[OK] created {key}")
    print(f"     {browse_url(key)}")
    print("     open it and confirm: summary, description body, transcript, labels")
    print("     then delete it in Jira")


if __name__ == "__main__":
    main()
