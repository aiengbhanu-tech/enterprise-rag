"""Auditable extractive answering: no tools, SQL, network or free-form instructions.

This intentionally returns evidence quotes, not unvalidated LLM paraphrases. A
future generative adapter must pass the same permission and citation checks plus
an independent entailment evaluator before deployment.
"""

from .chunking import sentences
from .models import tokens
from .retrieval import RetrievalConfig
from .security import quarantine, redact


class Answerer:
    def __init__(self, retriever):
        self.retriever = retriever

    def ask(self, principal, question, session="default", config=None, filters=None):
        question = redact(question)
        if quarantine(question):
            return {
                "answer": "This request was blocked by the instruction safety policy.",
                "citations": [],
                "abstained": True,
                "queries": [],
            }
        history = self.retriever.store.history(principal, session)
        result = self.retriever.search(principal, question, config or RetrievalConfig(), filters, history)
        terms = set(tokens(result["queries"][0] if result["queries"] else question))
        citations = []
        for hit in result["hits"]:
            choices = sentences(hit["parent_text"])
            if not choices:
                continue
            quote = max(choices, key=lambda s: len(terms.intersection(tokens(s))))
            overlap = len(terms.intersection(tokens(quote)))
            if overlap < min(2, len(terms)) or not terms:
                continue
            citations.append(
                {
                    "label": f"S{len(citations) + 1}",
                    "quote": quote,
                    **{
                        k: hit[k]
                        for k in [
                            "document_id",
                            "external_id",
                            "parent_id",
                            "revision",
                            "source",
                            "title",
                            "uri",
                            "page",
                        ]
                    },
                }
            )
        answer = "\n".join(f"{c['quote']} [{c['label']}]" for c in citations)
        if not answer:
            answer = "I could not find sufficient authorized evidence."
        self.retriever.store.remember(principal, session, question)
        return {"answer": answer, "citations": citations, "abstained": not citations, "queries": result["queries"]}
