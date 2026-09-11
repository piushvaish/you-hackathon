from datetime import datetime, timezone

from kojable_agent.models import CleanDataStatus, EvidenceRecord, SourceType
from kojable_agent.provenance import classify_source, validate_evidence


def record(**overrides) -> EvidenceRecord:
    values = {
        "id": "ev_1",
        "url": "https://docs.you.com/search",
        "title": "Search docs",
        "publisher_domain": "docs.you.com",
        "retrieved_at": datetime.now(timezone.utc),
        "published_at": "2026-09-01",
        "highlights": ["Search API evidence"],
        "description": None,
        "source_type": SourceType.PRIMARY,
    }
    values.update(overrides)
    return EvidenceRecord(**values)


def test_primary_and_competitor_classification() -> None:
    assert classify_source("docs.you.com", "you.com") == SourceType.PRIMARY
    assert classify_source("exa.ai", "you.com") == SourceType.COMPETITOR
    assert classify_source("you.com", "exa") == SourceType.COMPETITOR


def test_missing_publication_date_is_incomplete_not_invalid() -> None:
    result = validate_evidence(record(published_at=None))
    assert result.status == CleanDataStatus.INCOMPLETE
    assert result.reasons == ["publication date unavailable"]


def test_complete_record_is_valid() -> None:
    assert validate_evidence(record()).status == CleanDataStatus.VALID


def test_missing_required_provenance_is_invalid() -> None:
    result = validate_evidence(record(highlights=[]))
    assert result.status == CleanDataStatus.INVALID
    assert "retrieved evidence text unavailable" in result.reasons
