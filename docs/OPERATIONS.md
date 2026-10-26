# Operating the reference service

Use one process against a local persistent SQLite volume. The service never accepts caller-supplied identity headers as authorization. Issue at least 32 random bytes per bearer credential. Credential config records contain `sha256`, `tenant`, `user`, `groups`, and `admin`; manage them through a secret store. Separate ingestion operators from readers and give each connector only the upstream scopes it needs.

## Data lifecycle

An ingestion transaction commits document identities, redacted content artifacts, chunk vectors, ACLs, metadata and a source cursor together. A failed embedding call rolls everything back. Artifacts are tenant-scoped and content-addressed; titles, metadata and ACLs stay document-specific. Body reuse saves embedding work without creating a union ACL. Tombstones delete a source identity and cascade its chunks; unused body artifacts are pruned. Memory stores questions only, so source removal cannot leave a cached source answer behind.

Database tombstones are logical deletion from the active service, not guaranteed physical secure erasure: SQLite WAL pages, storage snapshots and backups can retain older bytes. Enforce retention and disposal in the storage layer. `DELETE /v1/memory/{session}` deletes that user's current session record. There is no built-in automatic expiration job.

## Backup and recovery

Use SQLite's online backup API rather than copying only the live `.sqlite` file while WAL is active:

```python
import sqlite3
with sqlite3.connect('/data/rag.sqlite') as source, sqlite3.connect('/backup/rag-backup.sqlite') as target:
    source.backup(target)
```

Protect the backup with the same access and encryption controls as source documents. In a restore drill, stop the service, restore the database, verify `PRAGMA integrity_check`, restart using the same encoder fingerprint, and test authorized/unauthorized questions plus a known tombstone. Recovery and backup scheduling must be supplied by the operator.

## Model updates

Pin embedding and reranker repository commit hashes. Build a separate index with the new encoder, run the golden suite and ACL cases, then switch traffic after validation. Do not mix embedding models in a serving index. Fingerprint mismatch blocks retrieval until reindexing completes. A reranker change does not require reembedding but does require evaluation. Network access should be disabled for the query process after model weights are cached and reviewed.

## Instrumentation

Health probes verify process/database availability. `/v1/admin/metrics` returns recent request durations and status counts; it does not implement a durable monitoring backend. A request id is returned for completed requests. Audit events include tenant, actor, action and numeric/configuration metadata, excluding question text. No full source bodies or provider errors should be logged. Run the supplied Uvicorn command with `--no-access-log` to avoid accidental sensitive URI logging at the edge.

A reverse proxy should enforce TLS, upstream identity if used, connection/body timeouts and global rate/concurrency limits. Test slow requests, model latency and resource exhaustion under realistic load before changing the single-process 4-query concurrency limit. Do not expose the localhost port directly to the Internet.

Container pattern reference: https://fastapi.tiangolo.com/deployment/docker/
