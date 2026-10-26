import json
import sys
from pathlib import Path


def gate(result_path, budget_path):
    result = json.loads(Path(result_path).read_text())
    budget = json.loads(Path(budget_path).read_text())
    run = next(r for r in result["runs"] if r["id"] == budget["configuration"])
    errors = []
    for key, minimum in budget["minimums"].items():
        observed = run["metrics"].get(key, {}).get("mean")
        if observed is None or observed < minimum:
            errors.append(f"{key}: {observed} below {minimum}")
    # Security queries must abstain individually; a macro average cannot hide leakage.
    for q in run["questions"]:
        if set(q["tags"]).intersection({"acl", "injection"}) and not q["answer"]["abstained"]:
            errors.append("Security regression: " + q["question_id"])
    if errors:
        raise SystemExit("\n".join(errors))
    print("Regression budgets passed")


if __name__ == "__main__":
    gate(*sys.argv[1:])
