"""Local reference implementation of Baseline Evidence Alignment."""

from __future__ import annotations

import math
from typing import Literal

from .models import (
    AnswerAlignmentScore,
    AuditVerdict,
    BaselineScore,
    Claim,
    ClaimAudit,
    CleanDataStatus,
    EvidenceRecord,
    EvidenceValidation,
)


def scoring_payload(
    claims: list[Claim],
    evidence: list[EvidenceRecord],
    validations: list[EvidenceValidation],
) -> dict[str, list[dict[str, object]]]:
    status_by_id = {item.evidence_id: item.status.value for item in validations}
    return {
        "claims": [
            {
                "id": claim.id,
                "material": claim.material,
                "evidence_ids": claim.evidence_ids,
            }
            for claim in claims
        ],
        "evidence": [
            {"id": record.id, "status": status_by_id.get(record.id, "invalid")}
            for record in evidence
        ],
    }


def score_baseline(
    claims: list[Claim],
    evidence: list[EvidenceRecord],
    validations: list[EvidenceValidation],
) -> BaselineScore:
    return score_payload(scoring_payload(claims, evidence, validations))


def score_payload(payload: dict[str, list[dict[str, object]]]) -> BaselineScore:
    material_claims = [claim for claim in payload["claims"] if claim["material"]]
    evidence_status = {
        str(record["id"]): str(record["status"]) for record in payload["evidence"]
    }
    supported = 0
    clean_supported = 0
    for claim in material_claims:
        referenced = [
            evidence_id
            for evidence_id in claim["evidence_ids"]
            if evidence_id in evidence_status
        ]
        if referenced:
            supported += 1
        if any(evidence_status[evidence_id] == "valid" for evidence_id in referenced):
            clean_supported += 1

    count = len(material_claims)
    possible = count * 2
    earned = supported + clean_supported
    percentage = math.floor((earned / possible * 100) + 0.5) if possible else 0
    return BaselineScore(
        alignment_score=percentage,
        material_claims=count,
        supported_claims=supported,
        unsupported_claims=count - supported,
        clean_evidence_records=sum(
            status == "valid" for status in evidence_status.values()
        ),
        incomplete_evidence_records=sum(
            status == "incomplete" for status in evidence_status.values()
        ),
    )


def alignment_scoring_payload(
    claims: list[Claim],
    evidence: list[EvidenceRecord],
    validations: list[EvidenceValidation],
    audits: list[ClaimAudit],
) -> dict[str, list[dict[str, object]]]:
    payload = scoring_payload(claims, evidence, validations)
    payload["audits"] = [
        {"claim_id": audit.claim_id, "verdict": audit.verdict.value}
        for audit in audits
    ]
    return payload


def score_answer_alignment(
    claims: list[Claim],
    evidence: list[EvidenceRecord],
    validations: list[EvidenceValidation],
    audits: list[ClaimAudit],
) -> AnswerAlignmentScore:
    return score_alignment_payload(
        alignment_scoring_payload(claims, evidence, validations, audits)
    )


def score_alignment_payload(
    payload: dict[str, list[dict[str, object]]],
) -> AnswerAlignmentScore:
    material_claims = [claim for claim in payload["claims"] if claim["material"]]
    evidence_status = {
        str(record["id"]): str(record["status"]) for record in payload["evidence"]
    }
    verdict_by_claim = {
        str(audit["claim_id"]): str(audit["verdict"])
        for audit in payload.get("audits", [])
    }
    supported = 0
    clean_supported = 0
    verdict_counts = {verdict.value: 0 for verdict in AuditVerdict}
    for claim in material_claims:
        referenced = [
            evidence_id
            for evidence_id in claim["evidence_ids"]
            if evidence_id in evidence_status
        ]
        supported += bool(referenced)
        clean_supported += any(
            evidence_status[evidence_id] == "valid" for evidence_id in referenced
        )
        verdict = verdict_by_claim.get(str(claim["id"]), AuditVerdict.UNSUPPORTED.value)
        if verdict not in verdict_counts:
            verdict = AuditVerdict.UNSUPPORTED.value
        verdict_counts[verdict] += 1

    earned = supported + clean_supported + verdict_counts[AuditVerdict.VERIFIED.value]
    possible = len(material_claims) * 3
    percentage = math.floor((earned / possible * 100) + 0.5) if possible else 0
    return AnswerAlignmentScore(
        alignment_score=percentage,
        material_claims=len(material_claims),
        verified_claims=verdict_counts[AuditVerdict.VERIFIED.value],
        weak_claims=verdict_counts[AuditVerdict.WEAK.value],
        conflicted_claims=verdict_counts[AuditVerdict.CONFLICTED.value],
        unsupported_claims=verdict_counts[AuditVerdict.UNSUPPORTED.value],
        supported_claims=supported,
        clean_evidence_records=sum(
            status == "valid" for status in evidence_status.values()
        ),
    )


def comparison_status(delta: int) -> Literal["improved", "unchanged", "regressed"]:
    if delta > 0:
        return "improved"
    if delta < 0:
        return "regressed"
    return "unchanged"
