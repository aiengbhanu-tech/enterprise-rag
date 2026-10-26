# Connector contract and examples

The CLI is a trusted ingestion boundary. Credentials are supplied in environment variables and never passed to the question API. For source permissions, empty ACLs deny all. `tenant:all` must only represent a document actually readable throughout that tenant.

## Normalized export

```json
{
  "cursor": "source-delta-token",
  "documents": [{
    "external_id": "stable-provider-id",
    "title": "Runbook",
    "pages": ["First page or logical segment", "Second page or segment"],
    "acl": ["group:engineering"],
    "metadata": {"kind": "drive", "department": "engineering"},
    "uri": "https://example.org/runbook"
  }],
  "deleted": ["removed-provider-id"]
}
```

`python -m rag.cli sync --db local.sqlite --tenant acme --source engineering-drive --profile smoke --export export.json`

A delta is committed with its checkpoint in one transaction. Retries with the same sanitized content, metadata, ACL and pipeline fingerprint do no indexing work. A cursor is retained for an external scheduler to resume; the sample live adapters do not implement a complete provider-wide delta crawler. A full replacement export must explicitly provide tombstones for removed items. Source disappearance cannot safely be inferred from one incomplete page.

## PDFs and websites

```bash
python -m rag.cli sync --db local.sqlite --tenant acme --source policies --profile smoke --pdf handbook.pdf --acl group:employees
python -m rag.cli sync --db local.sqlite --tenant acme --source handbook-web --profile smoke --website https://example.org/handbook --host example.org --acl group:employees
```

PDFs preserve page numbers. Scanned PDFs without text fail and require OCR upstream. The website adapter fetches one HTML page, skips script/style content, permits only configured HTTPS hosts, checks all DNS addresses, pins the selected public address, and rejects redirects. JavaScript rendering, crawl discovery, robots policy, retries and authenticated portals are not included. Run file parsers in an isolated ingestion job for untrusted organizational uploads.

## Drive, Notion and Slack

```bash
# Set DRIVE_TOKEN, NOTION_TOKEN or SLACK_TOKEN via your secrets manager first.
python -m rag.cli sync --db local.sqlite --tenant acme --source drive --profile smoke --drive FILE_ID --acl group:engineering
python -m rag.cli sync --db local.sqlite --tenant acme --source notion --profile smoke --notion PAGE_ID --acl group:engineering
python -m rag.cli sync --db local.sqlite --tenant acme --source slack --profile smoke --slack-channel CHANNEL_ID --slack-thread THREAD_TIMESTAMP --acl group:channel-members
```

These are narrow adapters, not complete managed connectors:

- Drive exports one Google Docs file as text. Other formats and permission enumeration need a provider worker.
- Notion fetches paginated top-level rich-text blocks. Nested blocks fail explicitly to avoid silently indexing incomplete content. Use a normalized export for richer pages.
- Slack fetches a paginated thread. It does not enumerate a workspace, ingest files, monitor edits/deletions or manage rate-limit retries.
- ACL/membership synchronization, OAuth refresh, webhooks and scheduling remain the responsibility of an upstream worker. Never assume that an integration token's ability to read a file makes that file public to users.

Provider adapter behavior was verified against mocked payloads, not live authenticated accounts. No accounts were accessed during this build.

Official endpoint references:

- https://developers.google.com/workspace/drive/api/reference/rest/v3/files/export
- https://developers.notion.com/reference/get-block-children
- https://docs.slack.dev/reference/methods/conversations.replies/

## Databases

```bash
python -m rag.cli sync --db local.sqlite --tenant acme --source product-catalog --profile smoke --sqlite source.sqlite --table products --id-column id --text-column name --text-column description --acl group:engineering
```

The adapter opens an existing SQLite database read-only, enables query-only mode, validates identifiers and reads at most 10,000 rows. It never executes user-submitted SQL. A PostgreSQL/MySQL/warehouse integration should produce the same normalized delta contract using a read-only service identity, reviewed queries and stable row ids. Database row-level permissions must be converted into document ACLs upstream. CDC and arbitrary external database drivers are not implemented.
