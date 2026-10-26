import json
import sqlite3

import pytest

from rag import connectors
from rag.connectors import (
    TextHTML,
    drive_text,
    fetch,
    notion_page,
    slack_thread,
    sqlite_table,
)


def test_website_denies_unapproved_or_private_targets(monkeypatch):
    with pytest.raises(ValueError):
        fetch("http://example.org", {"example.org"})
    with pytest.raises(ValueError):
        fetch("https://evil.example", {"example.org"})
    monkeypatch.setattr(connectors.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError, match="Non-public"):
        fetch("https://example.org", {"example.org"})


def test_dns_connection_is_pinned_and_redirect_denied(monkeypatch):
    monkeypatch.setattr(connectors.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    calls = []

    class Fake:
        def __init__(self, host, address):
            calls.append((host, address))

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return type("Response", (), {"status": 302})()

        def close(self):
            pass

    monkeypatch.setattr(connectors, "PinnedHTTPS", Fake)
    with pytest.raises(ValueError, match="302"):
        fetch("https://example.org/test", {"example.org"})
    assert calls == [("example.org", "93.184.216.34")]


def test_database_snapshot_read_only_and_identifier_validation(tmp_path):
    path = tmp_path / "source.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE products(id INTEGER PRIMARY KEY, name TEXT, description TEXT)")
    db.execute("INSERT INTO products VALUES(1,'Search','Knowledge search service')")
    db.commit()
    db.close()
    docs = sqlite_table(path, "products", "id", ["name", "description"], ["group:engineering"])
    assert docs[0].acl == ["group:engineering"]
    assert "Knowledge search" in docs[0].pages[0]
    with pytest.raises(ValueError):
        sqlite_table(path, "products; DROP TABLE products", "id", ["name"], [])
    assert path.is_file()


def test_slack_pagination_and_acl_preservation(monkeypatch):
    responses = iter(
        [
            {"ok": True, "messages": [{"user": "u1", "text": "Parent"}], "response_metadata": {"next_cursor": "next"}},
            {"ok": True, "messages": [{"user": "u2", "text": "Reply"}]},
        ]
    )
    monkeypatch.setattr(connectors, "fetch", lambda *a, **k: json.dumps(next(responses)).encode())
    doc = slack_thread("C123", "123.4", "not-real", ["group:private-channel"])
    assert "Parent" in doc.pages[0] and "Reply" in doc.pages[0]
    assert doc.acl == ["group:private-channel"]


def test_notion_nested_blocks_fail_instead_of_silent_partial_index(monkeypatch):
    payload = {"results": [{"type": "paragraph", "has_children": True}], "has_more": False}
    monkeypatch.setattr(connectors, "fetch", lambda *a, **k: json.dumps(payload).encode())
    with pytest.raises(ValueError, match="Nested"):
        notion_page("a" * 32, "not-real", [])


def test_drive_export_is_bound_to_fixed_host(monkeypatch):
    calls = []

    def mock_fetch(url, hosts, headers):
        calls.append((url, hosts))
        return b"Drive document text"

    monkeypatch.setattr(connectors, "fetch", mock_fetch)
    doc = drive_text("file_123", "not-real", [])
    assert doc.pages == ["Drive document text"] and doc.acl == []
    assert calls[0][1] == {"www.googleapis.com"}
    with pytest.raises(ValueError):
        drive_text("../../secret", "not-real", [])


def test_html_excludes_scripts():
    parser = TextHTML()
    parser.feed("<h1>Policy</h1><script>bad_secret()</script><p>Annual leave</p>")
    text = " ".join(parser.parts)
    assert "Policy" in text and "Annual leave" in text and "bad_secret" not in text


def test_pdf_scans_require_ocr(tmp_path):
    from pypdf import PdfWriter

    path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with path.open("wb") as stream:
        writer.write(stream)
    with pytest.raises(ValueError, match="OCR"):
        connectors.pdf(path, "scan", [])
