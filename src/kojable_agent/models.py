"""Typed contracts shared by retrieval, validation, scoring, and persistence."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Recommendation = Literal["you.com", "exa", "depends", "insufficient_evidence"]
ClaimCategory = Literal[
    "search",
    "extraction",
    "research",
    "freshness",
    "developer_experience",
    "pricing",
    "other",
]


class SourceType(str, Enum):
    PRIMARY = "primary"
    COMPETITOR = "competitor"
    INDEPENDENT = "independent"
    UNKNOWN = "unknown"


class CleanDataStatus(str, Enum):
    VALID = "valid"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"


class AuditVerdict(str, Enum):
    VERIFIED = "verified"
    WEAK = "weak"
    CONFLICTED = "conflicted"
    UNSUPPORTED = "unsupported"


class FailureType(str, Enum):
    MISSING_PRIMARY_VERIFICATION = "missing_primary_verification"
    COMPETITOR_CLAIM_NOT_INDEPENDENTLY_VERIFIED = (
        "competitor_claim_not_independently_verified"
    )
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    POSSIBLE_STALE_EVIDENCE = "possible_stale_evidence"
    ENDPOINT_PLATFORM_OVERGENERALIZATION = "endpoint_platform_overgeneralization"
    UNSUPPORTED_COMPARISON = "unsupported_comparison"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class SearchResult(BaseModel):
    url: str
    title: str = ""
    published_at: str | None = None
    highlights: list[str] = Field(default_factory=list)
    description: str | None = None


class EvidenceRecord(BaseModel):
    id: str
    url: str
    title: str
    publisher_domain: str
    retrieved_at: datetime | None
    published_at: str | None = None
    highlights: list[str] = Field(default_factory=list)
    description: str | None = None
    source_type: SourceType


class EvidenceValidation(BaseModel):
    evidence_id: str
    status: CleanDataStatus
    reasons: list[str] = Field(default_factory=list)


class ResearchClaim(BaseModel):
    claim: str
    subject: str
    category: ClaimCategory
    material: bool


class ResearchAnswer(BaseModel):
    answer: str
    recommendation: Recommendation
    claims: list[ResearchClaim]


class Claim(BaseModel):
    id: str
    text: str
    subject: str
    category: ClaimCategory
    material: bool
    evidence_ids: list[str] = Field(default_factory=list)


class BaselineScore(BaseModel):
    alignment_score: int = Field(ge=0, le=100)
    material_claims: int = Field(ge=0)
    supported_claims: int = Field(ge=0)
    unsupported_claims: int = Field(ge=0)
    clean_evidence_records: int = Field(ge=0)
    incomplete_evidence_records: int = Field(ge=0)


class ClaimAudit(BaseModel):
    claim_id: str
    verdict: AuditVerdict
    failure_types: list[FailureType] = Field(default_factory=list)
    explanation: str
    verification_evidence_ids: list[str] = Field(default_factory=list)


class AuditArtifact(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    run_id: str
    question: str
    created_at: datetime
    claims: list[ClaimAudit]


class LearnedRule(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    trigger: FailureType
    failure: str
    rule: str
    behaviors: list[str] = Field(default_factory=list, max_length=2)


class GitHubMemoryReference(BaseModel):
    memory_source: Literal["github_via_one"] = "github_via_one"
    issue_number: int
    issue_url: str | None = None
    issue_title: str
    retrieved_rule: str


class LearningArtifact(BaseModel):
    learned: LearnedRule
    memory: GitHubMemoryReference


class AnswerAlignmentScore(BaseModel):
    alignment_score: int = Field(ge=0, le=100)
    material_claims: int = Field(ge=0)
    verified_claims: int = Field(ge=0)
    weak_claims: int = Field(ge=0)
    conflicted_claims: int = Field(ge=0)
    unsupported_claims: int = Field(ge=0)
    supported_claims: int = Field(ge=0)
    clean_evidence_records: int = Field(ge=0)


class AnswerArtifact(BaseModel):
    text: str
    recommendation: Recommendation


class CleanDataSummary(BaseModel):
    valid_records: int
    incomplete_records: int
    invalid_records: int


class RuntimeSummary(BaseModel):
    orchestrator: str = "CrewAI"
    research: str = "You.com Research API"
    retrieval: str = "You.com Search API"
    scoring: str = "Daytona"


class RunArtifact(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    run_id: str = "run_1"
    question: str
    created_at: datetime
    answer: AnswerArtifact
    claims: list[Claim]
    evidence: list[EvidenceRecord]
    clean_data: CleanDataSummary
    baseline_score: BaselineScore
    evidence_validations: list[EvidenceValidation] = Field(default_factory=list)
    answer_alignment: AnswerAlignmentScore | None = None
    runtime: RuntimeSummary = Field(default_factory=RuntimeSummary)


class ComparisonRun(BaseModel):
    alignment_score: int = Field(ge=0, le=100)
    recommendation: Recommendation


class ComparisonLearning(BaseModel):
    trigger: FailureType
    rule: str
    persisted_via: Literal["one"] = "one"
    system: Literal["github"] = "github"
    issue_number: int
    issue_url: str | None = None


class ComparisonArtifact(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    question: str
    run_1: ComparisonRun
    learning: ComparisonLearning
    run_2: ComparisonRun
    delta: int
    status: Literal["improved", "unchanged", "regressed"]
