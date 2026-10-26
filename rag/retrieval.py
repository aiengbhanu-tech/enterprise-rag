import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from .models import cosine, tokens
from .types import allowed


@dataclass(frozen=True)
class RetrievalConfig:
    mode: str = "hybrid"
    rerank: bool = True
    multi_query: bool = True
    k: int = 5
    candidate_k: int = 30
    max_context_chars: int = 12000

    def __post_init__(self):
        if self.mode not in {"vector", "bm25", "hybrid"} or not 1 <= self.k <= self.candidate_k <= 100:
            raise ValueError("Invalid retrieval configuration")


class QueryPlanner:
    """Transparent baseline rewriting. Replace/extend with evaluated domain expansions."""

    expansions = {
        "pto": "paid time off annual leave",
        "sso": "single sign on authentication",
        "dr": "disaster recovery",
        "pii": "personally identifiable information",
        "onboarding": "new employee setup",
        "incident": "outage response",
    }

    def plan(self, question, history=(), multi=True):
        rewritten = question.strip()
        if history and re.search(r"\b(it|that|those|they|its|their)\b", question, re.IGNORECASE):
            rewritten = history[-1] + " Follow-up: " + question
        result = [rewritten]
        if multi:
            expanded = rewritten
            for word, value in self.expansions.items():
                expanded = re.sub(rf"\b{word}\b", value, expanded, flags=re.IGNORECASE)
            if expanded != rewritten:
                result.append(expanded)
            compact = " ".join(tokens(rewritten))
            if compact and compact not in result:
                result.append(compact)
        return result[:3]


def bm25(query, texts):
    bags = [Counter(tokens(t)) for t in texts]
    n = len(bags)
    if not n:
        return []
    avg = sum(sum(b.values()) for b in bags) / n or 1
    scores = [0.0] * n
    for term in set(tokens(query)):
        df = sum(term in bag for bag in bags)
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        for i, bag in enumerate(bags):
            tf = bag[term]
            denominator = tf + 1.2 * (0.25 + 0.75 * sum(bag.values()) / avg)
            scores[i] += idf * tf * 2.2 / denominator
    return scores


def rrf(rankings, constant=60):
    scores = defaultdict(float)
    for ranking in rankings:
        for rank, index in enumerate(ranking, 1):
            scores[index] += 1 / (constant + rank)
    return scores


class Retriever:
    def __init__(self, store, embedder, reranker):
        self.store, self.embedder, self.reranker = store, embedder, reranker
        self.planner = QueryPlanner()

    def search(self, principal, question, config=None, filters=None, history=()):
        config = config or RetrievalConfig()
        filters = filters or {}
        # ACL and metadata restriction BEFORE BM25 statistics, dense scoring or reranking.
        rows = [
            r
            for r in self.store.rows(principal.tenant)
            if allowed(json.loads(r["acl"]), principal)
            and all(json.loads(r["metadata"]).get(key) == value for key, value in filters.items())
        ]
        if len(rows) > 50000:
            raise RuntimeError("Reference backend limit exceeded; migrate to ACL-filtered search backend")
        if not rows:
            return {"queries": [], "hits": []}
        if any(r["encoder"] != self.embedder.name for r in rows):
            raise RuntimeError("Embedding fingerprint changed: reindex before querying")
        texts = [r["text"] for r in rows]
        queries = self.planner.plan(question, history, config.multi_query)
        ranks = []
        for query in queries:
            if config.mode in {"bm25", "hybrid"}:
                scores = bm25(query, texts)
                ranks.append(
                    sorted((i for i in range(len(rows)) if scores[i] > 0), key=lambda i: (-scores[i], rows[i]["id"]))[
                        : config.candidate_k
                    ]
                )
            if config.mode in {"vector", "hybrid"}:
                qv = self.embedder.encode([query])[0]
                scores = [cosine(qv, json.loads(r["vector"])) for r in rows]
                ranks.append(sorted(range(len(rows)), key=lambda i: (-scores[i], rows[i]["id"]))[: config.candidate_k])
        fused = rrf(ranks)
        candidates = sorted(fused, key=lambda i: (-fused[i], rows[i]["id"]))[: config.candidate_k]
        if config.rerank and candidates:
            scores = self.reranker.score(queries[0], [texts[i] for i in candidates])
            score_map = dict(zip(candidates, scores, strict=True))
            candidates.sort(key=lambda i: (-score_map[i], -fused[i], rows[i]["id"]))
        else:
            score_map = fused
        hits, parents, duplicate_content = [], set(), set()
        used = 0
        for i in candidates:
            row = rows[i]
            # Duplicate aliases with identical content produce one evidence item; distinct
            # parents within the same document can still contribute separate passages.
            content_key = (row["content_hash"], row["page"], row["parent_text"])
            if row["parent_id"] in parents or content_key in duplicate_content:
                continue
            if used + len(row["parent_text"]) > config.max_context_chars:
                continue
            parents.add(row["parent_id"])
            duplicate_content.add(content_key)
            used += len(row["parent_text"])
            hits.append(
                {
                    key: row[key]
                    for key in [
                        "id",
                        "parent_id",
                        "document_id",
                        "external_id",
                        "title",
                        "uri",
                        "source",
                        "page",
                        "text",
                        "parent_text",
                        "revision",
                    ]
                }
                | {"score": float(score_map[i]), "fusion_score": fused[i]}
            )
            if len(hits) >= config.k:
                break
        return {"queries": queries, "hits": hits}
