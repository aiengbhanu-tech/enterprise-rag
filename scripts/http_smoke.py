"""Actual HTTP/Uvicorn smoke check using temporary credentials and database."""

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        token = "temporary-integration-test-token"
        config = [
            {
                "sha256": hashlib.sha256(token.encode()).hexdigest(),
                "tenant": "test",
                "user": "tester",
                "groups": ["employees"],
                "admin": True,
            }
        ]
        (root / "tokens.json").write_text(json.dumps(config))
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        env = {
            **os.environ,
            "RAG_PROFILE": "smoke",
            "RAG_DB": str(root / "rag.sqlite"),
            "RAG_TOKENS_FILE": str(root / "tokens.json"),
        }
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "rag.api:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--no-access-log",
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base = f"http://127.0.0.1:{port}"

        def request(path, payload=None):
            req = urllib.request.Request(
                base + path,
                data=json.dumps(payload).encode() if payload is not None else None,
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                return json.load(response)

        try:
            for _ in range(50):
                try:
                    if request("/health/ready")["status"] == "ready":
                        break
                except (OSError, urllib.error.URLError):
                    time.sleep(0.1)
            else:
                raise RuntimeError("Service failed to become ready")
            delta = {
                "source": "test",
                "documents": [
                    {
                        "external_id": "leave",
                        "title": "Leave",
                        "pages": ["Employees receive 24 annual leave days."],
                        "acl": ["group:employees"],
                    }
                ],
            }
            assert request("/v1/admin/sync", delta)["indexed"] == 1
            answer = request("/v1/ask", {"question": "How many annual leave days do employees receive?"})
            assert "24 annual" in answer["answer"] and answer["citations"][0]["external_id"] == "leave"
            assert request("/v1/admin/sync", {"source": "test", "deleted": ["leave"]})["deleted"] == 1
            assert request("/v1/ask", {"question": "annual leave days"})["abstained"]
            print("HTTP smoke passed: startup, auth, indexing, cited answer, deletion and abstention")
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
