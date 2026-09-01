import eval_run


def test_bootstrap_ci_bounds():
    lo, hi = eval_run.bootstrap_ci([1.0] * 10)
    assert lo == hi == 1.0
    lo, hi = eval_run.bootstrap_ci([0.0, 1.0] * 20)
    assert 0.0 <= lo <= 0.5 <= hi <= 1.0


def test_cohens_kappa_perfect_and_chance():
    assert eval_run.cohens_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0
    k = eval_run.cohens_kappa([1, 1, 0, 0], [1, 0, 1, 0])
    assert -1.0 <= k <= 0.2


def test_run_case_answer_and_refuse_behaviour():
    ans = eval_run.run_case(
        {"id": "t1", "question": "How do I void a payment?",
         "expected_behavior": "answer", "expected_section": "Void a payment",
         "must_include": ["Void", "deposit"]},
        with_judge=False,
    )
    assert ans.behavior_correct
    assert ans.must_include_hits == ans.must_include_total == 2

    ref = eval_run.run_case(
        {"id": "t2", "question": "Tell me a joke unrelated to the product",
         "expected_behavior": "refuse", "expected_section": None},
        with_judge=False,
    )
    assert ref.behavior_correct and not ref.answered


def test_build_scorecard_slices():
    results = [
        eval_run.run_case({"id": "a", "question": "How do I void a payment?",
                           "expected_behavior": "answer", "expected_section": "Void a payment",
                           "must_include": ["Void"]}, with_judge=False),
        eval_run.run_case({"id": "b", "question": "random off-topic question",
                           "expected_behavior": "refuse", "expected_section": None},
                          with_judge=False),
    ]
    card = eval_run.build_scorecard(results)
    assert card.metrics["answer_slice"]["n"] == 1
    assert card.metrics["refuse_slice"]["n"] == 1
    assert 0.0 <= card.metrics["behavior_accuracy"]["value"] <= 1.0
