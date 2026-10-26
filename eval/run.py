import argparse
import hashlib
import importlib.metadata
import itertools
import json
import platform
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from rag.answer import Answerer
from rag.connectors import export_json
from rag.evaluation import aggregate, answer_metrics, bootstrap, retrieval_metrics
from rag.models import (
    CrossEncoderReranker,
    DenseEmbedding,
    HashEmbedding,
    LexicalReranker,
)
from rag.retrieval import RetrievalConfig, Retriever
from rag.store import Store
from rag.types import Principal

ROOT = Path(__file__).resolve().parents[1]


def run(profile="smoke", out=None, split="test", embed_revision=None, rerank_revision=None):
    if profile == "learned" and not (embed_revision and rerank_revision):
        raise ValueError("Learned benchmark requires --embed-revision and --rerank-revision commit hashes")
    out = Path(out or ROOT / "eval/results" / profile)
    out.mkdir(parents=True, exist_ok=True)
    embed = HashEmbedding() if profile == "smoke" else DenseEmbedding(revision=embed_revision)
    reranker = LexicalReranker() if profile == "smoke" else CrossEncoderReranker(revision=rerank_revision)
    docs, _, _ = export_json(ROOT / "data/corpus.json")
    cases = [json.loads(line) for line in (ROOT / "data/golden.jsonl").read_text().splitlines()]
    cases = [c for c in cases if c["split"] == split]
    manifest = {
        "created_at": datetime.now(UTC).isoformat(),
        "profile": profile,
        "split": split,
        "encoder": embed.name,
        "reranker": reranker.name,
        "python": platform.python_version(),
        "corpus_sha256": hashlib.sha256((ROOT / "data/corpus.json").read_bytes()).hexdigest(),
        "golden_sha256": hashlib.sha256((ROOT / "data/golden.jsonl").read_bytes()).hexdigest(),
        "source_sha256": hashlib.sha256(
            b"".join(p.read_bytes() for p in sorted([*(ROOT / "rag").glob("*.py"), *(ROOT / "eval").glob("*.py")]))
        ).hexdigest(),
        "dependencies": {name: importlib.metadata.version(name) for name in ["fastapi", "pypdf", "uvicorn"]},
        "k": 3,
        "candidate_k": 30,
        "multi_query": True,
        "caveat": "Synthetic fixture; extractive answer metrics; smoke profile has NO learned semantic encoder/reranker. No configuration was selected by these test results.",
    }
    runs = []
    with tempfile.TemporaryDirectory() as tmp:
        for chunking in ["fixed", "semantic"]:
            store = Store(Path(tmp) / f"{chunking}.sqlite")
            started = time.perf_counter()
            stats = store.sync("acme", "fixture", docs, embed, strategy=chunking)
            index_seconds = time.perf_counter() - started
            retriever = Retriever(store, embed, reranker)
            answerer = Answerer(retriever)
            for mode, rerank in itertools.product(["vector", "hybrid"], [False, True]):
                config = RetrievalConfig(mode=mode, rerank=rerank, k=3)
                rows, details = [], []
                for case in cases:
                    p = Principal("acme", "evaluator", tuple(case["groups"]))
                    started = time.perf_counter()
                    result = retriever.search(p, case["question"], config, case.get("filters"))
                    retrieval_ms = (time.perf_counter() - started) * 1000
                    # Unique sessions ensure no cross-question memory contamination.
                    answer = answerer.ask(
                        p,
                        case["question"],
                        session=case["id"] + str(rerank) + mode,
                        config=config,
                        filters=case.get("filters"),
                    )
                    metrics = retrieval_metrics([h["external_id"] for h in result["hits"]], case["qrels"], 3) or {}
                    metrics.update(answer_metrics(answer, case, result["hits"]))
                    metrics["retrieval_ms"] = retrieval_ms
                    rows.append(metrics)
                    details.append(
                        {
                            "question_id": case["id"],
                            "question": case["question"],
                            "tags": case["tags"],
                            "ranked_documents": list(dict.fromkeys(h["external_id"] for h in result["hits"])),
                            "metrics": metrics,
                            "answer": answer,
                        }
                    )
                runs.append(
                    {
                        "id": f"{chunking}-{mode}-{'rerank' if rerank else 'plain'}",
                        "chunking": chunking,
                        "mode": mode,
                        "rerank": rerank,
                        "index_seconds": index_seconds,
                        "index_stats": stats,
                        "metrics": aggregate(rows),
                        "questions": details,
                    }
                )
    # Matched-question contrasts; CI measures fixture sampling uncertainty only.
    contrasts = []
    for a, b in itertools.combinations(runs, 2):
        changed = [key for key in ["chunking", "mode", "rerank"] if a[key] != b[key]]
        if len(changed) != 1:
            continue
        for metric in ["recall", "precision", "mrr", "ndcg", "relevance_reference_coverage"]:
            pairs = [
                (x["metrics"].get(metric), y["metrics"].get(metric))
                for x, y in zip(a["questions"], b["questions"], strict=True)
            ]
            delta = [y - x for x, y in pairs if x is not None and y is not None]
            contrasts.append(
                {
                    "a": a["id"],
                    "b": b["id"],
                    "changed": changed[0],
                    "metric": metric,
                    "delta_b_minus_a": mean(delta) if delta else None,
                    "ci95": bootstrap(delta),
                    "n": len(delta),
                }
            )
    result = {"manifest": manifest, "runs": runs, "paired_contrasts": contrasts}
    (out / "results.json").write_text(json.dumps(result, indent=2))
    lines = [
        "# Retrieval experiment results",
        "",
        f"Profile: **{profile}**. Split: **{split}**. K = 3.",
        "",
        manifest["caveat"],
        "",
        "All eight factorial configurations were evaluated. Retrieval metrics exclude unanswerable/security questions; these contribute to abstention accuracy. Precision uses K as denominator even when fewer hits are returned.",
        "",
        "| Configuration | Recall@3 | Precision@3 | MRR@3 | NDCG@3 | Reference coverage | Citation correctness |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in runs:

        def fmt(key, run=r):
            val = run["metrics"].get(key, {}).get("mean")
            return f"{val:.3f}" if val is not None else "N/A"

        lines.append(
            f"| {r['id']} | "
            + " | ".join(
                fmt(k)
                for k in ["recall", "precision", "mrr", "ndcg", "relevance_reference_coverage", "citation_correctness"]
            )
            + " |"
        )
    lines += [
        "",
        "| Configuration | Extractive faithfulness | Extractive groundedness | Abstention accuracy |",
        "|---|---:|---:|---:|",
    ]
    for r in runs:
        lines.append(
            "| "
            + r["id"]
            + " | "
            + " | ".join(
                f"{r['metrics'][k]['mean']:.3f}"
                for k in ["faithfulness_extractive", "groundedness_extractive", "abstention_correct"]
            )
            + " |"
        )
    lines += [
        "",
        "## Answer metric definitions and limits",
        "",
        "Faithfulness (extractive) is the fraction of quotes found verbatim in the cited authorized parent at the cited revision. Groundedness (extractive) is the fraction of answer lines consisting entirely of a verified quote and citation. These are mechanical support checks, not independent semantic entailment judgments.",
        "",
        "Relevance is expected keyphrase coverage, a reference-based proxy. Citation correctness additionally requires a positively judged document in the golden qrels. Abstentions have undefined quote/citation metrics and zero reference coverage on answerable questions. See JSON for per-metric sample counts, 95% bootstrap intervals, abstention accuracy, latency and per-question failures.",
        "",
        "## Interpretation",
        "",
        "These measurements validate the experiment machinery on synthetic data. They do not establish that semantic chunks, hybrid retrieval or reranking will improve a real organization corpus. Smoke vectors and reranking are lexical baselines; run the learned profile with pinned model revisions before making semantic-model claims. Latency is a single local pass including a cold first query; it is not a throughput benchmark.",
        "",
        "No LLM or human answer judge was run. Use eval/review.py and the review rubric to add independent judgments. Do not tune on this held-out test split. Expand the corpus and commission blind relevance judgments before publishing performance claims.",
        "",
        "## Provenance",
        "",
        "```json",
        json.dumps(manifest, indent=2),
        "```",
        "",
    ]
    (out / "REPORT.md").write_text("\n".join(lines))
    # Self-contained, escaped report for local browser inspection.
    import html

    table = "".join(
        "<tr><td>"
        + "</td><td>".join(
            html.escape(str(v))
            for v in [r["id"], *[round(r["metrics"][key]["mean"], 4) for key in ["recall", "precision", "mrr", "ndcg"]]]
        )
        + "</td></tr>"
        for r in runs
    )
    (out / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>Retrieval experiment report</title><style>body{font:16px system-ui;max-width:1100px;margin:50px auto;padding:20px;background:#111827;color:#e5e7eb}table{border-collapse:collapse;width:100%}td,th{padding:14px;border-bottom:1px solid #374151;text-align:left}pre{white-space:pre-wrap}a{color:#93c5fd}summary{cursor:pointer;padding:14px}</style><h1>Enterprise RAG · Experiment report</h1><p>'
        + html.escape(manifest["caveat"])
        + "</p><table><tr><th>Configuration</th><th>Recall@3</th><th>Precision@3</th><th>MRR@3</th><th>NDCG@3</th></tr>"
        + table
        + '</table><p><a href="results.json">Raw results and paired contrasts</a> · <a href="REPORT.md">Full report</a></p>'
        + "".join(
            "<details><summary>"
            + html.escape(r["id"])
            + "</summary><pre>"
            + html.escape(json.dumps(r["questions"], indent=2))
            + "</pre></details>"
            for r in runs
        )
    )
    print(json.dumps({"output": str(out), "runs": len(runs), "questions_per_run": len(cases), "profile": profile}))
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--profile", choices=["smoke", "learned"], default="smoke")
    p.add_argument("--out")
    p.add_argument("--split", choices=["dev", "test"], default="test")
    p.add_argument("--embed-revision")
    p.add_argument("--rerank-revision")
    a = p.parse_args()
    run(a.profile, a.out, a.split, a.embed_revision, a.rerank_revision)
