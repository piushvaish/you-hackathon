from datetime import datetime, timezone

import pytest

from kojable_agent.audit import audit_run
from kojable_agent.learning import parse_learned_rule, select_learned_rule
from kojable_agent.models import (
    AnswerArtifact,
    AuditArtifact,
    AuditVerdict,
    BaselineScore,
    Claim,
    ClaimAudit,
    CleanDataSummary,
    FailureType,
    RunArtifact,
)


def run_with_claims(count: int = 5) -> RunArtifact:
    return RunArtifact(
        question="Which is better?",
        created_at=datetime.now(timezone.utc),
        answer=AnswerArtifact(text="Answer", recommendation="depends"),
        claims=[
            Claim(
                id=f"claim_{index}",
                text=f"Material comparison {index}",
                subject="comparison",
                category="other",
                material=True,
            )
            for index in range(count)
        ],
        evidence=[],
        clean_data=CleanDataSummary(
            valid_records=0, incomplete_records=0, invalid_records=0
        ),
        baseline_score=BaselineScore(
            alignment_score=0,
            material_claims=count,
            supported_claims=0,
            unsupported_claims=count,
            clean_evidence_records=0,
            incomplete_evidence_records=0,
        ),
    )


class FakeAuditor:
    def __init__(self, results):
        self.results = results

    def audit(self, run, *, max_claims):
        assert max_claims == 8
        return self.results


@pytest.mark.parametrize(
    ("verdict", "failure"),
    [
        (AuditVerdict.VERIFIED, None),
        (AuditVerdict.UNSUPPORTED, FailureType.INSUFFICIENT_EVIDENCE),
        (
            AuditVerdict.WEAK,
            FailureType.COMPETITOR_CLAIM_NOT_INDEPENDENTLY_VERIFIED,
        ),
        (AuditVerdict.CONFLICTED, FailureType.CONFLICTING_EVIDENCE),
        (AuditVerdict.WEAK, FailureType.ENDPOINT_PLATFORM_OVERGENERALIZATION),
    ],
)
def test_audit_preserves_supported_failure_vocabulary(verdict, failure) -> None:
    failures = [] if failure is None else [failure]
    result = audit_run(
        FakeAuditor(
            [
                ClaimAudit(
                    claim_id="claim_0",
                    verdict=verdict,
                    failure_types=failures,
                    explanation="Evidence-quality finding.",
                )
            ]
        ),
        run_with_claims(1),
    )
    assert result.claims[0].verdict == verdict
    assert result.claims[0].failure_types == failures


def test_audit_caps_material_claims_and_marks_missing_results_unsupported() -> None:
    result = audit_run(FakeAuditor([]), run_with_claims(10))
    assert len(result.claims) == 8
    assert all(item.verdict == AuditVerdict.UNSUPPORTED for item in result.claims)


def test_learning_uses_documented_priority_and_selects_one_rule() -> None:
    audit = AuditArtifact(
        run_id="run_1",
        question="Which is better?",
        created_at=datetime.now(timezone.utc),
        claims=[
            ClaimAudit(
                claim_id="c1",
                verdict=AuditVerdict.WEAK,
                failure_types=[FailureType.MISSING_PRIMARY_VERIFICATION],
                explanation="Primary source missing.",
            ),
            ClaimAudit(
                claim_id="c2",
                verdict=AuditVerdict.UNSUPPORTED,
                failure_types=[FailureType.UNSUPPORTED_COMPARISON],
                explanation="Comparison unsupported.",
            ),
        ],
    )
    learned = select_learned_rule(audit)
    assert learned is not None
    assert learned.trigger == FailureType.UNSUPPORTED_COMPARISON
    assert learned.failure == "Comparison unsupported."
    assert len(learned.behaviors) <= 2


def test_learning_does_not_invent_failure_for_clean_audit() -> None:
    audit = AuditArtifact(
        run_id="run_1",
        question="Which is better?",
        created_at=datetime.now(timezone.utc),
        claims=[
            ClaimAudit(
                claim_id="c1",
                verdict=AuditVerdict.VERIFIED,
                explanation="Verified by current primary documentation.",
            )
        ],
    )
    assert select_learned_rule(audit) is None


def test_issue_rule_parser_reads_only_external_markdown_section() -> None:
    body = "# Memory\n\n## Learned rule\n\nVerify both vendors.\n\n## Trigger\n\nmissing"
    assert parse_learned_rule(body) == "Verify both vendors."
