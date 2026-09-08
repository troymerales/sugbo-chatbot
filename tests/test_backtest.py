"""
Backtest harness tests — all offline (mock backend, via conftest).

They check the plumbing (loading, leakage guard, resumability, metrics,
agreement) — not answer quality, which needs the real model.
"""

from __future__ import annotations

import pandas as pd
import pytest

from evaluation import backtest as bt


@pytest.fixture
def tickets() -> pd.DataFrame:
    return pd.DataFrame({
        "ticket_id": ["T-1", "T-2", "T-3"],
        "summary": [
            "How do I add a new patient profile?",
            "Login returns a 500 error for everyone",
            "Please reset my password",
        ],
        "issue_type": ["Service Request", "Bug", "Access"],
        "resolved": ["True", "False", "True"],
    })


def _cfg(tmp_path, **kw):
    return bt.BacktestConfig(run_id="test", batch_size=2, **kw)


def test_load_tickets_sample_has_required_columns():
    df = bt.load_tickets(bt.TICKETS_SAMPLE_PATH)
    assert {"ticket_id", "summary"} <= set(df.columns)
    assert "historical_resolved" in df.columns
    assert len(df) > 10


def test_load_tickets_normalises_jira_export_headers(tmp_path):
    p = tmp_path / "jira_tickets_export.csv"
    p.write_text(
        "Issue Type,Issue id,Summary,Status,Resolution\n"
        "Story,17973,\"Modify inventory charges\",Done,Done\n"
        "Bug,17974,\"Login 500\",To Do,\n",
        encoding="utf-8",
    )
    df = bt.load_tickets(p)
    assert list(df["ticket_id"]) == ["17973", "17974"]
    assert df["summary"].iloc[0] == "Modify inventory charges"
    assert df["issue_type"].tolist() == ["Story", "Bug"]
    assert df["historical_resolved"].tolist() == [True, False]   # Done->True, To Do->False
    assert "historical_status" in df.columns
    assert bt.validate_tickets(df)["potential_leak_columns"] == []   # raw Status/Resolution renamed


def test_chatbot_input_is_summary_only(tickets):
    row = tickets.iloc[1]
    assert bt.chatbot_input(row) == "Login returns a 500 error for everyone"
    # nothing resolution-shaped leaks in
    assert "False" not in bt.chatbot_input(row)


def test_validate_flags_duplicates_and_blanks():
    df = pd.DataFrame({"ticket_id": ["A", "A", ""], "summary": ["x", "y", ""]})
    rep = bt.validate_tickets(df)
    assert rep["duplicate_ticket_ids"] == 1
    assert rep["blank_summaries"] == 1
    assert rep["blank_ticket_ids"] == 1


def test_run_chatbot_uses_production_model():
    out = bt.run_chatbot("How do I add a new patient profile?")
    assert out["chatbot_response"]
    assert out["chatbot_model"] == bt.config.ANSWER_MODEL
    assert out["chatbot_error"] == ""


def test_evaluate_response_returns_valid_label():
    v = bt.evaluate_response("How do I add a patient?", "From **Add a patient**: 1. ...")
    assert v["classification"] in bt.CLASSIFICATIONS
    assert v["evaluator_model"] == bt.config.JUDGE_MODEL


def test_evaluate_empty_response_is_human():
    v = bt.evaluate_response("anything", "")
    assert v["classification"] == "HUMAN"
    assert v["evaluator_fallback"] is True


def test_evaluate_batch_covers_every_ticket():
    items = [
        {"ticket_id": "B-1", "summary": "How do I add a patient?", "chatbot_response": "steps..."},
        {"ticket_id": "B-2", "summary": "Login 500 error", "chatbot_response": ""},
        {"ticket_id": "B-3", "summary": "Reset my password", "chatbot_response": "go to settings"},
    ]
    verdicts = bt.evaluate_batch(items, model="mock-judge")
    assert set(verdicts) == {"B-1", "B-2", "B-3"}          # nothing dropped
    assert all(v["classification"] in bt.CLASSIFICATIONS for v in verdicts.values())
    assert verdicts["B-2"]["classification"] == "HUMAN"    # empty response
    assert verdicts["B-2"]["evaluator_fallback"] is True


def test_parse_batch_json_validates_ids_and_labels():
    raw = ('[{"ticket_id":"X","classification":"FULL","reason":"ok"},'
           '{"ticket_id":"Y","classification":"BOGUS","reason":"x"},'
           '{"ticket_id":"Z","classification":"HUMAN","reason":"z"}]')
    out = bt._parse_batch_json(raw, expected_ids={"X", "Z"})
    assert set(out) == {"X", "Z"}          # Y dropped (bad label), unknown ids ignored


def test_score_manual_review_judge_correct_column():
    reviewed = pd.DataFrame({
        "llm_evaluation": ["FULL", "HUMAN", "PARTIAL"],
        "human_evaluation": ["FULL", "PARTIAL", ""],
    })
    scored = bt.score_manual_review(reviewed)
    assert list(scored["judge_correct"]) == ["yes", "no", ""]


def test_backtest_is_resumable(tmp_path, tickets):
    cfg = _cfg(tmp_path)
    rpath = tmp_path / "responses.csv"

    first = bt.run_backtest(tickets.head(2), cfg, responses_path=rpath, progress=lambda *_: None)
    assert len(first) == 2

    # re-run with the full set: only the missing ticket is processed
    full = bt.run_backtest(tickets, cfg, responses_path=rpath, progress=lambda *_: None)
    assert len(full) == 3
    assert set(full["ticket_id"]) == {"T-1", "T-2", "T-3"}
    # no duplicate rows written
    assert full["ticket_id"].is_unique


def test_end_to_end_metrics(tmp_path, tickets):
    cfg = _cfg(tmp_path)
    rpath, epath = tmp_path / "r.csv", tmp_path / "e.csv"

    responses = bt.run_backtest(tickets, cfg, responses_path=rpath, progress=lambda *_: None)
    evals = bt.run_evaluation(responses, cfg, evaluations_path=epath, progress=lambda *_: None)
    assert set(evals["classification"]) <= set(bt.CLASSIFICATIONS)

    tdf = tickets.rename(columns={"resolved": "historical_resolved"})
    tdf["historical_resolved"] = tdf["historical_resolved"].map(bt._coerce_bool)
    results = bt.build_results(tdf, responses, evals)
    assert len(results) == 3

    m = bt.calculate_metrics(results, cfg)
    assert m["total_tickets"] == 3
    assert m["full"] + m["partial"] + m["human"] == 3
    assert 0.0 <= m["potential_deflection_rate"] <= 1.0
    assert "run" in m and m["run"]["chatbot_model"] == bt.config.ANSWER_MODEL


def test_analysis_helpers(tmp_path, tickets):
    cfg = _cfg(tmp_path)
    responses = bt.run_backtest(tickets, cfg, responses_path=tmp_path / "r.csv",
                                progress=lambda *_: None)
    evals = bt.run_evaluation(responses, cfg, evaluations_path=tmp_path / "e.csv",
                              progress=lambda *_: None)
    tdf = tickets.rename(columns={"resolved": "historical_resolved"})
    tdf["historical_resolved"] = tdf["historical_resolved"].map(bt._coerce_bool)
    results = bt.build_results(tdf, responses, evals)

    assert list(bt.breakdown_table(results)["classification"]) == list(bt.CLASSIFICATIONS)
    assert bt.resolved_crosstab(results).sum().sum() == 3
    assert bt.by_category(results, "issue_type") is not None

    sample = bt.sample_for_manual_review(results, n=2, path=tmp_path / "m.csv")
    assert {"human_evaluation", "llm_evaluation", "judge_correct"} <= set(sample.columns)

    sample["human_evaluation"] = "FULL"
    agr = bt.evaluator_agreement(sample)
    assert agr["reviewed"] == 2
    assert agr["judge_correct"] + agr["judge_incorrect"] == 2
    assert -1.0 <= agr["cohens_kappa"] <= 1.0


def test_doc_overlap_and_likely_misses():
    frame = pd.DataFrame({
        "ticket_id": ["a", "b"],
        "summary": ["How do I create a prescription?", "asdfghjkl zxcvb qwerty"],
    })
    ov = bt.doc_overlap_frame(frame)
    assert set(ov.columns) == {"ticket_id", "doc_overlap", "nearest_doc_sections"}
    assert ov.set_index("ticket_id").loc["a", "doc_overlap"] > \
        ov.set_index("ticket_id").loc["b", "doc_overlap"]

    results = pd.DataFrame({
        "ticket_id": ["a", "b", "c"],
        "classification": ["HUMAN", "HUMAN", "FULL"],
        "chatbot_refused": [True, True, False],
        "doc_overlap": [0.4, 0.01, 0.9],
        "nearest_doc_sections": ["X (40%)", "(none)", "Y (90%)"],
        "summary": ["s", "s", "s"],
    })
    lm = bt.likely_misses(results, min_overlap=0.25)
    assert list(lm["ticket_id"]) == ["a"]          # refused + high overlap only


def test_wilson_ci():
    lo, hi = bt.wilson_ci(2, 33)                        # the real deflection point
    assert (round(lo, 3), round(hi, 3)) == (0.017, 0.196)
    assert lo < 2 / 33 < hi
    assert bt.wilson_ci(0, 0) == (0.0, 0.0)
    lo0, hi0 = bt.wilson_ci(0, 20)
    assert lo0 == 0.0 and 0 < hi0 < 0.2
    m = bt.calculate_metrics(pd.DataFrame({"classification": ["FULL", "HUMAN", "HUMAN"]}))
    assert m["deflection_ci95_low"] <= m["potential_deflection_rate"] <= m["deflection_ci95_high"]


def test_metrics_report_cost_and_latency():
    results = pd.DataFrame({
        "classification": ["FULL", "HUMAN", "HUMAN"],
        "latency_s": [2.0, 4.0, 30.0],
        "chatbot_refused": [False, True, True],
        "evaluator_fallback": [False, False, False],
        "chatbot_error": ["", "", ""],
    })
    cfg = bt.BacktestConfig(run_id="t", eval_batch_size=15)
    m = bt.calculate_metrics(results, cfg)
    assert m["est_chatbot_calls"] == 6            # 3 tickets * 2 (verify on)
    assert m["est_evaluator_calls"] == 1
    assert m["latency_s_p50"] == 4.0
    assert m["likely_miss_count"] == 0            # no doc_overlap column


def test_run_backtest_verify_override(tmp_path):
    import config as cfgmod
    t = pd.DataFrame({"ticket_id": ["V1"], "summary": ["How do I add a patient?"]})
    cfg = bt.BacktestConfig(run_id="v", batch_size=1)
    before = cfgmod.VERIFY_ANSWERS
    bt.run_backtest(t, cfg, responses_path=tmp_path / "r.csv",
                    verify_answers=False, progress=lambda *_: None)
    assert cfgmod.VERIFY_ANSWERS == before        # restored after the run


def test_failure_patterns_separate_from_primary(tmp_path):
    results = pd.DataFrame({
        "ticket_id": ["a", "b"],
        "classification": ["HUMAN", "FULL"],
        "evaluation_reason": ["Requires system access and admin permission", "fine"],
        "chatbot_response": ["x", "y"],
    })
    fp = bt.failure_patterns(results)
    assert "requires_system_access" in set(fp["patterns"])
