from core import jira_client


def test_adf_paragraph_per_line():
    doc = jira_client._adf("line one\nline two")
    assert doc["type"] == "doc" and doc["version"] == 1
    texts = [p["content"][0]["text"] for p in doc["content"] if p.get("content")]
    assert texts == ["line one", "line two"]


def test_adf_blank_line_is_spacer():
    doc = jira_client._adf("a\n\nb")
    assert doc["content"][1] == {"type": "paragraph"}  # empty spacer between a and b


def test_adf_empty_input_has_placeholder():
    doc = jira_client._adf("   \n  ")
    assert doc["content"][0]["content"][0]["text"] == "(no details)"


def test_build_description_includes_all_fields():
    d = jira_client.build_description(
        summary="cannot void", category="Billing", contact="a@b.com",
        question_count=3, transcript="User: hi\nAssistant: hello",
    )
    assert "cannot void" in d
    assert "Reporter email: a@b.com" in d
    assert "Suggested category: Billing" in d
    assert "Questions asked before ticket: 3" in d
    assert "Conversation transcript" in d and "User: hi" in d
