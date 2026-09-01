import config
from core import knowledge


def test_sections_parse():
    secs = knowledge.sections()
    assert len(secs) > 20
    titles = {s.title for s in secs}
    assert "Void a payment" in titles
    assert "Add a new patient" in titles


def test_content_sections_drops_toc():
    assert any(s.title == "Table of contents" for s in knowledge.sections())
    assert not any(s.title == "Table of contents" for s in knowledge.content_sections())


def test_find_section_by_slug_and_substring():
    assert knowledge.find_section("void-a-payment").title == "Void a payment"
    assert knowledge.find_section("void a payment").title == "Void a payment"
    assert knowledge.find_section("deposit").title.lower().startswith("add a deposit")
    assert knowledge.find_section("nonsense-xyz") is None


def test_system_prompt_contains_docs_and_refusal():
    sp = knowledge.system_prompt()
    assert config.REFUSAL_MARKER in sp
    assert "SUGBODOC DOCUMENTATION" in sp
    assert "Void a payment" in sp
