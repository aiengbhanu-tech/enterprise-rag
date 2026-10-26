import hashlib
import json
import math
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime

from .chunking import chunk_page
from .security import quarantine, redact


def stable(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Store:
    """Transactional single-node reference store. Connections are operation-local."""

    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS documents (
              id TEXT PRIMARY KEY, tenant TEXT NOT NULL, source TEXT NOT NULL,
              external_id TEXT NOT NULL, title TEXT NOT NULL, uri TEXT NOT NULL,
              acl TEXT NOT NULL, metadata TEXT NOT NULL, revision TEXT NOT NULL,
              content_hash TEXT NOT NULL, quarantined INTEGER NOT NULL, updated TEXT NOT NULL,
              UNIQUE(tenant,source,external_id));
            CREATE TABLE IF NOT EXISTS chunks (
              id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
              parent_id TEXT NOT NULL, page INTEGER NOT NULL, ordinal INTEGER NOT NULL,
              text TEXT NOT NULL, parent_text TEXT NOT NULL, vector TEXT NOT NULL, encoder TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS tenant_sources ON documents(tenant,source);
            CREATE INDEX IF NOT EXISTS chunk_documents ON chunks(document_id);
            CREATE TABLE IF NOT EXISTS index_artifacts (
              tenant TEXT, content_hash TEXT, pipeline TEXT, tree TEXT NOT NULL,
              PRIMARY KEY(tenant,content_hash,pipeline));
            CREATE TABLE IF NOT EXISTS checkpoints (
              tenant TEXT, source TEXT, cursor TEXT, updated TEXT, PRIMARY KEY(tenant,source));
            CREATE TABLE IF NOT EXISTS memory (
              tenant TEXT, user TEXT, session TEXT, turns TEXT, PRIMARY KEY(tenant,user,session));
            CREATE TABLE IF NOT EXISTS audit (
              id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, tenant TEXT NOT NULL,
              actor TEXT NOT NULL, event TEXT NOT NULL, details TEXT NOT NULL);
            """)

        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def audit(self, db, tenant, actor, event, details):
        db.execute(
            "INSERT INTO audit(timestamp,tenant,actor,event,details) VALUES(?,?,?,?,?)",
            (datetime.now(UTC).isoformat(), tenant, actor, event, json.dumps(details)),
        )

    def sync(
        self, tenant, source, documents, embedder, *, strategy="semantic", cursor="", deleted=(), actor="connector"
    ):
        """Atomic delta: replacements, explicit tombstones and checkpoint commit together.

        Same bytes with different ACLs stay separate identities. Dedup never widens ACLs.
        No missing-item deletion on partial pages; full exports must supply tombstones.
        """
        if not tenant or not source:
            raise ValueError("tenant and source required")
        documents = list(documents)
        ids = [d.external_id for d in documents]
        if len(ids) != len(set(ids)) or set(ids).intersection(deleted):
            raise ValueError("Duplicate or conflicting external ids in delta")
        stats = {"indexed": 0, "unchanged": 0, "deleted": 0, "quarantined": 0}
        with self.lock, self.connect() as db:
            for doc in documents:
                if not doc.external_id or not doc.title or not doc.pages:
                    raise ValueError("Document requires id, title and pages")
                if any(
                    not isinstance(a, str) or not (a == "tenant:all" or a.startswith(("user:", "group:")))
                    for a in doc.acl
                ):
                    raise ValueError("Invalid ACL")
                pages = [redact(p) for p in doc.pages]
                title, uri = redact(doc.title), redact(doc.uri)
                metadata = json.loads(redact(json.dumps(doc.metadata)))
                doc_id = stable([tenant, source, doc.external_id])
                content_hash = stable(pages)
                blocked = any(quarantine(p) for p in pages)
                rev = stable([pages, title, uri, sorted(doc.acl), metadata, strategy, embedder.name, "chunk-v1"])
                old = db.execute("SELECT revision FROM documents WHERE id=?", (doc_id,)).fetchone()
                if old and old[0] == rev:
                    stats["unchanged"] += 1
                    continue
                db.execute("DELETE FROM chunks WHERE document_id=?", (doc_id,))
                db.execute(
                    """INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(id) DO UPDATE SET title=excluded.title, uri=excluded.uri,
                  acl=excluded.acl, metadata=excluded.metadata, revision=excluded.revision,
                  content_hash=excluded.content_hash, quarantined=excluded.quarantined, updated=excluded.updated""",
                    (
                        doc_id,
                        tenant,
                        source,
                        doc.external_id,
                        title,
                        uri,
                        json.dumps(doc.acl),
                        json.dumps(metadata),
                        rev,
                        content_hash,
                        int(blocked),
                        datetime.now(UTC).isoformat(),
                    ),
                )
                if blocked:
                    stats["quarantined"] += 1
                    continue
                pipeline = stable([strategy, embedder.name, "chunk-v1"])
                artifact = db.execute(
                    "SELECT tree FROM index_artifacts WHERE tenant=? AND content_hash=? AND pipeline=?",
                    (tenant, content_hash, pipeline),
                ).fetchone()
                if artifact:
                    tree = json.loads(artifact[0])
                else:
                    tree = []
                    for page, text in enumerate(pages, 1):
                        for pi, (parent, children) in enumerate(chunk_page(text, embedder, strategy)):
                            vectors = embedder.encode(children)
                            if len(vectors) != len(children) or any(
                                not vector or any(not math.isfinite(x) for x in vector) for vector in vectors
                            ):
                                raise ValueError("Invalid embedding provider output")
                            tree.append([page, pi, parent, children, vectors])
                    db.execute(
                        "INSERT INTO index_artifacts VALUES(?,?,?,?)",
                        (tenant, content_hash, pipeline, json.dumps(tree)),
                    )
                for page, pi, parent, children, vectors in tree:
                    parent_id = stable([doc_id, rev, page, pi])
                    for ci, (child, vector) in enumerate(zip(children, vectors, strict=True)):
                        cid = stable([parent_id, ci])
                        db.execute(
                            "INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?,?)",
                            (cid, doc_id, parent_id, page, ci, child, parent, json.dumps(vector), embedder.name),
                        )
                stats["indexed"] += 1
            for external_id in deleted:
                stats["deleted"] += db.execute(
                    "DELETE FROM documents WHERE tenant=? AND source=? AND external_id=?", (tenant, source, external_id)
                ).rowcount
            db.execute(
                "INSERT OR REPLACE INTO checkpoints VALUES(?,?,?,?)",
                (tenant, source, cursor, datetime.now(UTC).isoformat()),
            )
            db.execute(
                "DELETE FROM index_artifacts WHERE tenant=? AND content_hash NOT IN (SELECT content_hash FROM documents WHERE tenant=?)",
                (tenant, tenant),
            )
            self.audit(db, tenant, actor, "sync", {"source": source, **stats})
        return stats

    def rows(self, tenant):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    """SELECT c.*,d.tenant,d.source,d.external_id,d.title,d.uri,
                d.acl,d.metadata,d.content_hash,d.revision FROM chunks c JOIN documents d ON c.document_id=d.id
                WHERE d.tenant=? AND d.quarantined=0""",
                    (tenant,),
                )
            ]

    def history(self, principal, session):
        with self.connect() as db:
            row = db.execute(
                "SELECT turns FROM memory WHERE tenant=? AND user=? AND session=?",
                (principal.tenant, principal.user, session),
            ).fetchone()
            return json.loads(row[0]) if row else []

    def remember(self, principal, session, question):
        # Only redacted questions persist. Source-derived answers are never replayed.
        with self.lock, self.connect() as db:
            row = db.execute(
                "SELECT turns FROM memory WHERE tenant=? AND user=? AND session=?",
                (principal.tenant, principal.user, session),
            ).fetchone()
            turns = (json.loads(row[0]) if row else []) + [redact(question)]
            db.execute(
                "INSERT OR REPLACE INTO memory VALUES(?,?,?,?)",
                (principal.tenant, principal.user, session, json.dumps(turns[-6:])),
            )

    def forget(self, principal, session):
        with self.connect() as db:
            db.execute(
                "DELETE FROM memory WHERE tenant=? AND user=? AND session=?",
                (principal.tenant, principal.user, session),
            )
