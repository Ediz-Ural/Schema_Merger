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
from web.backend.auth import UserStore
from web.backend.main import create_app
from web.backend.routes import SessionStore, get_embedding_client, get_llm_client


ACCOUNT = {"email": "kullanici@example.com", "password": "parola1234"}


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


def _app(tmp_path: Path) -> "object":
    return create_app(
        sessions=SessionStore(tmp_path / "sessions"), users=UserStore(tmp_path / "users.db")
    )


def _sign_up(test_client: TestClient, account: dict[str, str] | None = None) -> str:
    """Register an account and return its bearer token."""

    response = test_client.post("/auth/register", json=account or ACCOUNT)
    assert response.status_code == 201, response.text
    return response.json()["token"]


@pytest.fixture
def client(tmp_path: Path, llm: FakeLLMClient, embedder: FakeEmbeddingClient) -> TestClient:
    """A signed-in client; the provider itself is faked through the overrides."""

    app = _app(tmp_path)
    app.dependency_overrides[get_llm_client] = lambda: llm
    app.dependency_overrides[get_embedding_client] = lambda: embedder
    with TestClient(app) as test_client:
        test_client.headers["Authorization"] = f"Bearer {_sign_up(test_client)}"
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


def test_a_users_own_key_is_accepted_but_never_returned(client: TestClient):
    """The key is held in memory for this process only; no route echoes it."""

    response = client.put(
        "/provider",
        json={"provider": "openai", "model": "gpt-5-nano", "api_key": "sk-test-do-not-leak"},
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["provider"], body["model"], body["configured"]) == ("openai", "gpt-5-nano", True)
    assert "sk-test-do-not-leak" not in response.text
    for path in ("/provider", "/auth/me"):
        assert "sk-test-do-not-leak" not in client.get(path).text
    assert client.get("/auth/me").json()["key_configured"] is True


def test_a_key_is_never_written_to_disk(client: TestClient, tmp_path: Path):
    """Neither the accounts database nor a workspace may contain the key."""

    client.put("/provider", json={"provider": "openai", "api_key": "sk-secret-value"})
    _upload(client)

    written = [
        path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    ]
    assert not any(b"sk-secret-value" in blob for blob in written)


def test_forgetting_the_key_leaves_the_model_choice_alone(client: TestClient):
    client.put("/provider", json={"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-x"})

    body = client.delete("/provider").json()

    assert body["configured"] is False
    assert body["model"] == "gpt-4o-mini"


def test_signing_out_forgets_the_key_and_the_token(client: TestClient, tmp_path: Path):
    client.put("/provider", json={"provider": "openai", "api_key": "sk-x"})

    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401

    token = client.post("/auth/login", json=ACCOUNT).json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    assert client.get("/provider").json()["configured"] is False


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


def test_analyze_without_a_key_tells_the_user_to_add_one(tmp_path: Path):
    """No key, no Phase 1: the message says where to fix it, nothing is written."""

    app = _app(tmp_path)
    with TestClient(app) as fresh_client:
        fresh_client.headers["Authorization"] = f"Bearer {_sign_up(fresh_client)}"
        session_id = _upload(fresh_client)

        response = fresh_client.post(f"/analyze/{session_id}", json={})

        assert response.status_code == 503
        body = response.json()
        assert body["error"] == "llm_not_configured"
        assert "API anahtarını" in body["message"]
        assert fresh_client.get("/provider").json()["configured"] is False
        assert fresh_client.get(f"/status/{session_id}").json()["has_mapping"] is False


def test_every_session_route_requires_a_signed_in_user(client: TestClient, tmp_path: Path):
    session_id = _upload(client)
    anonymous = TestClient(client.app)

    for method, path in [
        ("get", f"/mapping/{session_id}"),
        ("get", f"/columns/{session_id}"),
        ("get", f"/status/{session_id}"),
        ("post", f"/analyze/{session_id}"),
        ("post", f"/apply/{session_id}"),
        ("get", f"/download/{session_id}/merged"),
        ("get", "/provider"),
    ]:
        response = getattr(anonymous, method)(path)
        assert response.status_code == 401, f"{method} {path} korumasız"


def test_one_user_cannot_reach_another_users_session(client: TestClient):
    """Someone else's session is reported as missing, not as forbidden."""

    session_id = _upload(client)
    other = TestClient(client.app)
    other.headers["Authorization"] = (
        f"Bearer {_sign_up(other, {'email': 'baska@example.com', 'password': 'parola1234'})}"
    )

    for path in (f"/mapping/{session_id}", f"/status/{session_id}", f"/download/{session_id}/merged"):
        assert other.get(path).status_code == 404


def test_registration_refuses_a_taken_address_and_a_weak_password(client: TestClient):
    assert client.post("/auth/register", json=ACCOUNT).status_code == 400
    weak = {"email": "yeni@example.com", "password": "kisa"}
    response = client.post("/auth/register", json=weak)
    assert response.status_code == 400
    assert "8 karakter" in response.json()["detail"]


def test_a_wrong_password_is_refused_without_saying_which_half_was_wrong(client: TestClient):
    unknown = client.post("/auth/login", json={"email": "yok@example.com", "password": "parola1234"})
    wrong = client.post("/auth/login", json={"email": ACCOUNT["email"], "password": "yanlisparola"})

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_the_stored_password_is_never_the_password_itself(tmp_path: Path):
    """A leaked database must not hand anyone a usable password."""

    store = UserStore(tmp_path / "users.db")
    store.register("gizli@example.com", "cokgizliparola")

    blob = (tmp_path / "users.db").read_bytes()
    assert b"cokgizliparola" not in blob


def test_starting_with_several_workers_stops_instead_of_failing_silently(monkeypatch):
    """Keys live in one process's memory, so many workers would answer wrongly."""

    from web.backend.main import MULTIPROCESS_OVERRIDE_ENV

    monkeypatch.setattr("sys.argv", ["uvicorn", "web.backend.main:app", "--workers", "4"])
    monkeypatch.delenv(MULTIPROCESS_OVERRIDE_ENV, raising=False)

    with pytest.raises(RuntimeError) as refusal:
        create_app()

    message = str(refusal.value)
    assert "tek süreçte çalışır" in message
    assert "--workers 1" in message


@pytest.mark.parametrize(
    "argv, environment",
    [
        (["uvicorn", "web.backend.main:app", "--workers=8"], {}),
        (["uvicorn", "web.backend.main:app"], {"WEB_CONCURRENCY": "3"}),
        (["gunicorn", "-w", "2", "web.backend.main:app"], {}),
    ],
)
def test_the_worker_count_is_read_from_the_command_line_and_the_environment(
    monkeypatch, argv: list[str], environment: dict[str, str]
):
    from web.backend.main import MULTIPROCESS_OVERRIDE_ENV

    monkeypatch.setattr("sys.argv", argv)
    monkeypatch.delenv(MULTIPROCESS_OVERRIDE_ENV, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError):
        create_app()


def test_an_operator_who_knows_what_they_are_doing_can_override_the_refusal(monkeypatch):
    from web.backend.main import MULTIPROCESS_OVERRIDE_ENV

    monkeypatch.setattr("sys.argv", ["uvicorn", "web.backend.main:app", "--workers", "4"])
    monkeypatch.setenv(MULTIPROCESS_OVERRIDE_ENV, "1")

    assert create_app() is not None
