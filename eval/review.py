"""Blind human judgment export/import; no invented model-judge scores."""

import argparse
import hashlib
import json
from pathlib import Path

from rag.evaluation import aggregate

SCORES = ["faithfulness", "groundedness", "relevance", "citation_correctness"]


def export(result_path, output):
    results = json.loads(Path(result_path).read_text())
    fingerprint = hashlib.sha256(Path(result_path).read_bytes()).hexdigest()
    rows = []
    for run in results["runs"]:
        for question in run["questions"]:
            # Stable blind identifier deliberately hides configuration from reviewers.
            blind_id = hashlib.sha256((run["id"] + question["question_id"]).encode()).hexdigest()[:16]
            rows.append(
                {
                    "blind_id": blind_id,
                    "question": question["question"],
                    "answer": question["answer"]["answer"],
                    "citations": question["answer"]["citations"],
                    "reviewer": "",
                    "scores": dict.fromkeys(SCORES),
                    "notes": "",
                }
            )
    import random

    random.Random(42).shuffle(rows)
    Path(output).write_text(json.dumps({"results_sha256": fingerprint, "reviews": rows}, indent=2))


def ingest(result_path, annotations, output):
    results = json.loads(Path(result_path).read_text())
    reviewed = json.loads(Path(annotations).read_text())
    fingerprint = hashlib.sha256(Path(result_path).read_bytes()).hexdigest()
    if reviewed.get("results_sha256") != fingerprint:
        raise ValueError("Annotations belong to another results artifact")
    lookup = {
        hashlib.sha256((run["id"] + q["question_id"]).encode()).hexdigest()[:16]: run["id"]
        for run in results["runs"]
        for q in run["questions"]
    }
    scores, seen = {}, set()
    for row in reviewed["reviews"]:
        bid = row["blind_id"]
        if bid not in lookup or bid in seen:
            raise ValueError("Unknown or duplicate review identifier")
        seen.add(bid)
        if not row["reviewer"].strip():
            raise ValueError("Every imported annotation requires a named reviewer")
        if set(row["scores"]) != set(SCORES):
            raise ValueError("All four rubric dimensions required")
        if any(
            not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 1 for v in row["scores"].values()
        ):
            raise ValueError("Scores must be numbers in [0,1]")
        scores.setdefault(lookup[bid], []).append(row["scores"])
    if seen != set(lookup):
        raise ValueError("Incomplete review batch; score every answer")
    Path(output).write_text(
        json.dumps(
            {"results_sha256": fingerprint, "human_judgments": {k: aggregate(v) for k, v in scores.items()}}, indent=2
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["export", "import"])
    p.add_argument("results")
    p.add_argument("output")
    p.add_argument("--annotations")
    args = p.parse_args()
    if args.action == "export":
        export(args.results, args.output)
    else:
        if not args.annotations:
            p.error("--annotations required")
        ingest(args.results, args.annotations, args.output)
