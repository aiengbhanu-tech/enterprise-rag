# Initial measured results and failures

The authoritative complete report is `eval/results/smoke/REPORT.md`; raw per-question output and paired intervals are in `results.json`. Open `index.html` for expandable runs. These are synthetic smoke results using lexical vectors and a lexical reranker, not pretrained semantic-model results.

At K=3 on the 26 answerable test questions:

| Configuration | Recall | MRR | NDCG | Expected phrase coverage |
|---|---:|---:|---:|---:|
| Fixed chunks / vector / no reranker | 0.904 | 0.910 | 0.878 | 0.788 |
| Semantic-boundary pipeline / hybrid / lexical reranker | 0.942 | 0.962 | 0.947 | 0.808 |

The second row changes three factors and is **not** a causal attribution to one component. Use the paired one-factor contrasts in the raw report for those questions. These descriptive improvements cannot support pretrained semantic-model or real-company claims.

## Useful counterexamples

- `q13`: The correct production-release document is retrieved at rank 1, but the sentence selector chooses an adjacent rollback sentence instead of the integration-test requirement. Recall=1 and MRR=1 coexist with reference coverage=0.
- `q16`: The contractor approval question misses the correct document, returning expense/procurement/release neighbors. Exact lexical forms such as `approves` versus `approval` expose the limitations of the smoke encoders.
- `q26` and `q27`: Multi-query expansion retrieves the disaster-recovery and SSO documents, but the extractive answerer's conservative overlap test still abstains. Correct retrieval does not imply a successful answer.
- `q32`: Only one of two required documents is present. The system retrieves the access-review document but misses credential rotation, giving Recall=0.5 and reference coverage=0.5.
- Turning reranking on for semantic/hybrid slightly decreases citation correctness, from approximately 0.790 to 0.783, while increasing NDCG from approximately 0.932 to 0.947. This demonstrates why ranking metrics and answer/citation metrics need separate inspection.

Exact quote support and groundedness are 1.0 for returned extracts by construction. That is not proof that the selected quotes answer the question: citation correctness is about 0.783 and expected phrase coverage about 0.808 for semantic/hybrid/rerank. Quote scores include 23 non-abstaining answers, while reference coverage includes all 26 answerable questions; missing-denominator disclosure would make this report misleading.

## Next experiments, without claiming outcomes

Run the unchanged factorial suite with pinned pretrained models. Use dev examples to evaluate a semantic answer selector or a carefully constrained generative answerer, with independent human/entailment judgments. Build a fresh real-company test set before selecting a production configuration. Add timestamp/source-authority labels to study archived proposals, contradiction handling and temporal correctness. Load-test corpus size, ACL selectivity and p95 latency separately from quality.
