import config
from core import failure_capture as fc


def _msgs(*turns):
    out = [{"role": "assistant", "content": "hi"}]
    for role, content in turns:
        out.append({"role": role, "content": content})
    return out


def test_no_signals_on_clean_chat():
    sig = fc.detect_failures(_msgs(("user", "how do I add a patient"),
                                   ("assistant", "Go to Patient Worklist ...")))
    assert not sig.failed
    assert sig.as_list() == []


def test_refusal_signal():
    sig = fc.detect_failures(_msgs(
        ("user", "how do I delete a patient"),
        ("assistant", f"{config.REFUSAL_MARKER}. Please submit a ticket."),
    ))
    assert sig.refused and sig.failed
    assert "refused" in sig.as_list()
    assert "bot could not answer from the docs" in sig.reasons


def test_reasons_are_human_readable_and_cover_each_signal():
    sig = fc.detect_failures(
        _msgs(("user", "how do I add vitals"),
              ("assistant", "..."),
              ("user", "how do i add vitals?"),
              ("assistant", "..."),
              ("user", "that's wrong")),
        thumbs_down=True, grounding_failed=True,
    )
    assert sig.reasons == [
        "user pressed thumbs-down",
        "verification pass rejected an answer",
        "user re-asked the same question",
        "user said the answer was wrong / unhelpful",
    ]


def test_repeated_question_signal_fuzzy():
    sig = fc.detect_failures(_msgs(
        ("user", "how do I delete a patient record"),
        ("assistant", "..."),
        ("user", "how do i delete a patient record?"),
    ))
    assert sig.repeated_question


def test_negative_feedback_on_last_turn():
    sig = fc.detect_failures(_msgs(
        ("user", "how do I add vitals"),
        ("assistant", "..."),
        ("user", "that's wrong, not helpful"),
    ))
    assert sig.negative_feedback and sig.failed


def test_thumbs_down_and_grounding_flags_passthrough():
    sig = fc.detect_failures(_msgs(("user", "q")), thumbs_down=True, grounding_failed=True)
    assert sig.thumbs_down and sig.grounding_failed and sig.failed
    assert set(sig.as_list()) >= {"thumbs_down", "grounding_failed"}
