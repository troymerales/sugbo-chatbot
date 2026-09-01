import config
from core import bot, grounding


def test_respond_answers_a_documented_question():
    res = bot.respond(bot.fresh_chat(), "How do I void a payment?")
    assert not res.refused
    assert "Void a payment" in res.text
    assert res.grounding.checked


def test_respond_refuses_when_no_doc_match():
    res = bot.respond(bot.fresh_chat(), "What is the airspeed velocity of a swallow?")
    assert res.refused
    assert config.REFUSAL_MARKER in res.text


def test_verify_short_circuits_on_refusal_text():
    v = grounding.verify("q", f"{config.REFUSAL_MARKER}. submit a ticket")
    assert v.supported and v.checked
    assert "refused" in v.reason


def test_verify_returns_verdict_for_normal_answer():
    v = grounding.verify("How do I void a payment?",
                         "From **Void a payment**: open the deposit and pick Void.")
    assert v.checked
    assert isinstance(v.supported, bool)
