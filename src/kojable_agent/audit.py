"""Focused evidence-quality audit for material comparative claims."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from .models import (
    AuditArtifact,
    AuditVerdict,
    ClaimAudit,
    FailureType,
    RunArtifact,
)


MAX_AUDIT_CLAIMS = 8


class AuditClient(Protocol):
    def audit(self, run: RunArtifact, *, max_claims: int) -> list[ClaimAudit]: ...


def audit_run(client: AuditClient, run: RunArtifact) -> AuditArtifact:
    """Audit at most eight material claims and normalize omissions honestly."""
    material = [claim for claim in run.claims if claim.material][:MAX_AUDIT_CLAIMS]
    raw = client.audit(run, max_claims=MAX_AUDIT_CLAIMS)
    valid_evidence = {record.id for record in run.evidence}
    by_claim: dict[str, ClaimAudit] = {}
    material_ids = {claim.id for claim in material}
    for item in raw:
        if item.claim_id not in material_ids or item.claim_id in by_claim:
            continue
        failures = [] if item.verdict == AuditVerdict.VERIFIED else item.failure_types
        by_claim[item.claim_id] = item.model_copy(
            update={
                "failure_types": failures,
                "verification_evidence_ids": [
                    evidence_id
                    for evidence_id in item.verification_evidence_ids
                    if evidence_id in valid_evidence
                ],
            }
        )

    normalized = []
    for claim in material:
        normalized.append(
            by_claim.get(
                claim.id,
                ClaimAudit(
                    claim_id=claim.id,
                    verdict=AuditVerdict.UNSUPPORTED,
                    failure_types=[FailureType.INSUFFICIENT_EVIDENCE],
                    explanation="The auditor returned no result for this material claim.",
                ),
            )
        )
    return AuditArtifact(
        run_id=run.run_id,
        question=run.question,
        created_at=datetime.now(timezone.utc),
        claims=normalized,
    )


def weakness_count(audit: AuditArtifact) -> int:
    return sum(item.verdict != AuditVerdict.VERIFIED.value for item in audit.claims)
