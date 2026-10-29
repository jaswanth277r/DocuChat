from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import time
from pathlib import Path

from bson import ObjectId

from .. import db
from ..config import BASE_DIR, get_settings
from ..generation.answer import extractive_answer
from ..generation.citations import build_citations, coverage_summary, verify_support
from ..generation.providers import provider_status
from ..ingestion.pipeline import ingest_document
from ..retrieval.embeddings import embedder_status
from ..retrieval.index import search
from ..security import hash_password
from ..storage import upload_path
from .metrics import aggregate, ndcg_at_k, recall_at_k, reciprocal_rank

EVAL_DIR = BASE_DIR / "evaluation"
EVAL_FIXTURES = EVAL_DIR / "fixtures"
EVAL_EMAIL = "eval@docuchat.local"


def load_dataset(name: str = "default") -> dict:
    path = EVAL_DIR / ("dataset.json" if name == "default" else f"{name}.json")
    if not path.exists():
        raise FileNotFoundError(f"Evaluation dataset not found: {path}")
    return json.loads(path.read_text())


def ensure_eval_user() -> dict:
    user = db.users().find_one({"email": EVAL_EMAIL})
    if user:
        return user
    user_id = db.users().insert_one(
        {
            "email": EVAL_EMAIL,
            "name": "Evaluation Runner",
            "password_hash": hash_password(str(ObjectId()) + "Eval-only-1"),
            "role": "student",
            "disabled": False,
            "is_eval": True,
            "created_at": db.utcnow(),
        }
    ).inserted_id
    return db.users().find_one({"_id": user_id})


def ensure_fixture_document(owner_id: ObjectId, fixture_key: str, filename: str) -> dict:
    path = EVAL_FIXTURES / filename
    if not path.exists():
        raise FileNotFoundError(f"Fixture missing: {path}. Run scripts/make_fixtures.py first.")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    existing = db.documents().find_one(
        {"user_id": owner_id, "fixture_key": fixture_key, "deleted": {"$ne": True}}
    )
    if existing and existing.get("sha256") == digest and existing.get("status") == "ready" and existing.get("ingest_version"):
        return existing

    document_id = existing["_id"] if existing else ObjectId()
    target = upload_path(str(document_id))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, target)
    record = {
        "user_id": owner_id,
        "original_name": filename,
        "title": path.stem.replace("_", " ").title(),
        "status": "queued",
        "progress": 8,
        "stage_message": "Queued for evaluation",
        "size_bytes": path.stat().st_size,
        "sha256": digest,
        "fixture_key": fixture_key,
        "category_locked": False,
        "warnings": [],
        "error": None,
        "created_at": existing.get("created_at") if existing else db.utcnow(),
        "updated_at": db.utcnow(),
        "deleted": False,
    }
    if existing:
        db.documents().update_one({"_id": document_id}, {"$set": record})
    else:
        record["_id"] = document_id
        record["ingest_version"] = 0
        db.documents().insert_one(record)
    ingest_document(str(document_id), str(owner_id), lambda *args: None)
    return db.documents().find_one({"_id": document_id})


def _ranked_pages(candidates: list[dict]) -> list[int]:
    pages = []
    seen = set()
    for candidate in candidates:
        page = int(candidate.get("page_number") or 0)
        if page and page not in seen:
            seen.add(page)
            pages.append(page)
    return pages


def run_evaluation(dataset_name: str = "default") -> dict:
    dataset = load_dataset(dataset_name)
    owner = ensure_eval_user()
    owner_id = owner["_id"]

    documents = {}
    for key, filename in dataset["fixtures"].items():
        documents[key] = ensure_fixture_document(owner_id, key, filename)

    settings = get_settings()
    config = {
        "embedder": embedder_status(),
        "provider": provider_status(),
        "retrieval_top_k": settings.retrieval_top_k,
        "rerank_top_n": settings.rerank_top_n,
        "rrf_k": settings.rrf_k,
        "vector_weight": settings.vector_weight,
        "bm25_weight": settings.bm25_weight,
        "enable_rerank": settings.enable_rerank,
        "min_retrieval_confidence": settings.min_retrieval_confidence,
        "answer_mode": "extractive (deterministic)",
    }

    records = []
    for question in dataset["questions"]:
        doc_ids = [str(documents[key]["_id"]) for key in question["documents"]]
        started = time.perf_counter()
        result = search(question["question"], doc_ids, str(owner_id))
        answer, abstained = extractive_answer(question["question"], result)
        citations, claims = build_citations(answer, result.get("selected") or [], doc_ids)
        citations = asyncio.run(
            verify_support(citations, result.get("selected") or [], None, False, extractive=True)
        )
        coverage = coverage_summary(citations, claims)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)

        ranked = _ranked_pages(result.get("candidates") or [])
        expected_pages = question.get("expected_pages") or []
        tokens = [token.lower() for token in question.get("expected_answer_contains") or []]
        answer_lower = answer.lower()
        answer_hit = bool(tokens) and all(token in answer_lower for token in tokens)
        invalid = sum(1 for citation in citations if citation.get("status") == "invalid")
        supported = sum(1 for citation in citations if citation.get("status") in {"verified", "partial"})

        records.append(
            {
                "id": question["id"],
                "type": question.get("type"),
                "question": question["question"],
                "expected_pages": expected_pages,
                "ranked_pages": ranked[:10],
                "selected_pages": sorted({int(c["page_number"]) for c in result.get("selected") or []}),
                "recall_at_5": round(recall_at_k(expected_pages, ranked, 5), 3),
                "rr": round(reciprocal_rank(expected_pages, ranked), 3),
                "ndcg_at_5": round(ndcg_at_k(expected_pages, ranked, 5), 3),
                "confidence": result.get("confidence"),
                "sufficient": result.get("sufficient"),
                "abstained": abstained,
                "expected_abstain": bool(question.get("expected_abstain")),
                "answer_hit": answer_hit,
                "answer": answer[:700],
                "citations_total": len(citations),
                "citations_invalid": invalid,
                "citations_supported": supported,
                "coverage": coverage,
                "latency_ms": latency_ms,
            }
        )

    summary = aggregate(records)
    report = {
        "dataset": dataset_name,
        "description": dataset.get("description"),
        "config": config,
        "summary": summary,
        "records": records,
        "created_at": db.utcnow().isoformat(),
    }
    db.evaluation_runs().insert_one(
        {
            "dataset": dataset_name,
            "summary": summary,
            "config": config,
            "records": records,
            "created_at": db.utcnow(),
            "run_by": "evaluation-runner",
        }
    )
    return report


def print_report(report: dict) -> None:
    summary = report["summary"]
    print(f"\nDocuChat evaluation — {report['dataset']}")
    print("=" * 64)
    for key in (
        "recall_at_5",
        "mrr",
        "ndcg_at_5",
        "answer_accuracy",
        "correct_abstention_rate",
        "false_abstention_rate",
        "citation_validity_rate",
        "citation_support_rate",
        "latency_p50_ms",
        "latency_p95_ms",
    ):
        print(f"{key:28} {summary.get(key)}")
    print("-" * 64)
    for record in report["records"]:
        flag = "PASS" if (record["answer_hit"] or record.get("expected_abstain") == record.get("abstained")) else "CHECK"
        print(
            f"{flag:5} {record['id']:28} r@5={record['recall_at_5']:.2f} "
            f"conf={record['confidence']} abstain={record['abstained']} "
            f"pages={record['selected_pages']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DocuChat RAG evaluation")
    parser.add_argument("--dataset", default="default")
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    report = run_evaluation(args.dataset)
    print_report(report)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, default=str))
        print(f"\nSaved report to {args.json_out}")


if __name__ == "__main__":
    main()
