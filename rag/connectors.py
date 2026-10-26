"""Read-only ingestion adapters. External credentials are CLI-only, never question tools."""

import http.client
import json
import re
import socket
import sqlite3
import ssl
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from .security import public_address
from .types import Document


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, hostname, address, port=443):
        super().__init__(hostname, port=port, timeout=15, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, self.port), timeout=self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def fetch(url, allowed_hosts, headers=None, max_bytes=5_000_000):
    """HTTPS, explicit host allowlist, public DNS, pinned address, no redirects.

    Pinning prevents the check/connect DNS-rebinding gap. Use an egress firewall too.
    """
    p = urlsplit(url)
    if p.scheme != "https" or p.hostname not in allowed_hosts or p.username or p.password or p.port not in (None, 443):
        raise ValueError("URL denied by egress policy")
    addresses = {r[4][0] for r in socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)}
    if not addresses or not all(public_address(a) for a in addresses):
        raise ValueError("Non-public destination denied")
    conn = PinnedHTTPS(p.hostname, min(addresses))
    try:
        conn.request("GET", (p.path or "/") + ("?" + p.query if p.query else ""), headers=headers or {})
        response = conn.getresponse()
        if response.status != 200:
            # Do not include secret-bearing URLs or response bodies in logs.
            raise ValueError(f"Connector HTTP status {response.status}")
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("Response too large")
        return data
    finally:
        conn.close()


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.skip = max(0, self.skip - 1)
        if not self.skip:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def website(url, acl, allowed_hosts):
    parser = TextHTML()
    parser.feed(fetch(url, allowed_hosts).decode("utf-8", errors="replace"))
    return Document(url, url, [" ".join(parser.parts)], acl, {"kind": "website"}, url)


def pdf(path, external_id, acl):
    from pypdf import PdfReader

    reader = PdfReader(path)
    if len(reader.pages) > 1000:
        raise ValueError("PDF page budget exceeded")
    pages = [page.extract_text() or "" for page in reader.pages]
    if not any(t.strip() for t in pages):
        raise ValueError("No extractable text: OCR required")
    return Document(external_id, Path(path).name, pages, acl, {"kind": "pdf"}, f"pdf:{external_id}")


def export_json(path):
    """Normalized export contract supports Notion/Drive docs and Slack threads.

    Connector workers, not end users, must set ACLs from the upstream provider.
    """
    payload = json.loads(Path(path).read_text())
    return [Document(**row) for row in payload["documents"]], payload.get("cursor", ""), payload.get("deleted", [])


def sqlite_table(path, table, id_column, text_columns, acl):
    if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", x) for x in [table, id_column, *text_columns]):
        raise ValueError("Invalid database identifier")
    if not text_columns or not Path(path).is_file():
        raise ValueError("Existing database and text columns required")
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    try:
        db.execute("PRAGMA query_only=ON")
        rows = db.execute(
            f'SELECT "{id_column}",' + ",".join(f'"{c}"' for c in text_columns) + f' FROM "{table}" LIMIT 10001'
        ).fetchall()
        if len(rows) > 10000:
            raise ValueError("Database snapshot row budget exceeded")
        return [
            Document(
                str(r[0]),
                f"{table}/{r[0]}",
                ["\n".join(f"{k}: {v}" for k, v in zip(text_columns, r[1:], strict=True))],
                acl,
                {"kind": "database", "table": table},
                f"db:{table}/{r[0]}",
            )
            for r in rows
        ]
    finally:
        db.close()


def drive_text(file_id, token, acl):
    """Google Docs text export. ACL input must come from a verified permissions sync."""
    if not re.fullmatch(r"[\w-]+", file_id):
        raise ValueError("Invalid Drive file id")
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}/export?mimeType=text%2Fplain"
    data = fetch(url, {"www.googleapis.com"}, {"Authorization": f"Bearer {token}"})
    return Document(
        file_id,
        f"Drive/{file_id}",
        [data.decode()],
        acl,
        {"kind": "drive"},
        f"https://docs.google.com/document/d/{file_id}",
    )


def notion_page(page_id, token, acl):
    """Paginated top-level paragraph export; nested blocks explicitly fail closed."""
    if not re.fullmatch(r"[a-fA-F0-9-]{32,36}", page_id):
        raise ValueError("Invalid Notion page id")
    blocks, cursor = [], ""
    for _ in range(100):
        url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"
        if cursor:
            url += "&start_cursor=" + cursor
        payload = json.loads(
            fetch(url, {"api.notion.com"}, {"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28"})
        )
        for block in payload["results"]:
            if block.get("has_children"):
                raise ValueError("Nested Notion blocks require recursive connector; use normalized export")
            value = block.get(block["type"], {})
            if "rich_text" in value:
                blocks.append("".join(t.get("plain_text", "") for t in value["rich_text"]))
        if not payload.get("has_more"):
            return Document(
                page_id,
                f"Notion/{page_id}",
                ["\n".join(blocks)],
                acl,
                {"kind": "notion"},
                f"https://notion.so/{page_id}",
            )
        cursor = payload["next_cursor"]
    raise ValueError("Notion pagination limit exceeded")


def slack_thread(channel, thread_ts, token, acl):
    """Read one whole thread. Channel ACL must be provided by verified membership sync."""
    messages, cursor = [], ""
    for _ in range(100):
        query = urlencode({"channel": channel, "ts": thread_ts, "limit": 100, "cursor": cursor})
        payload = json.loads(
            fetch(
                "https://slack.com/api/conversations.replies?" + query,
                {"slack.com"},
                {"Authorization": f"Bearer {token}"},
            )
        )
        if not payload.get("ok"):
            raise ValueError("Slack rejected request")
        messages.extend(f"{m.get('user', 'unknown')}: {m.get('text', '')}" for m in payload["messages"])
        cursor = payload.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            return Document(
                channel + "/" + thread_ts,
                f"Slack/{channel}/{thread_ts}",
                ["\n".join(messages)],
                acl,
                {"kind": "slack"},
                f"slack:{channel}/{thread_ts}",
            )
    raise ValueError("Slack pagination limit exceeded")
