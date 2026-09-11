from datetime import datetime, timezone

from kojable_agent.models import (
    AuditVerdict,
    Claim,
    ClaimAudit,
    CleanDataStatus,
    EvidenceRecord,
    EvidenceValidation,
    SourceType,
)
from kojable_agent.scoring import comparison_status, score_answer_alignment


def test_verified_claim_earns_third_point_and_other_verdicts_do_not() -> None:
    evidence = [
        EvidenceRecord(
            id="e1",
            url="https://example.com/docs",
            title="Docs",
            publisher_domain="example.com",
            retrieved_at=datetime.now(timezone.utc),
            published_at="2026-09-01",
            highlights=["support"],
            source_type=SourceType.PRIMARY,
        )
    ]
    claims = [
        Claim(
            id="verified",
            text="Verified",
            subject="vendor",
            category="search",
            material=True,
            evidence_ids=["e1"],
        ),
        Claim(
            id="weak",
            text="Weak",
            subject="vendor",
            category="search",
            material=True,
            evidence_ids=["e1"],
        ),
        Claim(
            id="conflicted",
            text="Conflicted",
            subject="vendor",
            category="search",
            material=True,
            evidence_ids=["e1"],
        ),
    ]
    validations = [EvidenceValidation(evidence_id="e1", status=CleanDataStatus.VALID)]
    audits = [
        ClaimAudit(claim_id="verified", verdict=AuditVerdict.VERIFIED, explanation="ok"),
        ClaimAudit(claim_id="weak", verdict=AuditVerdict.WEAK, explanation="weak"),
        ClaimAudit(
            claim_id="conflicted", verdict=AuditVerdict.CONFLICTED, explanation="conflict"
        ),
    ]
    score = score_answer_alignment(claims, evidence, validations, audits)
    assert score.alignment_score == 78
    assert score.verified_claims == 1
    assert score.weak_claims == 1
    assert score.conflicted_claims == 1
    assert score.supported_claims == 3


def test_same_formula_produces_honest_delta_status() -> None:
    assert comparison_status(19) == "improved"
    assert comparison_status(0) == "unchanged"
    assert comparison_status(-4) == "regressed"
