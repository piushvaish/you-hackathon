"""Deterministic evidence provenance and claim-linking rules."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from .models import (
    Claim,
    CleanDataStatus,
    EvidenceRecord,
    EvidenceValidation,
    ResearchClaim,
    SearchResult,
    SourceType,
)


YOU_DOMAINS = {"you.com", "docs.you.com", "about.you.com"}
EXA_DOMAINS = {"exa.ai"}
VENDOR_DOMAINS = YOU_DOMAINS | EXA_DOMAINS
STOP_WORDS = {
    "about",
    "agent",
    "agents",
    "also",
    "and",
    "are",
    "can",
    "com",
    "for",
    "from",
    "has",
    "into",
    "its",
    "that",
    "the",
    "their",
    "this",
    "through",
    "with",
}


def publisher_domain(url: str) -> str:
    try:
        domain = (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return domain[4:] if domain.startswith("www.") else domain


def classify_source(domain: str, subject: str | None = None) -> SourceType:
    normalized_domain = domain.lower().rstrip(".")
    owner = _vendor_owner(normalized_domain)
    normalized_subject = (subject or "").lower()
    subject_owner = (
        "you.com"
        if normalized_subject in {"you", "you.com"}
        else "exa"
        if normalized_subject in {"exa", "exa.ai"}
        else None
    )
    if owner and subject_owner and owner != subject_owner:
        return SourceType.COMPETITOR
    if owner:
        return SourceType.PRIMARY
    if normalized_domain:
        return SourceType.INDEPENDENT
    return SourceType.UNKNOWN


def normalize_evidence(
    result: SearchResult,
    *,
    retrieved_at: datetime | None = None,
    subject: str | None = None,
) -> EvidenceRecord:
    timestamp = retrieved_at or datetime.now(timezone.utc)
    domain = publisher_domain(result.url)
    digest = hashlib.sha256(result.url.encode("utf-8")).hexdigest()[:12]
    return EvidenceRecord(
        id=f"ev_{digest}",
        url=result.url,
        title=result.title,
        publisher_domain=domain,
        retrieved_at=timestamp,
        published_at=result.published_at,
        highlights=[text.strip() for text in result.highlights if text.strip()],
        description=result.description.strip() if result.description else None,
        source_type=classify_source(domain, subject),
    )


def validate_evidence(record: EvidenceRecord) -> EvidenceValidation:
    reasons: list[str] = []
    if not record.url.strip() or not publisher_domain(record.url):
        reasons.append("source URL unavailable or malformed")
    if not record.publisher_domain.strip():
        reasons.append("publisher domain unavailable")
    if record.retrieved_at is None:
        reasons.append("retrieval timestamp unavailable")
    if not any(text.strip() for text in record.highlights):
        reasons.append("retrieved evidence text unavailable")

    if reasons:
        status = CleanDataStatus.INVALID
    elif not record.published_at:
        status = CleanDataStatus.INCOMPLETE
        reasons.append("publication date unavailable")
    else:
        status = CleanDataStatus.VALID
    return EvidenceValidation(evidence_id=record.id, status=status, reasons=reasons)


def link_claims_to_evidence(
    research_claims: list[ResearchClaim], evidence: list[EvidenceRecord]
) -> list[Claim]:
    """Link by auditable token overlap; leave weak matches unsupported."""
    linked: list[Claim] = []
    for index, research_claim in enumerate(research_claims, start=1):
        claim_tokens = _tokens(research_claim.claim)
        matches: list[tuple[int, str]] = []
        for record in evidence:
            evidence_text = " ".join(
                [record.title, record.description or "", *record.highlights]
            )
            overlap = len(claim_tokens & _tokens(evidence_text))
            if overlap >= 2:
                matches.append((overlap, record.id))
        matches.sort(key=lambda item: (-item[0], item[1]))
        linked.append(
            Claim(
                id=f"claim_{index:03d}",
                text=research_claim.claim,
                subject=research_claim.subject,
                category=research_claim.category,
                material=research_claim.material,
                evidence_ids=[evidence_id for _, evidence_id in matches[:3]],
            )
        )
    return linked


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in STOP_WORDS
    }


def _vendor_owner(domain: str) -> str | None:
    if domain in YOU_DOMAINS or domain.endswith(".you.com"):
        return "you.com"
    if domain in EXA_DOMAINS or domain.endswith(".exa.ai"):
        return "exa"
    return None
