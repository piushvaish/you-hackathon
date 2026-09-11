from datetime import datetime, timezone

from kojable_agent.models import (
    Claim,
    CleanDataStatus,
    EvidenceRecord,
    EvidenceValidation,
    SourceType,
)
from kojable_agent.scoring import score_baseline


def evidence(evidence_id: str) -> EvidenceRecord:
    return EvidenceRecord(
        id=evidence_id,
        url=f"https://example.com/{evidence_id}",
        title="Evidence",
        publisher_domain="example.com",
        retrieved_at=datetime.now(timezone.utc),
        published_at="2026-01-01",
        highlights=["support"],
        source_type=SourceType.INDEPENDENT,
    )


def claim(claim_id: str, evidence_ids: list[str], *, material: bool = True) -> Claim:
    return Claim(
        id=claim_id,
        text="A material statement",
        subject="comparison",
        category="other",
        material=material,
        evidence_ids=evidence_ids,
    )


def validation(evidence_id: str, status: CleanDataStatus) -> EvidenceValidation:
    return EvidenceValidation(evidence_id=evidence_id, status=status)


def test_deterministic_score_math_and_unsupported_claims() -> None:
    result = score_baseline(
        [claim("c1", ["e1"]), claim("c2", [])],
        [evidence("e1")],
        [validation("e1", CleanDataStatus.VALID)],
    )
    assert result.alignment_score == 50
    assert result.supported_claims == 1
    assert result.unsupported_claims == 1


def test_incomplete_evidence_supports_but_gets_no_clean_credit() -> None:
    result = score_baseline(
        [claim("c1", ["e1"])],
        [evidence("e1")],
        [validation("e1", CleanDataStatus.INCOMPLETE)],
    )
    assert result.alignment_score == 50
    assert result.clean_evidence_records == 0
    assert result.incomplete_evidence_records == 1


def test_unknown_evidence_id_does_not_count_as_support() -> None:
    result = score_baseline([claim("c1", ["fabricated"])], [], [])
    assert result.alignment_score == 0
    assert result.unsupported_claims == 1


def test_zero_material_claim_edge_case() -> None:
    result = score_baseline([claim("c1", [], material=False)], [], [])
    assert result.alignment_score == 0
    assert result.material_claims == 0
