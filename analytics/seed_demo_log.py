"""
Seed logs/chats.jsonl with synthetic conversations so the analytics + docs-loop
scripts are demoable before the app has real traffic.

No model calls — hand-written records. Includes clusters of similar failures
(deleting patients, exporting data, mobile access) so clustering has something
to find.

Usage:
    python -m analytics.seed_demo_log            # append
    python -m analytics.seed_demo_log --reset    # wipe the log first
"""

from __future__ import annotations

# Allow `python analytics/seed_demo_log.py` as well as `python -m ...`.
if not __package__:
    import pathlib
    import sys as _sys

    _sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import argparse
from datetime import datetime, timedelta, timezone

import config
from core import chatlog
from core.chatlog import ConversationRecord


def _c(days_ago: int, **kw) -> ConversationRecord:
    started = datetime.now(timezone.utc) - timedelta(days=days_ago, hours=1)
    ended = started + timedelta(minutes=6)
    base = dict(
        conversation_id=chatlog.new_conversation_id(),
        started_at=started.isoformat(timespec="seconds"),
        ended_at=ended.isoformat(timespec="seconds"),
        outcome="resolved",
        question_count=1,
        messages=[],
        failure_signals=[],
        grounding_checks=[],
        triage_label=None,
        triage_confidence=None,
        thumbs=None,
        ticket_id=None,
        ticket_category=None,
        duplicate_of=None,
    )
    base.update(kw)
    return ConversationRecord(**base)  # type: ignore[arg-type]


def _turns(*pairs: tuple[str, str]) -> list[dict]:
    out = [{"role": "assistant", "content": "Hi! What can I help you with today?"}]
    for u, a in pairs:
        out.append({"role": "user", "content": u})
        out.append({"role": "assistant", "content": a})
    return out


REFUSAL = config.REFUSAL_MARKER


def build() -> list[ConversationRecord]:
    convs: list[ConversationRecord] = []

    # --- resolved, happy path ---
    for d, q, a in [
        (1, "how do I add a new patient", "Go to Patient Worklist -> Add patient -> Add new patient..."),
        (2, "create a prescription", "Open the Prescription card -> Add prescription..."),
        (3, "how to void a payment", "Bills and Payment -> View all -> View all deposit -> three dots -> Void."),
        (5, "add vital signs", "Vital Signs card -> Add vitals, then enter height, weight, BP..."),
        (6, "how do I pay my monthly subscription", "Subscription module -> Prepaid -> choose a payment method -> Proceed."),
        (8, "create a schedule for a doctor", "Schedule -> All Schedule -> Add new, set location, provider, days, time slots."),
        (11, "how to add a deposit to an unpaid invoice", "Bills and Payment -> View all -> Unpaid invoices -> Deposit..."),
        (14, "difference between internal and external immunization", "Internal = you administered and recorded it; external = someone else did."),
    ]:
        convs.append(_c(d, outcome="resolved", thumbs="up",
                        messages=_turns((q, a))))

    # --- CLUSTER 1: deleting / removing patients (docs gap) ---
    for d, q in [
        (1, "how do I delete a patient"),
        (2, "remove a patient from my worklist"),
        (4, "I added a patient by mistake, how do I delete them"),
        (7, "how to permanently remove a patient record"),
    ]:
        convs.append(_c(
            d, outcome="ticket_filed", question_count=3,
            failure_signals=["refused", "repeated_question"],
            triage_label="docs_gap", triage_confidence=0.8,
            thumbs="down", ticket_id=f"KAN-{100 + d}", ticket_category="Patients",
            messages=_turns(
                (q, f"{REFUSAL}. You can submit a support ticket."),
                ("it's really not in there?", f"{REFUSAL}."),
            ),
        ))

    # --- CLUSTER 2: exporting all data (docs gap / possible feature) ---
    for d, q in [
        (3, "how do I export all my patient data"),
        (6, "can I download every patient record as a backup"),
        (9, "bulk export of all clinical data please"),
    ]:
        convs.append(_c(
            d, outcome="ticket_filed", question_count=2,
            failure_signals=["refused"],
            triage_label="docs_gap", triage_confidence=0.6,
            ticket_id=f"KAN-{200 + d}", ticket_category="Account",
            messages=_turns((q, f"{REFUSAL}. You can submit a support ticket.")),
        ))

    # --- CLUSTER 3: mobile app (out of scope) ---
    for d, q in [
        (2, "is there a mobile app for sugbodoc"),
        (5, "can I use sugbodoc on my iphone"),
    ]:
        convs.append(_c(
            d, outcome="abandoned", question_count=1,
            failure_signals=["refused"],
            triage_label="out_of_scope", triage_confidence=0.9,
            messages=_turns((q, f"{REFUSAL}.")),
        ))

    # --- verification pass catch (bot drafted something wrong, got downgraded) ---
    convs.append(_c(
        4, outcome="ticket_filed", question_count=2,
        failure_signals=["grounding_failed", "refused"],
        triage_label="docs_gap", triage_confidence=0.7,
        ticket_id="KAN-305", ticket_category="Billing",
        grounding_checks=[{"question": "how do I give a partial refund",
                           "grounding_supported": False,
                           "grounding_reason": "docs only cover Void, not partial refunds"}],
        messages=_turns(("how do I give a partial refund on a deposit",
                         f"{REFUSAL}. You can submit a support ticket.")),
    ))

    # --- duplicate linked instead of new ticket ---
    convs.append(_c(
        1, outcome="linked_duplicate", question_count=3,
        failure_signals=["refused", "repeated_question"],
        triage_label="docs_gap", triage_confidence=0.75,
        duplicate_of="KAN-101",
        messages=_turns(("how do I delete a patient i added twice",
                         f"{REFUSAL}. You can submit a support ticket.")),
    ))

    return convs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    dest = "chat_logs table" if config.DATABASE_URL else str(config.CHAT_LOG_PATH)

    if args.reset:
        chatlog.reset_store()
        print(f"wiped {dest}")

    convs = build()
    for c in convs:
        chatlog.append(c)
    print(f"appended {len(convs)} synthetic conversations to {dest}")
    print("now try:  python -m analytics.analytics_kpis   and   "
          "python -m analytics.analytics_cluster")


if __name__ == "__main__":
    main()
