"""Web backend: the same two-phase flow, over HTTP.

Phase 1 endpoints get a fake provider injected through FastAPI's dependency
overrides and phase 2 builds none at all, so nothing here makes a network
request.  What these tests really guard is that the API adds no behaviour of its
own: the review guard still stops a blind merge (as ``409``), and the provider
key never appears in a response.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.llm import FakeEmbeddingClient, FakeLLMClient
from web.backend.main import create_app
from web.backend.routes import SessionStore, get_embedding_client, get_llm_client


SCHEMA_YAML = """target_columns:
  - name: product_name
    type: string
    required: true
  - name: unit_price
    type: decimal
    required: true
  - name: stock_quantity
    type: integer
    required: false
output:
  format: csv
  add_provenance: true
"""

SALES_TR = (
    "urun;fiyat;stok\n"
    "Coca Cola 330ml;12,50;10\n"
    "Coca-Cola 33cl;12,50;10\n"
    "Fanta 330ml;10,00;7\n"
)

EXPORT_EN = "product,price,stock\nPencil,8.90,3\n"

#: One vector per comparison key; the two Cola spellings normalise to the same
#: key, so they score 1.0 and merge without an LLM.
VECTORS = {
    "coca cola 330ml": [1.0, 0.0],
    "fanta 330ml": [0.0, 1.0],
    "pencil": [math.sqrt(1.0 - 0.2**2), 0.2],
}


def _mapping_response(product: str, price: str, stock: str, price_confidence: float) -> str:
    return json.dumps(
        {
            "matches": [
                {
                    "target_column": "product_name",
                    "column": product,
                    "confidence": 0.95,
                    "reason": "Adlar örtüşüyor.",
                },
                {
                    "target_column": "unit_price",
                    "column": price,
                    "confidence": price_confidence,
                    "reason": "Ondalık örnekler örtüşüyor.",
                },
                {
                    "target_column": "stock_quantity",
                    "column": stock,
                    "confidence": 0.9,
                    "reason": "İkisi de tamsayı.",
                },
            ]
        }
    )


@pytest.fixture
def llm() -> FakeLLMClient:
    """One review-worthy match on the second file keeps the guard testable."""

    return FakeLLMClient(
        responses=[
            _mapping_response("urun", "fiyat", "stok", 0.96),
            _mapping_response("product", "price", "stock", 0.54),
        ]
    )


@pytest.fixture
def embedder() -> FakeEmbeddingClient:
    return FakeEmbeddingClient(vectors=VECTORS, default=(0.0, 0.0, 1.0))


@pytest.fixture
def client(tmp_path: Path, llm: FakeLLMClient, embedder: FakeEmbeddingClient) -> TestClient:
    app = create_app(sessions=SessionStore(tmp_path / "sessions"))
    app.dependency_overrides[get_llm_client] = lambda: llm
    app.dependency_overrides[get_embedding_client] = lambda: embedder
    with TestClient(app) as test_client:
        yield test_client


def _upload(client: TestClient, *, schema: str = SCHEMA_YAML) -> str:
    response = client.post(
        "/upload",
        files=[
            ("files", ("sales_tr.csv", SALES_TR, "text/csv")),
            ("files", ("export_en.csv", EXPORT_EN, "text/csv")),
            ("target_schema", ("schema.yaml", schema, "application/x-yaml")),
        ],
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["inputs"] == ["sales_tr.csv", "export_en.csv"]
    return body["session_id"]


def _approve(client: TestClient, session_id: str) -> dict:
    """Accept every proposal: what a user does on the review screen."""

    plan = client.get(f"/mapping/{session_id}").json()
    for entry in plan["entries"]:
        for source in entry["sources"]:
            if source["status"] == "review":
                source["status"] = "auto"
                source["confidence"] = 1.0
    response = client.put(f"/mapping/{session_id}", json={"entries": plan["entries"]})
    assert response.status_code == 200, response.text
    return response.json()


def test_analyze_returns_a_plan_with_review_counts(client: TestClient, llm: FakeLLMClient):
    session_id = _upload(client)

    response = client.post(f"/analyze/{session_id}", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert [entry["target_column"] for entry in body["entries"]] == [
        "product_name",
        "unit_price",
        "stock_quantity",
    ]
    assert body["counts"] == {"auto": 5, "review": 1, "unmatched": 0}
    # One prompt per source file, and the plan is on disk for the CLI too.
    assert len(llm.calls or []) == 2
    assert client.get(f"/status/{session_id}").json()["has_mapping"] is True


def test_columns_lists_what_a_dropdown_may_offer(client: TestClient):
    """The review screen corrects a match by picking a column that exists."""

    session_id = _upload(client)

    body = client.get(f"/columns/{session_id}").json()

    files = {item["file"]: item for item in body["files"]}
    assert set(files) == {"sales_tr.csv", "export_en.csv"}
    assert [column["name"] for column in files["sales_tr.csv"]["columns"]] == [
        "urun",
        "fiyat",
        "stok",
    ]
    price = next(
        column for column in files["sales_tr.csv"]["columns"] if column["name"] == "fiyat"
    )
    assert price["inferred_type"] == "decimal"
    assert price["samples"], "dropdown shows sample values"
    assert [item["name"] for item in body["target_columns"]] == [
        "product_name",
        "unit_price",
        "stock_quantity",
    ]


def test_upload_rejects_a_malformed_target_schema(client: TestClient, tmp_path: Path):
    """The schema is validated on the way in, before any session work starts."""

    response = client.post(
        "/upload",
        files=[
            ("files", ("sales_tr.csv", SALES_TR, "text/csv")),
            (
                "target_schema",
                ("schema.yaml", "target_columns: []\noutput:\n  format: csv\n", "application/x-yaml"),
            ),
        ],
    )

    assert response.status_code == 400
    assert "target_columns" in response.json()["detail"]
    # The rejected workspace is cleaned up instead of lingering half-built.
    assert list((tmp_path / "sessions").glob("*")) == []


def test_upload_rejects_an_unsupported_input_type(client: TestClient):
    response = client.post(
        "/upload",
        files=[
            ("files", ("notes.txt", "hello", "text/plain")),
            ("target_schema", ("schema.yaml", SCHEMA_YAML, "application/x-yaml")),
        ],
    )

    assert response.status_code == 400
    assert "notes.txt" in response.json()["detail"]


def test_apply_is_refused_while_a_match_still_waits_for_review(client: TestClient, tmp_path: Path):
    session_id = _upload(client)
    client.post(f"/analyze/{session_id}", json={})

    response = client.post(f"/apply/{session_id}", json={})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "review_pending"
    assert detail["written"] is False
    assert [(item["target_column"], item["file"]) for item in detail["pending"]] == [
        ("unit_price", "export_en.csv")
    ]
    # Nothing was written, so there is nothing to download either.
    assert client.get(f"/download/{session_id}/merged").status_code == 404
    workspace = tmp_path / "sessions" / session_id
    assert not list(workspace.glob("merged.*"))


def test_mapping_can_be_edited_and_apply_then_merges(client: TestClient):
    session_id = _upload(client)
    client.post(f"/analyze/{session_id}", json={})

    approved = _approve(client, session_id)
    assert approved["counts"] == {"auto": 6, "review": 0, "unmatched": 0}
    assert client.get(f"/mapping/{session_id}").json()["counts"]["review"] == 0

    response = client.post(f"/apply/{session_id}", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["row_count"] == 4
    assert body["output_format"] == "csv"
    assert body["merged_file"] == "merged.csv"
    assert body["report_file"] == "merge_report.xlsx"
    assert client.get(f"/status/{session_id}").json()["artifacts"] == ["merged", "report"]


def test_apply_stops_when_the_validator_finds_a_serious_inconsistency(client: TestClient):
    session_id = _upload(client)
    client.post(f"/analyze/{session_id}", json={})
    plan = _approve(client, session_id)
    # A required target left unmapped: the data contradicts the approved plan.
    for entry in plan["entries"]:
        if entry["target_column"] == "unit_price":
            for source in entry["sources"]:
                source["status"] = "unmatched"
                source["column"] = None
                source["confidence"] = 0.0
    assert client.put(f"/mapping/{session_id}", json={"entries": plan["entries"]}).status_code == 200

    response = client.post(f"/apply/{session_id}", json={})

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "validation_failed"
    assert detail["written"] is False
    assert [item["check"] for item in detail["findings"]] == ["required"]
    assert client.get(f"/download/{session_id}/merged").status_code == 404


def test_download_serves_both_artifacts_of_a_finished_run(client: TestClient):
    session_id = _upload(client)
    client.post(f"/analyze/{session_id}", json={})
    _approve(client, session_id)
    client.post(f"/apply/{session_id}", json={"output_format": "csv"})

    merged = client.get(f"/download/{session_id}/merged")
    report = client.get(f"/download/{session_id}/report")

    assert merged.status_code == 200
    text = merged.content.decode("utf-8")
    assert "product_name" in text.splitlines()[0]
    assert "_source_file" in text.splitlines()[0]
    assert "Coca Cola 330ml" in text
    assert report.status_code == 200
    assert report.content[:2] == b"PK"  # xlsx is a zip container


def test_download_before_apply_says_so(client: TestClient):
    session_id = _upload(client)

    response = client.get(f"/download/{session_id}/merged")

    assert response.status_code == 404
    assert "/apply" in response.json()["detail"]


def test_clusters_are_proposed_reviewed_and_only_approved_ones_merge(client: TestClient):
    session_id = _upload(client)
    client.post(f"/analyze/{session_id}", json={})
    _approve(client, session_id)

    proposed = client.post(f"/cluster/{session_id}", json={"column": "product_name"})
    assert proposed.status_code == 200, proposed.text
    body = proposed.json()
    assert body["target_column"] == "product_name"
    cola = next(
        item
        for item in body["clusters"]
        if {member["value"] for member in item["members"]}
        == {"Coca Cola 330ml", "Coca-Cola 33cl"}
    )
    assert cola["status"] == "auto"

    stored = client.get(f"/clusters/{session_id}").json()
    assert stored["clusters"] == body["clusters"]

    # Reject the cluster: apply must then leave both spellings alone.
    rejected = [dict(item, status="rejected") if item == cola else item for item in body["clusters"]]
    assert client.put(f"/clusters/{session_id}", json={"clusters": rejected}).status_code == 200

    response = client.post(f"/apply/{session_id}", json={})
    assert response.status_code == 200, response.text
    assert response.json()["entity"]["merged_cluster_count"] == 0
    assert response.json()["row_count"] == 4

    # Approve it again and the two spellings collapse into one row.
    assert client.put(f"/clusters/{session_id}", json={"clusters": body["clusters"]}).status_code == 200
    merged = client.post(f"/apply/{session_id}", json={}).json()
    assert merged["entity"]["merged_cluster_count"] == 1
    assert merged["entity"]["duplicate_row_count"] == 1
    assert merged["row_count"] == 3


def test_cluster_is_refused_while_the_plan_still_waits_for_review(client: TestClient):
    session_id = _upload(client)
    client.post(f"/analyze/{session_id}", json={})

    response = client.post(f"/cluster/{session_id}", json={"column": "product_name"})

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "review_pending"
    assert client.get(f"/clusters/{session_id}").status_code == 404


def test_cluster_refuses_a_column_that_is_not_text(client: TestClient):
    session_id = _upload(client)
    client.post(f"/analyze/{session_id}", json={})
    _approve(client, session_id)

    response = client.post(f"/cluster/{session_id}", json={"column": "unit_price"})

    assert response.status_code == 400
    assert "decimal" in response.json()["detail"]


def test_unknown_session_is_reported_as_missing(client: TestClient):
    assert client.get("/status/does-not-exist").status_code == 404
    assert client.post("/apply/does-not-exist", json={}).status_code == 404


def test_deleting_a_session_removes_its_workspace(client: TestClient, tmp_path: Path):
    session_id = _upload(client)
    workspace = tmp_path / "sessions" / session_id
    assert workspace.is_dir()

    assert client.delete(f"/session/{session_id}").status_code == 204

    assert not workspace.exists()
    assert client.get(f"/status/{session_id}").status_code == 404


def test_provider_endpoint_never_returns_the_key(client: TestClient, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-do-not-leak")

    response = client.get("/provider")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "openai"
    assert body["configured"] is True
    assert "sk-test-do-not-leak" not in response.text


def test_a_refused_provider_call_is_reported_as_an_upstream_failure(client: TestClient):
    """A configured provider that refuses is 502, not 400: nothing is written."""

    from core.llm import LLMClient, LLMRequestError

    class RefusingClient(LLMClient):
        def complete(self, system: str, user: str) -> str:
            raise LLMRequestError("OpenAI isteği başarısız: model_not_found.")

    session_id = _upload(client)
    client.app.dependency_overrides[get_llm_client] = RefusingClient

    response = client.post(f"/analyze/{session_id}")

    assert response.status_code == 502
    body = response.json()
    assert body["error"] == "llm_request_failed"
    assert "model_not_found" in body["message"]
    assert client.get(f"/status/{session_id}").json()["has_mapping"] is False


def test_analyze_without_a_configured_key_fails_clearly(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")  # also blocks .env from filling it in
    app = create_app(sessions=SessionStore(tmp_path / "sessions"))
    with TestClient(app) as configured_client:
        session_id = _upload(configured_client)

        response = configured_client.post(f"/analyze/{session_id}", json={})

        assert response.status_code == 503
        body = response.json()
        assert body["error"] == "llm_not_configured"
        assert "OPENAI_API_KEY" in body["message"]
        assert configured_client.get("/provider").json()["configured"] is False
