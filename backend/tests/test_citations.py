from __future__ import annotations

from app.generation.citations import build_citations, coverage_summary, verify_support
from app.retrieval.index import search


def _passages(corpus, owner):
    result = search("What does Section 4.2 say?", [str(corpus["notes"]["_id"])], owner.id)
    return result["selected"]


def test_valid_citation_is_verified(corpus, owner):
    passages = _passages(corpus, owner)
    answer = f"- The scaling factor keeps logits stable. [{passages[0]['citation_label']}]"
    citations, claims = build_citations(answer, passages, [str(corpus["notes"]["_id"])])
    citations = __import__("asyncio").run(verify_support(citations, passages, None, False, extractive=True))
    coverage = coverage_summary(citations, claims)
    assert citations[0]["status"] == "verified"
    assert citations[0]["page_number"] == 2
    assert coverage["status"] == "all_claims_cited"


def test_unknown_label_is_rejected(corpus, owner):
    passages = _passages(corpus, owner)
    citations, _ = build_citations("- A claim with a fake source. [S42]", passages, [str(corpus["notes"]["_id"])])
    assert citations[0]["status"] == "invalid"


def test_document_outside_scope_is_rejected(corpus, owner):
    passages = _passages(corpus, owner)
    answer = f"- A claim. [{passages[0]['citation_label']}]"
    citations, _ = build_citations(answer, passages, [])
    assert citations[0]["status"] == "invalid"


def test_page_outside_document_is_rejected(corpus, owner):
    passages = _passages(corpus, owner)
    tampered = [dict(passages[0], page_number=99)]
    citations, _ = build_citations("- A claim. [S1]", tampered, [str(corpus["notes"]["_id"])])
    assert citations[0]["status"] == "invalid"


def test_uncited_claim_is_reported(corpus, owner):
    passages = _passages(corpus, owner)
    answer = f"- This claim is cited. [{passages[0]['citation_label']}]\n- This factual sentence has no source attached at all."
    citations, claims = build_citations(answer, passages, [str(corpus["notes"]["_id"])])
    coverage = coverage_summary(citations, claims)
    assert coverage["status"] == "some_claims_uncited"
    assert coverage["claims"] == 2
