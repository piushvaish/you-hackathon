import os
from pathlib import Path

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")

from kojable_agent.config import DEMO_QUESTION, Settings
from kojable_agent.flow import AlignmentFlow
from kojable_agent.models import ResearchAnswer, ResearchClaim, SearchResult
from kojable_agent.scoring import score_baseline


class FakeYouClient:
    def search(self, query: str, count: int = 10) -> list[SearchResult]:
        slug = "you" if query.startswith("You.com") else "exa"
        return [
            SearchResult(
                url=f"https://{slug}.example.com/docs",
                title="Web search API freshness",
                published_at="2026-09-01",
                highlights=["Web search API provides fresh indexed results"],
            )
        ]

    def research(self, question: str) -> ResearchAnswer:
        assert question == DEMO_QUESTION
        return ResearchAnswer(
            answer="The better fit depends on the use case.",
            recommendation="depends",
            claims=[
                ResearchClaim(
                    claim="Both provide web search API results.",
                    subject="comparison",
                    category="search",
                    material=True,
                )
            ],
        )


class FakeDaytonaRunner:
    def score(self, claims, evidence, validations):
        return score_baseline(claims, evidence, validations)


def test_flow_stage_order_and_persistence(tmp_path: Path) -> None:
    settings = Settings(
        root=tmp_path, ydc_api_key="you-key", daytona_api_key="daytona-key"
    )
    output = tmp_path / "data" / "run_1.json"
    flow = AlignmentFlow(
        settings,
        you_client=FakeYouClient(),
        daytona_runner=FakeDaytonaRunner(),
        output_path=output,
    )
    artifact = flow.kickoff()
    assert flow.stage_order == [
        "retrieve",
        "research",
        "normalize",
        "validate",
        "score",
        "persist",
    ]
    assert artifact.question == DEMO_QUESTION
    assert artifact.answer.recommendation == "depends"
    assert artifact.runtime.orchestrator == "CrewAI"
    assert output.is_file()
