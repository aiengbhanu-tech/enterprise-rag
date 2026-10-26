import json
import logging
import os
import threading
import time
import uuid
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .answer import Answerer
from .models import CrossEncoderReranker, DenseEmbedding, HashEmbedding, LexicalReranker
from .retrieval import RetrievalConfig, Retriever
from .security import authenticate
from .store import Store
from .types import Document


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    session: str = Field(default="default", min_length=1, max_length=128)
    filters: dict[str, str | int | bool] = Field(default_factory=dict, max_length=20)
    k: int = Field(default=5, ge=1, le=10)
    mode: Literal["vector", "bm25", "hybrid"] = "hybrid"
    rerank: bool = True
    multi_query: bool = True


class IngestDocument(BaseModel):
    external_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=500)
    pages: list[str] = Field(min_length=1, max_length=1000)
    acl: list[str] = Field(max_length=1000)
    metadata: dict = Field(default_factory=dict, max_length=30)
    uri: str = Field(default="", max_length=2000)


class Sync(BaseModel):
    source: str = Field(min_length=1, max_length=128)
    documents: list[IngestDocument] = Field(default_factory=list, max_length=100)
    deleted: list[str] = Field(default_factory=list, max_length=1000)
    cursor: str = Field(default="", max_length=2000)
    strategy: Literal["fixed", "semantic"] = "semantic"


class BodyLimit:
    def __init__(self, app, limit=2_000_000):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        messages, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.limit:
                return await JSONResponse({"detail": "Request exceeds byte budget"}, status_code=413)(
                    scope, receive, send
                )
            messages.append(message)
            if not message.get("more_body", False):
                break

        async def replay():
            if messages:
                return messages.pop(0)
            return await receive()

        await self.app(scope, replay, send)


def create_app(store=None, embedder=None, reranker=None, token_config=None):
    config = token_config or Path(os.environ["RAG_TOKENS_FILE"]).read_text()
    if not json.loads(config):
        raise ValueError("At least one service credential is required")
    if embedder is None:
        smoke = os.getenv("RAG_PROFILE", "learned") == "smoke"
        embedder = HashEmbedding() if smoke else DenseEmbedding(revision=os.getenv("RAG_EMBED_REVISION"))
        reranker = LexicalReranker() if smoke else CrossEncoderReranker(revision=os.getenv("RAG_RERANK_REVISION"))
    if reranker is None:
        raise ValueError("Explicit reranker required")
    if store is None:
        db_path = Path(os.getenv("RAG_DB", "/data/rag.sqlite"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        store = Store(db_path)
    retriever = Retriever(store, embedder, reranker)
    answerer = Answerer(retriever)
    app = FastAPI(title="Enterprise RAG Lab", version="0.1.0")
    app.add_middleware(BodyLimit)
    counts, durations = Counter(), deque(maxlen=1000)
    rates, rate_lock = defaultdict(deque), threading.Lock()
    slots = threading.BoundedSemaphore(4)

    @app.middleware("http")
    async def observe(request: Request, call_next):
        start, rid = time.monotonic(), uuid.uuid4().hex
        try:
            response = await call_next(request)
        except Exception as exc:
            # Provider exception strings can contain credentials or source text.
            logging.getLogger("rag").error("request_failed id=%s type=%s", rid, type(exc).__name__)
            response = JSONResponse(
                status_code=500, content={"detail": "Internal error; contact operator with request ID"}
            )
        counts[str(response.status_code)] += 1
        durations.append(time.monotonic() - start)
        response.headers["X-Request-ID"] = rid
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def identity(authorization: str = Header(default="")):
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "Bearer credential required")
        try:
            p = authenticate(authorization[7:], config)
        except PermissionError:
            raise HTTPException(401, "Invalid credential") from None
        with rate_lock:
            queue = rates[(p.tenant, p.user)]
            now = time.monotonic()
            while queue and queue[0] < now - 60:
                queue.popleft()
            if len(queue) >= 60:
                raise HTTPException(429, "Rate limit exceeded")
            queue.append(now)
        return p

    def admin(p=Depends(identity)):
        if not p.admin:
            raise HTTPException(403, "Ingestion administrator required")
        return p

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        with store.connect() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ready", "encoder": embedder.name, "reranker": reranker.name}

    def execute(body, p, answer):
        if not slots.acquire(blocking=False):
            raise HTTPException(503, "Retrieval capacity reached")
        try:
            cfg = RetrievalConfig(body.mode, body.rerank, body.multi_query, body.k)
            if answer:
                result = answerer.ask(p, body.question, body.session, cfg, body.filters)
            else:
                from .security import redact

                result = retriever.search(p, redact(body.question), cfg, body.filters)
            with store.connect() as db:
                store.audit(db, p.tenant, p.user, "ask" if answer else "search", {"mode": body.mode, "k": body.k})
            return result
        finally:
            slots.release()

    @app.post("/v1/ask")
    def ask(body: Ask, p=Depends(identity)):
        return execute(body, p, True)

    @app.post("/v1/search")
    def search(body: Ask, p=Depends(identity)):
        return execute(body, p, False)

    @app.delete("/v1/memory/{session}", status_code=204)
    def forget(session: str, p=Depends(identity)):
        store.forget(p, session)

    @app.post("/v1/admin/sync")
    def sync(body: Sync, p=Depends(admin)):
        try:
            return store.sync(
                p.tenant,
                body.source,
                [Document(**d.model_dump()) for d in body.documents],
                embedder,
                strategy=body.strategy,
                cursor=body.cursor,
                deleted=body.deleted,
                actor=p.user,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.get("/v1/admin/metrics")
    def metrics(p=Depends(admin)):
        # Operational aggregate only; document/query content never included.
        return {
            "requests_by_status": dict(counts),
            "latency_seconds_recent": list(durations),
            "note": "Single-process counters; scrape externally for durable metrics",
        }

    return app
