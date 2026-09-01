"""`ticketing` — the no-LLM ticket default + date/urgency helpers."""

from datetime import date

from core import ticketing

TUE = date(2026, 9, 1)


def test_default_draft_seeds_subject_from_first_question():
    d = ticketing.default_draft(
        "Assistant: hi\nUser: how do I export insurance claims?\nAssistant: no idea"
    )
    assert d.subject == "how do I export insurance claims?"
    assert d.category == "Other"
    assert d.summary == ""


def test_default_draft_falls_back_when_no_user_line():
    d = ticketing.default_draft("Assistant: hello")
    assert d.subject == "SugboDoc support request"


def test_as_iso_date():
    assert ticketing.as_iso_date("2026-12-25") == "2026-12-25"
    assert ticketing.as_iso_date(" 2026-12-25 ") == "2026-12-25"
    assert ticketing.as_iso_date("2026-13-40") is None      # not a real date
    assert ticketing.as_iso_date("next Friday") is None
    assert ticketing.as_iso_date("") is None
    assert ticketing.as_iso_date(None) is None


def test_urgency_for_date():
    assert ticketing.urgency_for_date(None) == "medium"
    assert ticketing.urgency_for_date("2026-09-02", today=TUE) == "high"    # 1 day
    assert ticketing.urgency_for_date("2026-09-10", today=TUE) == "medium"  # 9 days
    assert ticketing.urgency_for_date("2026-10-15", today=TUE) == "low"     # far out
    assert ticketing.urgency_for_date("not-a-date") == "medium"
