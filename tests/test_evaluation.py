import math

import pytest

from rag.evaluation import aggregate, answer_metrics, bootstrap, retrieval_metrics


def test_metric_hand_calculated_example():
    result = retrieval_metrics(["wrong", "b", "a"], {"a": 3, "b": 1}, 3)
    assert result["recall"] == 1
    assert result["precision"] == 2 / 3
    assert result["mrr"] == 1 / 2
    expected = (1 / math.log2(3) + 7 / math.log2(4)) / (7 + 1 / math.log2(3))
    assert result["ndcg"] == pytest.approx(expected)


def test_duplicate_ranks_missing_results_and_unanswerable():
    result = retrieval_metrics(["a", "a"], {"a": 1, "b": 1}, 5)
    assert result["recall"] == 0.5 and result["precision"] == 0.2
    assert retrieval_metrics([], {}, 5) is None
    assert retrieval_metrics([], {"a": 1}, 5)["mrr"] == 0
    assert bootstrap([1, 1, 1]) == [1, 1]


def test_null_metrics_excluded_and_ci_reproducible():
    result = aggregate([{"x": None}, {"x": 0.5}, {"x": 1}])
    assert result["x"]["n"] == 2 and result["x"]["mean"] == 0.75
    assert bootstrap([0, 1, 0.3]) == bootstrap([0, 1, 0.3])


def test_fabricated_citation_fails_support_checks():
    c = {"label": "S1", "quote": "Invented answer.", "parent_id": "p", "revision": "v", "external_id": "doc"}
    answer = {"answer": "Invented answer. [S1]", "citations": [c], "abstained": False}
    case = {"qrels": {"doc": 3}, "expected_phrases": ["actual fact"]}
    hits = [{"parent_id": "p", "parent_text": "Actual fact.", "revision": "v", "external_id": "doc"}]
    metrics = answer_metrics(answer, case, hits)
    assert metrics["faithfulness_extractive"] == 0
    assert metrics["groundedness_extractive"] == 0
    assert metrics["citation_correctness"] == 0
