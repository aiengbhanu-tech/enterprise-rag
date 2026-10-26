# Deployment readiness and scope

## Implemented and verified locally

The CPU-only smoke service is runnable with persistent transactional storage. Tests cover tenant/ACL filtering, no implicit admin read bypass, permission revocation, deletion, metadata filters, exact citation provenance, incremental no-op updates, rollback/checkpoint consistency, deduplication without ACL merging, PII pattern redaction, memory isolation, quarantine, API auth/limits, connector transport constraints and metric correctness.

## Implemented but not validated against production dependencies

The Sentence Transformers bi-encoder and cross-encoder adapters, Docker image/Compose runtime and narrow provider APIs need validation with pinned models, a container engine and test provider accounts. Live connector calls were not made. Model and container performance results are not part of the included report.

## Concrete limits

- Single-node SQLite canonical store, in-process BM25 and exhaustive dense scoring. A query refuses more than 50,000 *authorized and filtered* chunks, but row loading happens earlier and is not a memory-safety guarantee. Establish a smaller measured organization limit. This is not an ANN/distributed retrieval implementation.
- Opaque service credentials with server-defined tenants/groups, read once at startup. There is no employee login, OIDC/SCIM or automatic group refresh. Rotate/revoke credentials and refresh memberships by changing the secret and restarting. Integrate a verified organization identity layer before broad employee use.
- Source ACL ingestion is manual/worker-controlled; provider-wide discovery, continuous OAuth/ACL synchronization, change-data capture, retries/backoff and a background job queue are not implemented. Permission revocation takes effect on the next query after the sync commits; in-flight requests use their already-authorized snapshot.
- The database has no application-managed encryption at rest or retention scheduler. Use encrypted volumes and bounded retention, including backups. Redaction is limited to explicit regex patterns and can miss names, addresses, secrets and nonstandard identifiers. It can also over-redact numeric business identifiers.
- Prompt attack pattern matching can miss obfuscated instructions. The structural control is that answering only emits evidence quotes and has no executable tools or free-form synthesis. Quoted malicious or misleading content remains possible if not quarantined; this is not proof of universal injection resistance.
- The answerer is extractive and uses overlap-based abstention. It can omit facts, include irrelevant quotes and fail multi-hop/paraphrase questions. It does not resolve contradictions, rank source authority or provide generative synthesis.
- Conversation memory contains up to six redacted user questions per tenant/user/session, but has no automatic TTL. It is not a full chat transcript and never caches source answers. Concurrent updates to the same session are serialized within one process.
- Read-only adapters support text PDFs, a single HTML page, a single Drive document, top-level Notion blocks, one Slack thread, SQLite snapshots and normalized exports. This is not a full ingestion platform for all organizational systems.
- Metrics/rate limits/concurrency are process-local. The pilot uses one API process. Do not add replicas and assume global rate limits or globally consistent metrics. Audit records are local and not tamper-proof; forward to an external audit sink if needed.
- No UI for employee chat, background evaluation jobs, experiment registry service, independent human labels or LLM judge is included. The evaluation platform is a CLI runner, artifact reports and blind review import/export.

## Rollout criteria

Run learned-model and live-source integration tests; verify upstream ACL semantics; integrate organization identity and revocation; freeze source and model versions; measure retrieval quality and concurrency at the target corpus size; validate encrypted backup/restore; define retention and deletion policies; and review the bounded extractive answer behavior with intended users. The current deliverable is an internal pilot reference with transparent measured limitations, not a claim that these acceptance criteria have been met.
