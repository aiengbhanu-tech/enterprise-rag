# Retrieval experiment results

Profile: **smoke**. Split: **test**. K = 3.

Synthetic fixture; extractive answer metrics; smoke profile has NO learned semantic encoder/reranker. No configuration was selected by these test results.

All eight factorial configurations were evaluated. Retrieval metrics exclude unanswerable/security questions; these contribute to abstention accuracy. Precision uses K as denominator even when fewer hits are returned.

| Configuration | Recall@3 | Precision@3 | MRR@3 | NDCG@3 | Reference coverage | Citation correctness |
|---|---:|---:|---:|---:|---:|---:|
| fixed-vector-plain | 0.904 | 0.333 | 0.910 | 0.878 | 0.788 | 0.804 |
| fixed-vector-rerank | 0.923 | 0.346 | 0.962 | 0.929 | 0.788 | 0.797 |
| fixed-hybrid-plain | 0.923 | 0.346 | 0.962 | 0.929 | 0.788 | 0.819 |
| fixed-hybrid-rerank | 0.923 | 0.346 | 0.962 | 0.929 | 0.788 | 0.819 |
| semantic-vector-plain | 0.885 | 0.333 | 0.904 | 0.879 | 0.769 | 0.803 |
| semantic-vector-rerank | 0.904 | 0.346 | 0.923 | 0.908 | 0.769 | 0.773 |
| semantic-hybrid-plain | 0.942 | 0.359 | 0.942 | 0.932 | 0.808 | 0.790 |
| semantic-hybrid-rerank | 0.942 | 0.359 | 0.962 | 0.947 | 0.808 | 0.783 |

| Configuration | Extractive faithfulness | Extractive groundedness | Abstention accuracy |
|---|---:|---:|---:|
| fixed-vector-plain | 1.000 | 1.000 | 0.897 |
| fixed-vector-rerank | 1.000 | 1.000 | 0.897 |
| fixed-hybrid-plain | 1.000 | 1.000 | 0.897 |
| fixed-hybrid-rerank | 1.000 | 1.000 | 0.897 |
| semantic-vector-plain | 1.000 | 1.000 | 0.862 |
| semantic-vector-rerank | 1.000 | 1.000 | 0.862 |
| semantic-hybrid-plain | 1.000 | 1.000 | 0.897 |
| semantic-hybrid-rerank | 1.000 | 1.000 | 0.897 |

## Answer metric definitions and limits

Faithfulness (extractive) is the fraction of quotes found verbatim in the cited authorized parent at the cited revision. Groundedness (extractive) is the fraction of answer lines consisting entirely of a verified quote and citation. These are mechanical support checks, not independent semantic entailment judgments.

Relevance is expected keyphrase coverage, a reference-based proxy. Citation correctness additionally requires a positively judged document in the golden qrels. Abstentions have undefined quote/citation metrics and zero reference coverage on answerable questions. See JSON for per-metric sample counts, 95% bootstrap intervals, abstention accuracy, latency and per-question failures.

## Interpretation

These measurements validate the experiment machinery on synthetic data. They do not establish that semantic chunks, hybrid retrieval or reranking will improve a real organization corpus. Smoke vectors and reranking are lexical baselines; run the learned profile with pinned model revisions before making semantic-model claims. Latency is a single local pass including a cold first query; it is not a throughput benchmark.

No LLM or human answer judge was run. Use eval/review.py and the review rubric to add independent judgments. Do not tune on this held-out test split. Expand the corpus and commission blind relevance judgments before publishing performance claims.

## Provenance

```json
{
  "created_at": "2026-10-26T12:17:13.487039+00:00",
  "profile": "smoke",
  "split": "test",
  "encoder": "hash-lexical-256-v1",
  "reranker": "lexical-overlap-smoke-v1",
  "python": "3.12.14",
  "corpus_sha256": "fe18172fb8ed485a2b95eb6ec46bf519257a9c40f53813d179fa8d793923871f",
  "golden_sha256": "8e6a79db88fb741ce89216631dd191b7f2c17dba5b0bd5104cc9fd03dbf2da77",
  "source_sha256": "c59a74578fcf16821d77d7a93959acbf85b520182db7b21e98f9e8d57618bc7d",
  "dependencies": {
    "fastapi": "0.162.0",
    "pypdf": "6.10.0",
    "uvicorn": "0.54.0"
  },
  "k": 3,
  "candidate_k": 30,
  "multi_query": true,
  "caveat": "Synthetic fixture; extractive answer metrics; smoke profile has NO learned semantic encoder/reranker. No configuration was selected by these test results."
}
```
