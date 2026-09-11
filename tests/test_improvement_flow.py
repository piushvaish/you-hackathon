import os
import json
from pathlib import Path

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")

from kojable_agent.config import DEMO_QUESTION, Settings
from kojable_agent.flow import ImprovementFlow
from kojable_agent.github_memory import CreatedIssue
from kojable_agent.models import (
    AuditVerdict,
    ClaimAudit,
    FailureType,
    GitHubMemoryReference,
    ResearchAnswer,
    ResearchClaim,
    SearchResult,
)
from kojable_agent.one_client import OneConnection
from kojable_agent.scoring import score_answer_alignment


REMOTE_RULE = "Use the research rule retrieved from the GitHub Issue."


class FakeYouClient:
    def __init__(self):
        self.research_rules = []

    def search(self, query, count=10):
        return [
            SearchResult(
                url="https://docs.example.com/search",
                title="Current search documentation",
                published_at="2026-09-01",
                highlights=["Both products provide current search documentation"],
            )
        ]

    def research(self, question, learned_rule=None):
        assert question == DEMO_QUESTION
        self.research_rules.append(learned_rule)
        return ResearchAnswer(
            answer="It depends on the use case.",
            recommendation="depends",
            claims=[
                ResearchClaim(
                    claim="Both products provide current search documentation",
                    subject="comparison",
                    category="search",
                    material=True,
                )
            ],
        )

    def audit(self, run, *, max_claims):
        if run.run_id == "run_1":
            return [
                ClaimAudit(
                    claim_id=run.claims[0].id,
                    verdict=AuditVerdict.WEAK,
                    failure_types=[
                        FailureType.COMPETITOR_CLAIM_NOT_INDEPENDENTLY_VERIFIED
                    ],
                    explanation="The competitor claim lacked independent verification.",
                )
            ]
        return [
            ClaimAudit(
                claim_id=run.claims[0].id,
                verdict=AuditVerdict.VERIFIED,
                explanation="Verified from the retrieved-rule research method.",
                verification_evidence_ids=run.claims[0].evidence_ids,
            )
        ]


class FakeDaytona:
    def __init__(self):
        self.calls = 0

    def score_alignment(self, claims, evidence, validations, audits):
        self.calls += 1
        return score_answer_alignment(claims, evidence, validations, audits)


class FakeOne:
    def github_connection(self):
        return OneConnection("github", "key", "connected", {"methods": ["POST"]})


class FakeMemory:
    def __init__(self):
        self.created_body = ""
        self.create_calls = 0

    def create_issue(self, *, title, body):
        self.create_calls += 1
        self.created_body = body
        return CreatedIssue(7, title, "https://github.com/piushvaish/you-hackathon/issues/7")

    def read_rule(self, issue):
        return GitHubMemoryReference(
            issue_number=issue.number,
            issue_url=issue.url,
            issue_title=issue.title,
            retrieved_rule=REMOTE_RULE,
        )


def test_complete_flow_order_and_external_rule_controls_run_2(tmp_path: Path) -> None:
    you = FakeYouClient()
    daytona = FakeDaytona()
    memory = FakeMemory()
    settings = Settings(
        root=tmp_path,
        ydc_api_key="you-key",
        daytona_api_key="daytona-key",
    )
    flow = ImprovementFlow(
        settings,
        you_client=you,
        daytona_runner=daytona,
        one_client=FakeOne(),
        github_memory=memory,
        data_directory=tmp_path / "data",
    )
    result = flow.kickoff()

    assert flow.stage_order == [
        "baseline",
        "audit1",
        "score1",
        "learn",
        "persist",
        "retrieve",
        "run2",
        "audit2",
        "score2",
        "compare",
        "save",
    ]
    assert you.research_rules == [None, REMOTE_RULE]
    assert REMOTE_RULE not in memory.created_body
    assert daytona.calls == 2
    assert result.delta > 0
    assert result.status == "improved"
    assert memory.create_calls == 1
    assert {path.name for path in (tmp_path / "data").iterdir()} == {
        "run_1.json",
        "audit_1.json",
        "learning.json",
        "run_2.json",
        "audit_2.json",
        "comparison.json",
    }


def test_retry_reuses_pending_github_issue_without_duplicate(tmp_path: Path) -> None:
    persisted_rule = {
        "trigger": "missing_primary_verification",
        "failure": "A material claim lacked primary verification.",
        "rule": "Verify material claims against current primary documentation.",
        "behaviors": ["Seek an official source."],
    }
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    (data_directory / "learning.json").write_text(
        json.dumps(
            {
                "learned": persisted_rule,
                "memory": {
                    "memory_source": "github_via_one",
                    "issue_number": 19,
                    "issue_url": "https://github.com/piushvaish/you-hackathon/issues/19",
                    "issue_title": "Kojable Agent Learning — prior-run",
                    "retrieval_status": "pending",
                },
            }
        ),
        encoding="utf-8",
    )
    you = FakeYouClient()
    memory = FakeMemory()
    flow = ImprovementFlow(
        Settings(
            root=tmp_path,
            ydc_api_key="you-key",
            daytona_api_key="daytona-key",
        ),
        you_client=you,
        daytona_runner=FakeDaytona(),
        one_client=FakeOne(),
        github_memory=memory,
        data_directory=data_directory,
    )

    flow.kickoff()

    assert memory.create_calls == 0
    assert flow.state.created_issue_number == 19
    assert flow.state.learned is not None
    assert flow.state.learned.rule == persisted_rule["rule"]
