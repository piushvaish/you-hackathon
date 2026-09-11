import httpx
import pytest
from datetime import datetime, timezone

from kojable_agent.models import (
    AnswerArtifact,
    BaselineScore,
    Claim,
    CleanDataSummary,
    EvidenceRecord,
    RunArtifact,
    SourceType,
)
from kojable_agent.you_client import (
    MAX_AUDIT_INPUT_CHARS,
    RESEARCH_URL,
    SEARCH_URL,
    YouAPIError,
    YouClient,
)


def client_for(handler) -> YouClient:
    return YouClient("test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_search_normalizes_highlights() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == SEARCH_URL
        assert request.method == "POST"
        assert request.headers["X-API-Key"] == "test-key"
        body = __import__("json").loads(request.content)
        assert body["extraction"] == {"extraction_mode": "highlights"}
        return httpx.Response(
            200,
            json={
                "results": {
                    "web": [
                        {
                            "url": "https://docs.you.com/search",
                            "title": "Search",
                            "description": "API docs",
                            "page_age": "2026-09-01",
                            "contents": {"highlights": ["query-aware passage"]},
                        }
                    ],
                    "news": [],
                }
            },
        )

    result = client_for(handler).search("agent search")
    assert result[0].highlights == ["query-aware passage"]
    assert result[0].published_at == "2026-09-01"


def test_search_empty_results() -> None:
    client = client_for(lambda _request: httpx.Response(200, json={"results": {}}))
    assert client.search("nothing") == []


def test_research_parses_structured_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == RESEARCH_URL
        body = __import__("json").loads(request.content)
        assert body["research_effort"] == "standard"
        assert body["output_schema"]["additionalProperties"] is False
        return httpx.Response(
            200,
            json={
                "output": {
                    "content_type": "object",
                    "content": {
                        "answer": "It depends on the use case.",
                        "recommendation": "depends",
                        "claims": [
                            {
                                "claim": "Both expose web search APIs.",
                                "subject": "comparison",
                                "category": "search",
                                "material": True,
                            }
                        ],
                    },
                }
            },
        )

    answer = client_for(handler).research("Which is better?")
    assert answer.recommendation == "depends"
    assert answer.claims[0].material is True


@pytest.mark.parametrize(
    "payload",
    ["not-an-object", {"output": {"content": "not-structured"}}, {"output": {"content": {}}}],
)
def test_research_rejects_malformed_response(payload) -> None:
    client = client_for(lambda _request: httpx.Response(200, json=payload))
    with pytest.raises(YouAPIError, match="Malformed Research"):
        client.research("question")


def test_authentication_error_is_clear() -> None:
    client = client_for(lambda _request: httpx.Response(401, json={"detail": "bad"}))
    with pytest.raises(YouAPIError, match="authentication/permission"):
        client.search("question")


def test_audit_packet_is_bounded_for_large_live_evidence() -> None:
    evidence = [
        EvidenceRecord(
            id=f"e{index}",
            url=f"https://example.com/{index}/" + ("path" * 300),
            title="title " * 200,
            publisher_domain="example.com",
            retrieved_at=datetime.now(timezone.utc),
            published_at="2026-09-01",
            highlights=["evidence " * 2_000 for _ in range(4)],
            source_type=SourceType.INDEPENDENT,
        )
        for index in range(30)
    ]
    claims = [
        Claim(
            id=f"c{index}",
            text="material comparison " * 200,
            subject="comparison",
            category="other",
            material=True,
            evidence_ids=[f"e{index}"],
        )
        for index in range(9)
    ]
    run = RunArtifact(
        question="Which is better?",
        created_at=datetime.now(timezone.utc),
        answer=AnswerArtifact(text="answer " * 20_000, recommendation="depends"),
        claims=claims,
        evidence=evidence,
        clean_data=CleanDataSummary(
            valid_records=30, incomplete_records=0, invalid_records=0
        ),
        baseline_score=BaselineScore(
            alignment_score=100,
            material_claims=9,
            supported_claims=9,
            unsupported_claims=0,
            clean_evidence_records=30,
            incomplete_evidence_records=0,
        ),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = __import__("json").loads(request.content)
        assert len(body["input"]) <= MAX_AUDIT_INPUT_CHARS
        assert body["input"].count('"claim_id"') == 0
        return httpx.Response(
            200,
            json={
                "output": {
                    "content": {
                        "claims": [
                            {
                                "claim_id": f"c{index}",
                                "verdict": "verified",
                                "failure_types": [],
                                "explanation": "Verified.",
                                "verification_evidence_ids": [f"e{index}"],
                            }
                            for index in range(8)
                        ]
                    }
                }
            },
        )

    result = client_for(handler).audit(run)
    assert len(result) == 8
