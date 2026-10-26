"""Document-ranked metrics and explicitly extractive answer checks."""

import math
import random
from statistics import mean


def retrieval_metrics(ranked, qrels, k):
    # Collapse multiple parents/children to document rank; pad precision denominator to K.
    ranked = list(dict.fromkeys(ranked))[:k]
    positive = {doc for doc, grade in qrels.items() if grade > 0}
    if not positive:
        return None  # unanswerable/security queries are a separate cohort
    relevant = [int(doc in positive) for doc in ranked]
    dcg = sum((2 ** qrels.get(doc, 0) - 1) / math.log2(i + 2) for i, doc in enumerate(ranked))
    ideal = sorted(qrels.values(), reverse=True)[:k]
    idcg = sum((2**grade - 1) / math.log2(i + 2) for i, grade in enumerate(ideal))
    return {
        "recall": sum(relevant) / len(positive),
        "precision": sum(relevant) / k,
        "mrr": next((1 / (i + 1) for i, value in enumerate(relevant) if value), 0),
        "ndcg": dcg / idcg if idcg else 0,
    }


def answer_metrics(answer, case, hits):
    citations = answer["citations"]
    expected_abstain = not any(case["qrels"].values())
    by_parent = {hit["parent_id"]: hit for hit in hits}

    def exact_support(c):
        hit = by_parent.get(c["parent_id"])
        return bool(
            hit
            and c["quote"] in hit["parent_text"]
            and c["revision"] == hit["revision"]
            and c["external_id"] == hit["external_id"]
        )

    support = [exact_support(c) for c in citations]
    # Every nonempty answer line must be exactly a source quote plus its citation.
    supported_lines = {f"{c['quote']} [{c['label']}]" for c in citations if exact_support(c)}
    lines = [line for line in answer["answer"].splitlines() if line.strip()]
    required = case.get("expected_phrases", [])
    text = " ".join(c["quote"] for c in citations).lower()
    return {
        "faithfulness_extractive": mean(support) if citations else None,
        "groundedness_extractive": sum(line in supported_lines for line in lines) / len(lines) if citations else None,
        "relevance_reference_coverage": mean(phrase.lower() in text for phrase in required) if required else None,
        "citation_correctness": mean(
            ok and case["qrels"].get(c["external_id"], 0) > 0 for ok, c in zip(support, citations, strict=True)
        )
        if citations
        else None,
        "abstention_correct": float(answer["abstained"] == expected_abstain),
    }


def bootstrap(values, seed=42, iterations=2000):
    if not values:
        return [None, None]
    rng = random.Random(seed)
    samples = sorted(mean(rng.choices(values, k=len(values))) for _ in range(iterations))
    return [samples[int(iterations * 0.025)], samples[int(iterations * 0.975)]]


def aggregate(rows):
    result = {}
    keys = set().union(*(r.keys() for r in rows)) if rows else set()
    for key in sorted(keys):
        values = [r[key] for r in rows if r.get(key) is not None]
        result[key] = {"mean": mean(values) if values else None, "n": len(values), "ci95": bootstrap(values)}
    return result
