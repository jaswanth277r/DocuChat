from __future__ import annotations

import logging
import re
from typing import Iterable

from ..retrieval.textutil import split_sentences
from .prompts import build_support_check
from .providers import LLMProvider, ProviderError

log = logging.getLogger("docuchat.citations")

MARKER_RE = re.compile(r"\[S(\d+)\]")
ABSTAIN_PREFIX = "I couldn't find enough information"


def strip_markers(text: str) -> str:
    return re.sub(r"\s*\[S\d+\]", "", text).strip()


def _claim_units(answer: str) -> list[str]:
    """One claim per bullet, one per sentence otherwise. Bullets are the unit a
    reader verifies, so grouping them keeps citations attached to the right claim."""
    units: list[str] = []
    for raw_line in (answer or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("**"):
            continue
        if line.startswith(("- ", "* ")):
            units.append(line[2:].strip())
        else:
            units.extend(split_sentences(line))
    return [unit for unit in units if unit]


def split_claims(answer: str) -> list[dict]:
    claims: list[dict] = []
    for unit in _claim_units(answer):
        markers = [int(m) for m in MARKER_RE.findall(unit)]
        text = strip_markers(unit)
        if not text:
            continue
        claims.append({"text": text, "markers": sorted(set(markers)), "cited": bool(markers)})
    return claims


def _excerpt(text: str, limit: int = 420) -> str:
    clean = " ".join((text or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def build_citations(
    answer: str,
    passages: list[dict],
    authorized_doc_ids: Iterable[str],
) -> tuple[list[dict], list[dict]]:
    """Layer 1 (deterministic): every cited label must resolve to an authorized,
    page-accurate passage. Unresolvable markers are rejected and displayed as invalid."""
    authorized = {str(doc_id) for doc_id in authorized_doc_ids}
    by_label = {f"S{i}": passage for i, passage in enumerate(passages, start=1)}
    claims = split_claims(answer)
    citations: list[dict] = []

    for claim_index, claim in enumerate(claims):
        for marker in claim["markers"]:
            passage = by_label.get(f"S{marker}")
            if passage is None:
                citations.append(
                    {
                        "label": f"S{marker}",
                        "claim": claim["text"],
                        "status": "invalid",
                        "method": "deterministic",
                        "reason": "The citation label does not exist in the retrieved context.",
                    }
                )
                continue
            doc_id = str(passage["document_id"])
            page = int(passage.get("page_number") or 0)
            page_count = int(passage.get("page_count") or 0)
            valid = doc_id in authorized and 1 <= page <= max(page_count, 1)
            citation = {
                "label": f"S{marker}",
                "claim_index": claim_index,
                "claim": claim["text"],
                "document_id": doc_id,
                "document_title": passage.get("document_title"),
                "page_number": page,
                "page_count": page_count,
                "section_path": passage.get("section_path") or "",
                "chunk_id": passage.get("chunk_id"),
                "excerpt": _excerpt(passage.get("text", "")),
                "extraction_method": passage.get("extraction_method"),
                "status": "pending" if valid else "invalid",
                "method": "deterministic",
                "reason": None if valid else "Citation does not match an authorized passage in scope.",
            }
            citations.append(citation)

    cited_claims = sum(1 for claim in claims if claim["cited"])
    substantive = [claim for claim in claims if len(claim["text"]) > 25]
    cited_substantive = sum(1 for claim in substantive if claim["cited"])
    for claim in claims:
        claim["citation_status"] = (
            "cited" if claim["cited"] else ("uncited" if len(claim["text"]) > 25 else "ignored")
        )

    return citations, claims


async def verify_support(
    citations: list[dict],
    passages: list[dict],
    provider: LLMProvider | None,
    enabled: bool,
    extractive: bool,
    limit: int = 6,
) -> list[dict]:
    """Layer 2 (optional): ask a judge whether the passage supports the claim.

    Extractive answers are verbatim quotations from the cited passage, so they are
    marked verified without an extra model call. Deterministic failures stay invalid.
    """
    by_label = {f"S{i}": passage for i, passage in enumerate(passages, start=1)}

    for citation in citations:
        if citation["status"] == "invalid":
            continue
        if extractive:
            citation["status"] = "verified"
            citation["method"] = "verbatim_extract"
            citation["reason"] = "The quoted sentence is taken directly from the cited passage."
            continue
        if not enabled or provider is None:
            citation["status"] = "pending"
            citation["method"] = "unverified"
            citation["reason"] = "Support verification is disabled or no verifier model is configured."
            continue

    if not enabled or provider is None or extractive:
        return citations

    checked = 0
    for citation in citations:
        if citation["status"] != "pending":
            continue
        if checked >= limit:
            break
        passage = by_label.get(citation["label"])
        if not passage:
            continue
        checked += 1
        try:
            response = await provider.complete(
                build_support_check(citation["claim"], passage.get("text", ""))
            )
        except ProviderError as exc:
            citation["reason"] = f"Verification call failed: {exc}"
            continue
        verdict = response.strip().upper()
        if verdict.startswith("SUPPORTED") and not verdict.startswith("SUPPORTED_BY"):
            citation["status"] = "verified"
        elif verdict.startswith("PARTIAL"):
            citation["status"] = "partial"
        elif verdict.startswith("NOT_SUPPORTED") or verdict.startswith("NOT SUPPORTED"):
            citation["status"] = "unsupported"
        else:
            citation["status"] = "partial"
        citation["method"] = "llm_judge"
        citation["reason"] = response.strip().split("\n", 1)[0][:240]

    return citations


def coverage_summary(citations: list[dict], claims: list[dict]) -> dict:
    substantive = [c for c in claims if c["citation_status"] in {"cited", "uncited"}]
    cited = [c for c in substantive if c["citation_status"] == "cited"]
    verified = {c["claim_index"] for c in citations if c.get("status") in {"verified", "partial"}}
    invalid = [c for c in citations if c.get("status") == "invalid"]
    if not substantive:
        return {"claims": 0, "cited": 0, "ratio": 0.0, "status": "no_claims", "invalid_citations": len(invalid)}
    ratio = len(cited) / len(substantive)
    if invalid:
        status = "invalid_citations"
    elif ratio >= 0.99:
        status = "all_claims_cited"
    elif ratio >= 0.5:
        status = "some_claims_uncited"
    else:
        status = "mostly_uncited"
    return {
        "claims": len(substantive),
        "cited": len(cited),
        "verified": len(verified),
        "ratio": round(ratio, 3),
        "status": status,
        "invalid_citations": len(invalid),
    }
