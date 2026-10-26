import pytest

from rag.answer import Answerer
from rag.chunking import chunk_page
from rag.models import HashEmbedding
from rag.retrieval import RetrievalConfig, bm25, rrf
from rag.types import Document, Principal


def test_acl_before_every_scorer(stack, alice, doc):
    store, embed, retriever = stack
    store.sync(
        "acme",
        "wiki",
        [doc, Document("secret", "Secret", ["Secret payroll compensation 9000000."], ["group:executive"])],
        embed,
    )

    # A guard scorer fails if unauthorized content ever reaches reranking.
    class Guard:
        def score(self, query, texts):
            assert all("Secret" not in t for t in texts)
            return [0] * len(texts)

    retriever.reranker = Guard()
    for mode in ["vector", "bm25", "hybrid"]:
        result = retriever.search(alice, "Secret payroll annual leave", RetrievalConfig(mode=mode))
        assert {h["external_id"] for h in result["hits"]} <= {"policy"}
    assert not retriever.search(Principal("other", "alice", ("engineering",)), "annual leave")["hits"]
    assert not retriever.search(Principal("acme", "bob"), "annual leave")["hits"]
    assert not retriever.search(Principal("acme", "admin", (), True), "annual leave")["hits"]


def test_metadata_filter_and_parent_expansion(stack, alice, doc):
    store, embed, retriever = stack
    store.sync("acme", "wiki", [doc], embed)
    assert not retriever.search(alice, "annual leave", filters={"department": "engineering"})["hits"]
    hit = retriever.search(alice, "annual leave", filters={"department": "hr"})["hits"][0]
    assert "direct manager" in hit["parent_text"]
    assert hit["text"] in hit["parent_text"]
    assert hit["page"] == 1


def test_rewrite_and_multi_query(stack):
    planner = stack[2].planner
    queries = planner.plan("How much PTO do we get?", multi=True)
    assert any("paid time off" in q for q in queries)
    assert len(planner.plan("How much PTO?", multi=False)) == 1
    assert "annual leave" in planner.plan("Who approves it?", ["annual leave"], False)[0]


def test_embedding_change_requires_reindex(stack, alice, doc):
    store, embed, retriever = stack
    store.sync("acme", "wiki", [doc], embed)
    embed.name = "new-fingerprint"
    with pytest.raises(RuntimeError, match="reindex"):
        retriever.search(alice, "annual leave")


def test_citations_are_exact_authorized_quotes(stack, alice, doc):
    store, embed, retriever = stack
    store.sync("acme", "wiki", [doc], embed)
    answer = Answerer(retriever).ask(alice, "How many annual leave days do employees receive?")
    assert not answer["abstained"]
    assert answer["citations"][0]["quote"] in doc.pages[0]
    assert answer["citations"][0]["revision"]
    assert "[S1]" in answer["answer"]


def test_page_boundaries_and_hard_chunk_budgets():
    for strategy in ["fixed", "semantic"]:
        parents = chunk_page("one " * 1000, HashEmbedding(), strategy)
        assert all(len(parent.split()) <= 320 for parent, _ in parents)
        assert all(len(child.split()) <= 80 for _, children in parents for child in children)
        assert sum(len(c.split()) for _, children in parents for c in children) == 1000


def test_bm25_and_rrf_known_order():
    scores = bm25("retention", ["backup retention retention", "annual leave"])
    assert scores[0] > scores[1] == 0
    scores = rrf([[0, 1], [1, 0]])
    assert scores[0] == scores[1]


def test_duplicate_content_never_widens_acl(stack, alice):
    store, embed, retriever = stack
    body = ["Payroll budget is restricted to executive approval."]
    store.sync(
        "acme",
        "drive",
        [
            Document("one", "Private", body, ["group:executive"]),
            Document("two", "Shared", body, ["group:engineering"]),
            Document("three", "Alias", body, ["group:engineering"]),
        ],
        embed,
    )
    hits = retriever.search(alice, "Payroll budget")["hits"]
    assert len(hits) == 1 and hits[0]["external_id"] in {"two", "three"}
    assert not retriever.search(Principal("acme", "bob"), "Payroll budget")["hits"]
