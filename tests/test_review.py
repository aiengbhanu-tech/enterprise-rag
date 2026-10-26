import json

import pytest

from eval.review import export, ingest


def test_review_requires_real_complete_judgments(tmp_path):
    result = tmp_path / "result.json"
    reviews = tmp_path / "reviews.json"
    summary = tmp_path / "human.json"
    result.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "id": "test",
                        "questions": [
                            {
                                "question_id": "q1",
                                "question": "What?",
                                "answer": {"answer": "Evidence [S1]", "citations": []},
                            }
                        ],
                    }
                ]
            }
        )
    )
    export(result, reviews)
    with pytest.raises(ValueError, match="reviewer"):
        ingest(result, reviews, summary)
    payload = json.loads(reviews.read_text())
    payload["reviews"][0]["reviewer"] = "reviewer-a"
    payload["reviews"][0]["scores"] = dict.fromkeys(
        ["faithfulness", "groundedness", "relevance", "citation_correctness"], 1
    )
    reviews.write_text(json.dumps(payload))
    ingest(result, reviews, summary)
    assert json.loads(summary.read_text())["human_judgments"]["test"]["faithfulness"]["mean"] == 1
