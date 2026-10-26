READER = {"Authorization": "Bearer reader-test"}
ADMIN = {"Authorization": "Bearer admin-test"}
OTHER = {"Authorization": "Bearer other-test"}
PAYLOAD = {
    "source": "wiki",
    "documents": [
        {
            "external_id": "leave",
            "title": "Leave",
            "pages": ["Employees receive 24 annual leave days."],
            "acl": ["group:engineering"],
            "metadata": {"kind": "pdf"},
        }
    ],
}


def test_auth_admin_and_tenant_boundaries(client):
    api, _store = client
    assert api.get("/health/live").status_code == 200
    assert api.post("/v1/ask", json={"question": "annual leave"}).status_code == 401
    assert api.post("/v1/admin/sync", headers=READER, json=PAYLOAD).status_code == 403
    assert api.post("/v1/admin/sync", headers=ADMIN, json=PAYLOAD).status_code == 200
    answer = api.post("/v1/ask", headers=READER, json={"question": "How many annual leave days do employees receive?"})
    assert answer.status_code == 200 and answer.json()["citations"]
    assert answer.headers["Cache-Control"] == "no-store"
    assert answer.headers["X-Request-ID"]
    assert api.post("/v1/ask", headers=OTHER, json={"question": "annual leave"}).json()["abstained"]
    # Caller-supplied identity headers confer no access.
    assert (
        api.post(
            "/v1/ask", headers={"X-Tenant": "acme", "X-Groups": "engineering"}, json={"question": "annual leave"}
        ).status_code
        == 401
    )
    assert api.get("/v1/admin/metrics", headers=READER).status_code == 403
    assert api.get("/v1/admin/metrics", headers=ADMIN).status_code == 200
    assert api.delete("/v1/memory/default", headers=READER).status_code == 204


def test_api_validation_body_budget_and_rate_limit(client):
    api, _ = client
    assert api.post("/v1/ask", headers=READER, json={"question": "", "k": 100}).status_code == 422
    assert api.post("/v1/ask", headers=READER, content=b"a" * 2_000_001).status_code == 413
    responses = [api.post("/v1/ask", headers=READER, json={"question": "annual leave"}).status_code for _ in range(61)]
    assert 429 in responses


def test_delete_propagates_to_next_request(client):
    api, _ = client
    api.post("/v1/admin/sync", headers=ADMIN, json=PAYLOAD)
    assert api.post("/v1/search", headers=READER, json={"question": "annual leave"}).json()["hits"]
    result = api.post("/v1/admin/sync", headers=ADMIN, json={"source": "wiki", "deleted": ["leave"], "cursor": "2"})
    assert result.json()["deleted"] == 1
    assert not api.post("/v1/search", headers=READER, json={"question": "annual leave"}).json()["hits"]


def test_provider_failure_is_sanitized_and_has_request_id(client, monkeypatch):
    api, store = client

    def broken(*args):
        raise RuntimeError("credential=TOP-SECRET and private-source-text")

    monkeypatch.setattr(store, "rows", broken)
    response = api.post("/v1/ask", headers=READER, json={"question": "annual leave"})
    assert response.status_code == 500
    assert response.headers["X-Request-ID"]
    assert "TOP-SECRET" not in response.text and "private-source-text" not in response.text
