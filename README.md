# Enterprise RAG Lab

A runnable permission-aware retrieval service and evaluation platform. This builds beyond a multi-PDF chatbot: the core deliverable is an experimentally testable retrieval pipeline, reproducible results, and explicit security boundaries.

**Status:** deployable single-node reference implementation for a bounded internal pilot. It is not a completed enterprise SaaS product. The included measurements use deterministic lexical smoke models on synthetic data; pretrained semantic-model, live-provider, container and production-scale validation remain outstanding. Read `docs/READINESS.md` before an organizational rollout.

## What is implemented

- Read-only adapters for text PDFs, allowlisted HTTPS websites, Drive text exports, top-level Notion blocks, Slack threads, normalized document exports, and SQLite table snapshots.
- BM25 + normalized dense embedding search, reciprocal rank fusion, optional cross-encoder reranking, bounded parent expansion and revisioned citations.
- Sentence-similarity chunk boundaries, fixed chunk baseline, multi-query acronym expansion, follow-up query rewriting and exact metadata filters.
- Server-side identities, tenant isolation, deny-by-default document ACLs and permission filtering **before every scorer**. Being an ingestion administrator does not bypass document ACLs.
- Atomic incremental indexing, checkpoint persistence, explicit tombstones and content-addressed embedding reuse without merging document identities or permissions.
- Redaction of email, phone-like identifiers and SSNs; quarantine for known instruction-attack patterns; extractive answering with no tool execution.
- User/tenant/session-scoped redacted question memory, deletion endpoint, request budgets, rate limits, health probes, sanitized audit events and operational metrics.
- Golden questions, graded qrels, all eight factorial experiments, per-query outputs, bootstrap confidence intervals, paired contrasts, a browser report, blind human-review workflow and CI regression checks.

Learned encoding/reranking follows the bi-encoder → cross-encoder design documented by Sentence Transformers: https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html

## Quick start: local smoke profile

Requires Python 3.11+. Run from the extracted `enterprise-rag` directory. The smoke profile needs no model downloads or service credentials.

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell, use this activation command instead:
# .venv\Scripts\Activate.ps1
python -m pip install -c requirements-tested.txt '.[dev]'
python -m pytest -q
python -m eval.run --profile smoke
python -m eval.gate eval/results/smoke/results.json eval/budgets.json
```

Open `eval/results/smoke/index.html` in a browser. The checked-in `REPORT.md` and `results.json` include the measurements from this build. There are 39 synthetic source documents and 35 golden questions: six dev, 29 test. Retrieval averages use the 26 answerable test questions; three additional test questions exercise denial/abstention behavior. The source-kind tags are fixture metadata, not evidence of live integration testing.

### Start the API

```bash
python -c "from pathlib import Path; Path('secrets').mkdir(exist_ok=True)"
python -m rag.cli token --tenant acme --user pilot-admin --admin --out secrets/tokens.json
python -m rag.cli sync --db local.sqlite --tenant acme --source fixture --profile smoke --export data/corpus.json
```

Keep the bearer token printed once by `token`. The credential file contains its SHA-256 hash, not its cleartext. `token` refuses to overwrite an existing config. Ingestion requires an administrator; document reading still requires an ACL match.

Linux/macOS:

```bash
export RAG_PROFILE=smoke
export RAG_DB=local.sqlite
export RAG_TOKENS_FILE=secrets/tokens.json
python -m uvicorn rag.api:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

Windows PowerShell:

```powershell
$env:RAG_PROFILE="smoke"
$env:RAG_DB="local.sqlite"
$env:RAG_TOKENS_FILE="secrets/tokens.json"
python -m uvicorn rag.api:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

Swagger: http://127.0.0.1:8000/docs. Supply `Authorization: Bearer <token>` in the endpoint header field. Example `POST /v1/ask` body:

```json
{
  "question": "How much PTO do we get each year?",
  "session": "demo-session",
  "mode": "hybrid",
  "rerank": true,
  "multi_query": true,
  "k": 5,
  "filters": {"department": "operations"}
}
```

Responses contain exact evidence quotes with document id, source, URI, logical page/segment, parent id and content revision. This answerer does not pretend to produce independently verified free-form synthesis. Search is also available at `POST /v1/search`.

### Learned semantic models

```bash
python -m pip install '.[models]'
python -m eval.run --profile learned --embed-revision EMBEDDING_COMMIT_SHA --rerank-revision RERANKER_COMMIT_SHA
```

The defaults are `sentence-transformers/all-MiniLM-L6-v2` and `cross-encoder/ms-marco-MiniLM-L6-v2`. Supply model repository commit hashes for reproducibility. There is **no silent fallback** if downloads, dependencies or inference fail. Learned evaluation requires both revision arguments. Set `RAG_EMBED_REVISION` and `RAG_RERANK_REVISION` to the same commits when indexing/serving. Changing an encoder fingerprint requires reindexing the corpus before queries can proceed.

For serving, set `RAG_PROFILE=learned` and rebuild the index with `--profile learned`. Model loading/inference has not been exercised in this environment. Pin model commits and resolved dependencies in the target environment before using its benchmark results.

## Source ingestion

Detailed examples and the export contract are in `docs/CONNECTORS.md`. The ingestion CLI has network/database credentials; the question service has no network tools and receives no database credentials.

A minimal admin delta request to `POST /v1/admin/sync`:

```json
{
  "source": "hr-notion",
  "cursor": "provider-watermark-123",
  "strategy": "semantic",
  "documents": [{
    "external_id": "leave-policy",
    "title": "Leave policy",
    "pages": ["Employees receive 24 days of annual leave."],
    "acl": ["group:employees"],
    "metadata": {"department": "hr", "kind": "notion"},
    "uri": "https://example.org/hr/leave"
  }],
  "deleted": []
}
```

Clients cannot select their tenant: it comes from the authenticated credential. ACL values are `user:alice`, `group:employees` and `tenant:all`; an empty ACL denies everyone. The administrator/connector must derive ACLs from an authoritative source. Missing items on a partial source page are never inferred to be deletions.

## Evaluation and publishing

```bash
# Tune only on the development split:
python -m eval.run --profile smoke --split dev --out eval/results/dev
# Evaluate frozen configurations on test:
python -m eval.run --profile smoke --split test
# Export blinded answer-review tasks:
python -m eval.review export eval/results/smoke/results.json answer-reviews.json
# After reviewers fill every score and their identity:
python -m eval.review import eval/results/smoke/results.json human-results.json --annotations answer-reviews.json
```

`docs/EVALUATION.md` defines metrics, annotation rubrics, qrel policy, denominator handling, failure analysis and a responsible publication protocol. The generated report contains all configurations, including regressions. `docs/RESULTS.md` discusses the observed weaknesses. CI uploads the report as a build artifact; no public deployment or GitHub publication has been performed.

## Container deployment

`Dockerfile` and `compose.yaml` include a non-root runtime, localhost binding, persistent data/models, read-only root, dropped capabilities, health checks and resource limits. Container execution was not available during this build.

After creating `secrets/tokens.json`:

```bash
# Default image includes learned-model dependencies:
docker compose up --build -d
# Populate its persistent index via authenticated /v1/admin/sync or a CLI job:
docker compose exec api python -m rag.cli sync --db /data/rag.sqlite --tenant acme --source fixture --profile learned --export /tmp/corpus.json
```

Copy a corpus export into `/tmp/corpus.json` first (`docker compose cp data/corpus.json api:/tmp/corpus.json`), or use `/v1/admin/sync`. For a model-free container trial set `RAG_EXTRAS=dev` and `RAG_PROFILE=smoke` in your shell before building, and pass `--profile smoke` to the ingestion command. Do not mix profiles in one active index.

The default learned startup downloads model weights into the named `/models` volume. A controlled deployment should pre-cache reviewed pinned weights, set `HF_HUB_OFFLINE=1`, restrict network egress and put the localhost listener behind the organization's authenticated TLS gateway. See `docs/OPERATIONS.md` for backups and concrete deployment boundaries.

## Repository map

| Path | Responsibility |
|---|---|
| `rag/store.py` | Atomic revisions, ACL records, artifacts, checkpoints, audit and memory |
| `rag/chunking.py` | Semantic/fixed child chunks and page-local parent groups |
| `rag/retrieval.py` | ACL/filter → multi-query → BM25/dense → RRF → rerank → parent context |
| `rag/models.py` | Learned models and explicitly lexical smoke substitutes |
| `rag/answer.py` | Citation-bearing extractive answers and abstention |
| `rag/connectors.py` | Read-only source adapters and pinned HTTPS transport |
| `rag/api.py`, `rag/cli.py` | Serving and controlled ingestion |
| `data/` | Synthetic corpus and golden annotations |
| `eval/` | Metrics, factorial runner, review workflow, budgets and published artifacts |
| `tests/` | Retrieval, ACL, indexing, privacy, API, connector and metric verification |
