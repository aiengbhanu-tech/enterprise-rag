# Evaluation protocol

## Golden dataset

`data/corpus.json` is a synthetic company knowledge fixture. `data/golden.jsonl` contains explicit question ids, split labels, graded document relevance, expected answer phrases, authorization groups and scenario tags. The fixture author defined facts and relevance labels independently of retrieval outputs; labels have not received independent human validation. `scripts/make_fixture.py` regenerates it exactly.

There are 35 questions: six development questions, 26 answerable test questions and three test cases for denied access, out-of-domain knowledge and instruction attacks. Four test questions require multiple documents. There are 39 documents including overlap-heavy distractors, a restricted executive document, a quarantined malicious document and a contact containing redacted PII. Synthetic qrels are exhaustive by construction; for real collections do not treat unjudged documents as proven irrelevant without pooled judgments.

The current dataset is a smoke/regression fixture, not a representative company benchmark. It has repeated filler, few questions, one language and manually constructed paraphrases. Parent IDs vary across chunking methods, so retrieval metrics rank **unique external document ids**, not raw chunks. Multiple returned parents from the same document collapse to one rank; retrieval has a passage K budget, so fewer than K unique docs can remain. Reference coverage adds an answer-bearing check that document-level recall alone cannot provide.

## Metrics

For positively judged documents R and unique retrieved document ranks d1…dK:

- Recall@K = relevant documents retrieved / all relevant documents.
- Precision@K = relevant documents retrieved / K, including missing-result slots.
- MRR@K = reciprocal rank of the first relevant document, or zero.
- NDCG@K = DCG / ideal DCG, with gain `2^relevance - 1` and discount `log2(rank + 1)`.

The qrel grade range is 0–3. Current positive fixture labels use grade 3; unit tests verify genuinely graded examples using unequal gains. No-positive cases have undefined retrieval metrics and are excluded, with explicit sample counts.

Answer measures are deliberately separated:

| Measure | Automated implementation | Limit |
|---|---|---|
| Faithfulness, extractive | Fraction of quotes contained verbatim in cited authorized evidence at the cited revision | Does not judge semantic entailment of free-form prose |
| Groundedness, extractive | Fraction of answer lines composed only of a verified quote and citation | Checks mechanical support, not independent factual truth |
| Relevance proxy | Fraction of expected gold phrases appearing in answer quotes | Wording-sensitive; not a general semantic relevance judge |
| Citation correctness | Fraction of citations both exactly supported and associated with positively judged documents | Needs validated, exhaustive qrels |
| Abstention accuracy | Whether the system abstained iff the fixture had no authorized answer | Aggregate can hide scenario-specific failures; inspect per-query rows |

Quote/citation scores are null for abstentions, not automatically perfect. Reference coverage is zero on answerable abstentions. Always publish the `n` denominator with any average. All four human rubric scores remain unmeasured until actual annotations are imported.

## Factorial experiment

The full 2 × 2 × 2 experiment varies fixed/semantic chunks, vector/hybrid retrieval and reranking off/on. Query rewriting, multi-query expansion, ACLs, filters, child budget 80 words, parent budget 320 words, candidate pool 30 and result K=3 are held constant. Semantic boundaries use adjacent normalized embedding cosine below 0.35. These constants were defined in the implementation; they have not been optimized on the test split. Smoke boundaries use lexical vectors and cannot substantiate semantic-model claims.

The runner logs model fingerprints, corpus/golden/source hashes, Python/dependency versions, index timings, per-query rankings, answers, metric denominators and latency. Every configuration gets a fresh user session per question to prevent memory contamination. Paired contrasts change one factor at a time on the same question set. Seeded 2,000-resample percentile bootstrap intervals quantify fixture sampling variability, not generalization to future companies. The single-pass latency includes cold effects and is not a load test.

`eval/budgets.json` is a loose smoke regression contract. It is not proof of production relevance or a pre-registered hypothesis. The committed static report publishes the initial frozen experiment. If you iterate after examining it, version the fixture and reserve a newly labeled untouched test set before making comparative claims.

## Blind human review

Export with `python -m eval.review export ...`. The export randomizes tasks and hides configuration names behind stable opaque ids. Reviewers see the question, answer and citations; obtain the full authorized reference passages from the matching run when judging sufficiency. For a real evaluation, label at least two independent reviewers and adjudicate disagreement; the supplied importer handles one complete reviewer batch at a time, which can be combined after adjudication.

Score each dimension 0, 0.5 or 1 using this rubric (the importer allows finer [0,1] values for an agreed rubric):

- Faithfulness: 1 all answer claims follow from evidence, 0.5 partly supported, 0 unsupported claims dominate.
- Groundedness: 1 all factual claims have sufficient identified supporting evidence, 0.5 some gaps, 0 evidence absent or contradictory.
- Relevance: 1 directly and sufficiently answers the actual question, 0.5 partial or distracting, 0 fails to answer. For unanswerable cases, a correct clear abstention can score 1.
- Citation correctness: 1 cited passages support the associated claims and resolve to the correct accessible revision; 0.5 partial or ambiguous; 0 wrong/inaccessible. For a correct abstention with no claims, use 1 under this human rubric and record the convention.

Import requires every task, numeric scores, a reviewer identity, no duplicates and the exact source artifact fingerprint. It rejects blank placeholder scores and never invents judges. Human scores are output separately from automated support checks.

## Publishing real results

1. Freeze requirements, code, model commits, chunk budgets and a corpus snapshot with ACLs.
2. Commission real questions from employees, including multi-hop, temporal, ambiguous and unanswerable cases; split by topic/document family to reduce leakage.
3. Pool candidates across systems for blind graded judgments and answer-bearing passage labels.
4. Tune only on dev. Rebuild and evaluate every frozen configuration on held-out test.
5. Add independent answer review, permission-attack tests, deletion/revocation freshness and realistic concurrent load tests.
6. Publish all configurations, paired effect sizes with intervals, metric definitions, failure examples, costs and limitations. Publish only approved/de-identified corpora and examples.

The included HTML/Markdown/JSON reports are publication artifacts. They have not been uploaded to a public website or external repository.
