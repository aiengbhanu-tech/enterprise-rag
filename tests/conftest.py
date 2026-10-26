import hashlib
import json

import pytest

from rag.models import HashEmbedding, LexicalReranker
from rag.retrieval import Retriever
from rag.store import Store
from rag.types import Document, Principal


@pytest.fixture
def stack(tmp_path):
    store, embed = Store(tmp_path / "test.sqlite"), HashEmbedding()
    return store, embed, Retriever(store, embed, LexicalReranker())


@pytest.fixture
def alice():
    return Principal("acme", "alice", ("engineering",))


@pytest.fixture
def doc():
    return Document(
        "policy",
        "Leave policy",
        ["Employees receive 24 annual leave days. The direct manager approves leave requests."],
        ["group:engineering"],
        {"department": "hr"},
    )


@pytest.fixture
def client(stack):
    from fastapi.testclient import TestClient

    from rag.api import create_app

    store, embed, retriever = stack
    config = json.dumps(
        [
            {
                "sha256": hashlib.sha256(token.encode()).hexdigest(),
                "tenant": tenant,
                "user": user,
                "groups": groups,
                "admin": admin,
            }
            for token, tenant, user, groups, admin in [
                ("reader-test", "acme", "alice", ["engineering"], False),
                ("admin-test", "acme", "operator", [], True),
                ("other-test", "other", "alice", ["engineering"], False),
            ]
        ]
    )
    return TestClient(create_app(store, embed, retriever.reranker, config)), store
