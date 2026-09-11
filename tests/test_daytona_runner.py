from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from kojable_agent.daytona_runner import DaytonaRunner, DaytonaScoringError
from kojable_agent.models import (
    AuditVerdict,
    Claim,
    ClaimAudit,
    CleanDataStatus,
    EvidenceRecord,
    EvidenceValidation,
    SourceType,
)


def inputs():
    evidence = [
        EvidenceRecord(
            id="e1",
            url="https://example.com/e1",
            title="Evidence",
            publisher_domain="example.com",
            retrieved_at=datetime.now(timezone.utc),
            published_at="2026-01-01",
            highlights=["support"],
            source_type=SourceType.INDEPENDENT,
        )
    ]
    claims = [
        Claim(
            id="c1",
            text="Claim",
            subject="comparison",
            category="other",
            material=True,
            evidence_ids=["e1"],
        )
    ]
    validations = [
        EvidenceValidation(evidence_id="e1", status=CleanDataStatus.VALID)
    ]
    return claims, evidence, validations


class FakeProcess:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.script = ""

    def code_run(self, script: str, timeout: int):
        self.script = script
        if self.fail:
            raise RuntimeError("execution failed")
        return SimpleNamespace(
            exit_code=0,
            result=(
                '{"alignment_score":100,"material_claims":1,'
                '"supported_claims":1,"unsupported_claims":0,'
                '"clean_evidence_records":1,"incomplete_evidence_records":0}'
            ),
        )


class FakeClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.process = FakeProcess(fail=fail)
        self.sandbox = SimpleNamespace(process=self.process)
        self.deleted = False

    def create(self):
        return self.sandbox

    def delete(self, sandbox, wait: bool):
        assert sandbox is self.sandbox
        assert wait is True
        self.deleted = True


class AlignmentProcess:
    def __init__(self) -> None:
        self.script = ""

    def code_run(self, script: str, timeout: int):
        self.script = script
        return SimpleNamespace(
            exit_code=0,
            result=(
                '{"alignment_score":100,"material_claims":1,'
                '"verified_claims":1,"weak_claims":0,"conflicted_claims":0,'
                '"unsupported_claims":0,"supported_claims":1,'
                '"clean_evidence_records":1}'
            ),
        )


class AlignmentClient(FakeClient):
    def __init__(self) -> None:
        self.process = AlignmentProcess()
        self.sandbox = SimpleNamespace(process=self.process)
        self.deleted = False


def test_daytona_payload_runs_and_returned_json_is_validated() -> None:
    fake = FakeClient()
    runner = DaytonaRunner("daytona-key", client_factory=lambda key: fake)
    result = runner.score(*inputs())
    assert result.alignment_score == 100
    assert "daytona-key" not in fake.process.script
    assert "base64.b64decode" in fake.process.script
    assert fake.deleted is True


def test_cleanup_is_attempted_after_execution_failure() -> None:
    fake = FakeClient(fail=True)
    runner = DaytonaRunner("daytona-key", client_factory=lambda key: fake)
    with pytest.raises(DaytonaScoringError, match="baseline run incomplete"):
        runner.score(*inputs())
    assert fake.deleted is True


def test_answer_alignment_uses_same_daytona_formula_and_cleans_up() -> None:
    claims, evidence, validations = inputs()
    audits = [
        ClaimAudit(
            claim_id="c1", verdict=AuditVerdict.VERIFIED, explanation="verified"
        )
    ]
    fake = AlignmentClient()
    runner = DaytonaRunner("daytona-key", client_factory=lambda key: fake)
    result = runner.score_alignment(claims, evidence, validations, audits)
    assert result.alignment_score == 100
    assert 'possible = len(material) * 3' in fake.process.script
    assert "daytona-key" not in fake.process.script
    assert fake.deleted is True
