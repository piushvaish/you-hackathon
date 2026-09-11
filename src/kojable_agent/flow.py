"""CrewAI Flows for the PR1 baseline and complete PR2 improvement loop."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel, Field

from .config import DEMO_QUESTION, SEARCH_QUERIES, Settings
from .daytona_runner import DaytonaRunner
from .audit import audit_run, weakness_count
from .github_memory import CreatedIssue, GitHubMemory
from .learning import (
    NoLearningNeededError,
    issue_body,
    select_learned_rule,
    targeted_queries,
)
from .models import (
    AnswerAlignmentScore,
    AuditArtifact,
    BaselineScore,
    Claim,
    CleanDataStatus,
    CleanDataSummary,
    EvidenceRecord,
    EvidenceValidation,
    ResearchAnswer,
    RunArtifact,
    AnswerArtifact,
    ComparisonArtifact,
    ComparisonLearning,
    ComparisonRun,
    GitHubMemoryReference,
    LearnedRule,
    LearningArtifact,
)
from .one_client import OneClient
from .provenance import link_claims_to_evidence, normalize_evidence, validate_evidence
from .scoring import comparison_status, score_baseline
from .you_client import YouClient


Progress = Callable[[str], None]


class AlignmentState(BaseModel):
    question: str = DEMO_QUESTION
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    research_answer: ResearchAnswer | None = None
    claims: list[Claim] = Field(default_factory=list)
    validations: list[EvidenceValidation] = Field(default_factory=list)
    baseline_score: BaselineScore | None = None
    artifact: RunArtifact | None = None


class AlignmentFlow(Flow[AlignmentState]):
    """CrewAI is the real event-driven orchestration layer for PR1."""

    def __init__(
        self,
        settings: Settings,
        *,
        you_client: YouClient | None = None,
        daytona_runner: DaytonaRunner | None = None,
        output_path: Path | None = None,
        progress: Progress | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.you_client = you_client or YouClient(settings.ydc_api_key or "")
        self.daytona_runner = daytona_runner or DaytonaRunner(settings.daytona_api_key or "")
        self.output_path = output_path or settings.output_path
        self.progress = progress or (lambda _message: None)
        self.stage_order: list[str] = []

    @start()
    def retrieve(self) -> int:
        self.stage_order.append("retrieve")
        self.progress("[1/5] Retrieving live evidence with You.com Search...")
        records: dict[str, EvidenceRecord] = {}
        retrieved_at = datetime.now(timezone.utc)
        for query, subject in SEARCH_QUERIES:
            for result in self.you_client.search(query):
                record = normalize_evidence(
                    result, retrieved_at=retrieved_at, subject=subject
                )
                records.setdefault(record.id, record)
        self.state.evidence = list(records.values())
        self.progress(f"      {len(self.state.evidence)} evidence records")
        return len(self.state.evidence)

    @listen(retrieve)
    def research(self) -> int:
        self.stage_order.append("research")
        self.progress("[2/5] Researching baseline answer with You.com...")
        self.state.research_answer = self.you_client.research(self.state.question)
        material = sum(claim.material for claim in self.state.research_answer.claims)
        self.progress(f"      {material} material claims")
        return material

    @listen(research)
    def normalize(self) -> int:
        self.stage_order.append("normalize")
        assert self.state.research_answer is not None
        self.state.claims = link_claims_to_evidence(
            self.state.research_answer.claims, self.state.evidence
        )
        return len(self.state.claims)

    @listen(normalize)
    def validate_provenance(self) -> CleanDataSummary:
        self.stage_order.append("validate")
        self.progress("[3/5] Applying Clean Data provenance checks...")
        self.state.validations = [validate_evidence(item) for item in self.state.evidence]
        summary = CleanDataSummary(
            valid_records=_status_count(self.state.validations, CleanDataStatus.VALID),
            incomplete_records=_status_count(
                self.state.validations, CleanDataStatus.INCOMPLETE
            ),
            invalid_records=_status_count(self.state.validations, CleanDataStatus.INVALID),
        )
        self.progress(f"      {summary.valid_records} valid")
        self.progress(f"      {summary.incomplete_records} incomplete")
        self.progress(f"      {summary.invalid_records} invalid")
        return summary

    @listen(validate_provenance)
    def score(self) -> BaselineScore:
        self.stage_order.append("score")
        self.progress("[4/5] Measuring inside Daytona...")
        self.state.baseline_score = self.daytona_runner.score(
            self.state.claims, self.state.evidence, self.state.validations
        )
        self.progress(
            "      Baseline Evidence Alignment: "
            f"{self.state.baseline_score.alignment_score}%"
        )
        return self.state.baseline_score

    @listen(score)
    def persist(self) -> RunArtifact:
        self.stage_order.append("persist")
        self.progress("[5/5] Saving baseline...")
        assert self.state.research_answer is not None
        assert self.state.baseline_score is not None
        summary = CleanDataSummary(
            valid_records=_status_count(self.state.validations, CleanDataStatus.VALID),
            incomplete_records=_status_count(
                self.state.validations, CleanDataStatus.INCOMPLETE
            ),
            invalid_records=_status_count(self.state.validations, CleanDataStatus.INVALID),
        )
        artifact = RunArtifact(
            question=self.state.question,
            created_at=self.state.created_at,
            answer=AnswerArtifact(
                text=self.state.research_answer.answer,
                recommendation=self.state.research_answer.recommendation,
            ),
            claims=self.state.claims,
            evidence=self.state.evidence,
            clean_data=summary,
            baseline_score=self.state.baseline_score,
        )
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.output_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(artifact.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.output_path)
        self.state.artifact = artifact
        try:
            shown_path = self.output_path.relative_to(self.settings.root)
        except ValueError:
            shown_path = self.output_path
        self.progress(f"      {shown_path}")
        return artifact


def _status_count(
    validations: list[EvidenceValidation], status: CleanDataStatus
) -> int:
    return sum(item.status == status for item in validations)


def _loop_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class ImprovementState(BaseModel):
    question: str = DEMO_QUESTION
    loop_run_id: str = Field(default_factory=_loop_run_id)
    run_1: RunArtifact | None = None
    validations_1: list[EvidenceValidation] = Field(default_factory=list)
    audit_1: AuditArtifact | None = None
    score_1: AnswerAlignmentScore | None = None
    learned: LearnedRule | None = None
    memory: GitHubMemoryReference | None = None
    created_issue_number: int | None = None
    created_issue_title: str | None = None
    created_issue_url: str | None = None
    run_2: RunArtifact | None = None
    validations_2: list[EvidenceValidation] = Field(default_factory=list)
    audit_2: AuditArtifact | None = None
    score_2: AnswerAlignmentScore | None = None
    comparison: ComparisonArtifact | None = None


class ImprovementFlow(Flow[ImprovementState]):
    """Full self-improving loop, with GitHub-through-One as authoritative memory."""

    def __init__(
        self,
        settings: Settings,
        *,
        you_client: YouClient | None = None,
        daytona_runner: DaytonaRunner | None = None,
        one_client: OneClient | None = None,
        github_memory: GitHubMemory | None = None,
        data_directory: Path | None = None,
        progress: Progress | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.you_client = you_client or YouClient(settings.ydc_api_key or "")
        self.daytona_runner = daytona_runner or DaytonaRunner(
            settings.daytona_api_key or ""
        )
        self.one_client = one_client or OneClient(
            settings.root, one_secret=settings.one_secret
        )
        self.github_memory = github_memory
        self.data_directory = data_directory or settings.data_directory
        self.progress = progress or (lambda _message: None)
        self.stage_order: list[str] = []
        self._created_issue: CreatedIssue | None = None

    @start()
    def baseline(self) -> RunArtifact:
        self.stage_order.append("baseline")
        self.progress("RUN 1 — researching with You.com...")
        run, validations = self._research_run("run_1")
        self.state.run_1 = run
        self.state.validations_1 = validations
        material = sum(claim.material for claim in run.claims)
        self.progress(f"      {material} material claims")
        return run

    @listen(baseline)
    def audit1(self) -> AuditArtifact:
        self.stage_order.append("audit1")
        self.progress("Auditing Run 1 evidence...")
        assert self.state.run_1 is not None
        self.state.audit_1 = audit_run(self.you_client, self.state.run_1)
        self.progress(f"      {weakness_count(self.state.audit_1)} weaknesses")
        return self.state.audit_1

    @listen(audit1)
    def score1(self) -> AnswerAlignmentScore:
        self.stage_order.append("score1")
        self.progress("Scoring Run 1 in Daytona...")
        assert self.state.run_1 is not None and self.state.audit_1 is not None
        self.state.score_1 = self.daytona_runner.score_alignment(
            self.state.run_1.claims,
            self.state.run_1.evidence,
            self.state.validations_1,
            self.state.audit_1.claims,
        )
        self.state.run_1 = self.state.run_1.model_copy(
            update={"answer_alignment": self.state.score_1}
        )
        self.progress(f"      Answer Alignment: {self.state.score_1.alignment_score}%")
        return self.state.score_1

    @listen(score1)
    def learn(self) -> LearnedRule:
        self.stage_order.append("learn")
        assert self.state.audit_1 is not None
        learned = select_learned_rule(self.state.audit_1)
        if learned is None:
            raise NoLearningNeededError(
                "Run 1 was already strongly aligned; no material evidence failure was "
                "found, so the agent did not manufacture a learned rule."
            )
        self.state.learned = learned
        self.progress(f"Learning trigger: {learned.trigger}")
        self.progress(f"I learned: {learned.rule}")
        return learned

    @listen(learn)
    def persist_learning(self) -> int:
        self.stage_order.append("persist")
        self.progress("Persisting learning to GitHub through One...")
        assert self.state.learned is not None and self.state.score_1 is not None
        connection = self.one_client.github_connection()
        if self.github_memory is None:
            self.github_memory = GitHubMemory(self.one_client, connection)
        pending = _load_pending_learning(self.data_directory / "learning.json")
        if pending is not None:
            self.state.learned, self._created_issue = pending
            self.state.created_issue_number = self._created_issue.number
            self.state.created_issue_title = self._created_issue.title
            self.state.created_issue_url = self._created_issue.url
            self.progress(
                f"      Reusing pending GitHub issue #{self._created_issue.number}"
            )
            return self._created_issue.number
        title = f"Kojable Agent Learning — {self.state.loop_run_id}"
        body = issue_body(
            question=self.state.question,
            learned=self.state.learned,
            run_score=self.state.score_1.alignment_score,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._created_issue = self.github_memory.create_issue(title=title, body=body)
        self.state.created_issue_number = self._created_issue.number
        self.state.created_issue_title = self._created_issue.title
        self.state.created_issue_url = self._created_issue.url
        _write_json(
            self.data_directory / "learning.json",
            {
                "learned": self.state.learned.model_dump(mode="json"),
                "memory": {
                    "memory_source": "github_via_one",
                    "issue_number": self._created_issue.number,
                    "issue_url": self._created_issue.url,
                    "issue_title": self._created_issue.title,
                    "retrieval_status": "pending",
                },
            },
        )
        self.progress(f"      GitHub issue #{self._created_issue.number} created")
        return self._created_issue.number

    @listen(persist_learning)
    def retrieve_learning(self) -> GitHubMemoryReference:
        self.stage_order.append("retrieve")
        self.progress("Reading learning back from GitHub through One...")
        assert self.github_memory is not None and self._created_issue is not None
        self.state.memory = self.github_memory.read_rule(self._created_issue)
        assert self.state.learned is not None
        _write_json(
            self.data_directory / "learning.json",
            LearningArtifact(
                learned=self.state.learned, memory=self.state.memory
            ).model_dump(mode="json"),
        )
        self.progress("      Memory retrieved ✓")
        return self.state.memory

    @listen(retrieve_learning)
    def run2(self) -> RunArtifact:
        self.stage_order.append("run2")
        self.progress("RUN 2 — applying the retrieved rule to the same question...")
        assert self.state.memory is not None
        assert self.state.audit_1 is not None and self.state.learned is not None
        assert self.state.run_1 is not None
        queries = targeted_queries(
            self.state.audit_1, self.state.run_1.claims, self.state.learned
        )
        run, validations = self._research_run(
            "run_2",
            learned_rule=self.state.memory.retrieved_rule,
            extra_queries=queries,
        )
        self.state.run_2 = run
        self.state.validations_2 = validations
        self.progress(f"      {sum(claim.material for claim in run.claims)} material claims")
        return run

    @listen(run2)
    def audit2(self) -> AuditArtifact:
        self.stage_order.append("audit2")
        self.progress("Auditing Run 2 with the same criteria...")
        assert self.state.run_2 is not None
        self.state.audit_2 = audit_run(self.you_client, self.state.run_2)
        self.progress(f"      {weakness_count(self.state.audit_2)} weaknesses")
        return self.state.audit_2

    @listen(audit2)
    def score2(self) -> AnswerAlignmentScore:
        self.stage_order.append("score2")
        self.progress("Scoring Run 2 in Daytona...")
        assert self.state.run_2 is not None and self.state.audit_2 is not None
        self.state.score_2 = self.daytona_runner.score_alignment(
            self.state.run_2.claims,
            self.state.run_2.evidence,
            self.state.validations_2,
            self.state.audit_2.claims,
        )
        self.state.run_2 = self.state.run_2.model_copy(
            update={"answer_alignment": self.state.score_2}
        )
        self.progress(f"      Answer Alignment: {self.state.score_2.alignment_score}%")
        return self.state.score_2

    @listen(score2)
    def compare(self) -> ComparisonArtifact:
        self.stage_order.append("compare")
        assert self.state.run_1 is not None and self.state.run_2 is not None
        assert self.state.score_1 is not None and self.state.score_2 is not None
        assert self.state.learned is not None and self.state.memory is not None
        delta = self.state.score_2.alignment_score - self.state.score_1.alignment_score
        status = comparison_status(delta)
        self.state.comparison = ComparisonArtifact(
            question=self.state.question,
            run_1=ComparisonRun(
                alignment_score=self.state.score_1.alignment_score,
                recommendation=self.state.run_1.answer.recommendation,
            ),
            learning=ComparisonLearning(
                trigger=self.state.learned.trigger,
                rule=self.state.memory.retrieved_rule,
                issue_number=self.state.memory.issue_number,
                issue_url=self.state.memory.issue_url,
            ),
            run_2=ComparisonRun(
                alignment_score=self.state.score_2.alignment_score,
                recommendation=self.state.run_2.answer.recommendation,
            ),
            delta=delta,
            status=status,
        )
        return self.state.comparison

    @listen(compare)
    def persist_results(self) -> ComparisonArtifact:
        self.stage_order.append("save")
        assert self.state.run_1 is not None and self.state.audit_1 is not None
        assert self.state.run_2 is not None and self.state.audit_2 is not None
        assert self.state.comparison is not None
        _write_json(
            self.data_directory / "run_1.json",
            self.state.run_1.model_dump(mode="json"),
        )
        _write_json(
            self.data_directory / "audit_1.json",
            self.state.audit_1.model_dump(mode="json"),
        )
        _write_json(
            self.data_directory / "run_2.json",
            self.state.run_2.model_dump(mode="json"),
        )
        _write_json(
            self.data_directory / "audit_2.json",
            self.state.audit_2.model_dump(mode="json"),
        )
        _write_json(
            self.data_directory / "comparison.json",
            self.state.comparison.model_dump(mode="json"),
        )
        self.progress("Saved: data/comparison.json")
        return self.state.comparison

    def _research_run(
        self,
        run_id: str,
        *,
        learned_rule: str | None = None,
        extra_queries: list[str] | None = None,
    ) -> tuple[RunArtifact, list[EvidenceValidation]]:
        records: dict[str, EvidenceRecord] = {}
        retrieved_at = datetime.now(timezone.utc)
        queries = list(SEARCH_QUERIES) + [
            (query, "targeted_verification") for query in (extra_queries or [])
        ]
        for query, subject in queries:
            for result in self.you_client.search(query):
                record = normalize_evidence(
                    result, retrieved_at=retrieved_at, subject=subject
                )
                records.setdefault(record.id, record)
        evidence = list(records.values())
        answer = self.you_client.research(self.state.question, learned_rule)
        claims = link_claims_to_evidence(answer.claims, evidence)
        validations = [validate_evidence(item) for item in evidence]
        clean_data = CleanDataSummary(
            valid_records=_status_count(validations, CleanDataStatus.VALID),
            incomplete_records=_status_count(validations, CleanDataStatus.INCOMPLETE),
            invalid_records=_status_count(validations, CleanDataStatus.INVALID),
        )
        artifact = RunArtifact(
            run_id=run_id,
            question=self.state.question,
            created_at=datetime.now(timezone.utc),
            answer=AnswerArtifact(
                text=answer.answer, recommendation=answer.recommendation
            ),
            claims=claims,
            evidence=evidence,
            clean_data=clean_data,
            baseline_score=score_baseline(claims, evidence, validations),
            evidence_validations=validations,
        )
        return artifact, validations


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _load_pending_learning(
    path: Path,
) -> tuple[LearnedRule, CreatedIssue] | None:
    """Recover a created issue after a later stage failed in an earlier process."""
    if not path.exists():
        return None
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise OneError(
            "Existing data/learning.json could not be read safely; refusing to "
            "create a potentially duplicate GitHub issue."
        ) from exc
    if not isinstance(payload, dict):
        return None
    memory = payload.get("memory")
    if not isinstance(memory, dict) or memory.get("retrieval_status") != "pending":
        return None
    try:
        learned = LearnedRule.model_validate(payload["learned"])
        number = memory["issue_number"]
        title = memory["issue_title"]
        url = memory.get("issue_url")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise ValueError("invalid issue number")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("invalid issue title")
        if url is not None and not isinstance(url, str):
            raise ValueError("invalid issue URL")
    except (KeyError, TypeError, ValueError) as exc:
        raise OneError(
            "Pending GitHub memory metadata is invalid; refusing to create a "
            "potentially duplicate issue."
        ) from exc
    return learned, CreatedIssue(number=number, title=title, url=url)
