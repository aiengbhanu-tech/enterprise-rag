import hashlib
import math
import re
from collections import Counter

STOP = set(
    [
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "to",
        "of",
        "for",
        "in",
        "on",
        "with",
        "and",
        "or",
        "how",
        "what",
        "which",
        "can",
        "do",
        "does",
        "i",
        "we",
        "our",
        "it",
        "this",
        "that",
        "please",
    ]
)


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP]


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


class HashEmbedding:
    """Deterministic lexical smoke-test encoder. NOT a semantic model."""

    name = "hash-lexical-256-v1"

    def encode(self, texts):
        result = []
        for text in texts:
            vec = [0.0] * 256
            for token in tokens(text):
                digest = hashlib.sha256(token.encode()).digest()
                vec[int.from_bytes(digest[:2], "big") % 256] += 1 if digest[2] % 2 else -1
            norm = math.sqrt(sum(x * x for x in vec)) or 1
            result.append([x / norm for x in vec])
        return result


class DenseEmbedding:
    def __init__(self, name="sentence-transformers/all-MiniLM-L6-v2", revision=None):
        from sentence_transformers import SentenceTransformer

        revision = revision or None
        self.name = name + "@" + (revision or "unpinned")
        self.model = SentenceTransformer(name, revision=revision, trust_remote_code=False)

    def encode(self, texts):
        return self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()


class LexicalReranker:
    name = "lexical-overlap-smoke-v1"

    def score(self, query, texts):
        q = Counter(tokens(query))
        return [sum((q & Counter(tokens(t))).values()) / max(1, len(q)) for t in texts]


class CrossEncoderReranker:
    def __init__(self, name="cross-encoder/ms-marco-MiniLM-L6-v2", revision=None):
        from sentence_transformers import CrossEncoder

        revision = revision or None
        self.name = name + "@" + (revision or "unpinned")
        self.model = CrossEncoder(name, revision=revision, trust_remote_code=False)

    def score(self, query, texts):
        return self.model.predict([(query, t) for t in texts], show_progress_bar=False).tolist()
