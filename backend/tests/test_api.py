from __future__ import annotations

from pathlib import Path

from app.evaluation.metrics import aggregate, ndcg_at_k, recall_at_k, reciprocal_rank

FIXTURES = Path(__file__).resolve().parents[2] / "evaluation" / "fixtures"


def test_retrieval_metrics():
    assert recall_at_k([2, 3], [1, 2, 3, 4], 5) == 1.0
    assert recall_at_k([4], [1, 2, 3], 5) == 0.0
    assert reciprocal_rank([3], [1, 2, 3]) == 1 / 3
    assert ndcg_at_k([1], [1, 2, 3], 5) == 1.0


def test_aggregate_tracks_abstention_and_citations():
    records = [
        {
            "citations_total": 2,
            "citations_invalid": 0,
            "citations_supported": 2,
            "latency_ms": 40,
            "recall_at_5": 1.0,
            "rr": 1.0,
            "ndcg_at_5": 1.0,
            "expected_abstain": False,
            "abstained": False,
            "answer_hit": True,
        },
        {
            "citations_total": 0,
            "citations_invalid": 0,
            "citations_supported": 0,
            "latency_ms": 20,
            "recall_at_5": 1.0,
            "rr": 0.5,
            "ndcg_at_5": 0.5,
            "expected_abstain": True,
            "abstained": True,
            "answer_hit": False,
        },
    ]
    summary = aggregate(records)
    assert summary["recall_at_5"] == 1.0
    assert summary["mrr"] == 0.75
    assert summary["correct_abstention_rate"] == 1.0
    assert summary["false_abstention_rate"] == 0.0
    assert summary["citation_validity_rate"] == 1.0
    assert summary["citation_support_rate"] == 1.0


def test_api_auth_and_document_isolation(client):
    register = client.post(
        "/api/auth/register",
        json={"email": "api-one@test.local", "password": "password-123", "name": "API One"},
    )
    assert register.status_code == 200, register.text
    assert register.json()["email"] == "api-one@test.local"
    me = client.get("/api/auth/me")
    assert me.status_code == 200

    duplicate = client.post(
        "/api/auth/register",
        json={"email": "api-one@test.local", "password": "password-123", "name": "Dup"},
    )
    assert duplicate.status_code == 409

    pdf = (FIXTURES / "transformer_notes.pdf").read_bytes()
    upload = client.post(
        "/api/documents",
        files={"file": ("notes.pdf", pdf, "application/pdf")},
    )
    assert upload.status_code == 200, upload.text
    document_id = upload.json()["id"]

    other = client
    other.post("/api/auth/logout")
    other.post(
        "/api/auth/register",
        json={"email": "api-two@test.local", "password": "password-123", "name": "API Two"},
    )
    forbidden = other.get(f"/api/documents/{document_id}")
    assert forbidden.status_code == 404
    assert other.get(f"/api/documents/{document_id}/file").status_code == 404


def test_upload_rejects_fake_pdf(client):
    client.post("/api/auth/login", json={"email": "api-two@test.local", "password": "password-123"})
    response = client.post(
        "/api/documents",
        files={"file": ("fake.pdf", b"this is not a PDF at all", "application/pdf")},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "not_pdf"


def test_requires_authentication(client):
    fresh = client.__class__(client.app)
    assert fresh.get("/api/documents").status_code == 401
    assert fresh.get("/api/system/status").status_code == 401
