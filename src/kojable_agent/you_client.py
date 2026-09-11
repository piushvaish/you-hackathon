"""Small, explicit clients for You.com Search and Research APIs."""

from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import ValidationError

from .models import ClaimAudit, ResearchAnswer, RunArtifact, SearchResult


SEARCH_URL = "https://ydc-index.io/v1/search"
RESEARCH_URL = "https://api.you.com/v1/research"
MAX_AUDIT_EVIDENCE = 12
MAX_AUDIT_INPUT_CHARS = 38_000


class YouAPIError(RuntimeError):
    """A safe, actionable You.com API failure."""


class YouClient:
    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 45.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("A You.com API key is required")
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(timeout=timeout)
        self._headers = {"X-API-Key": api_key, "Content-Type": "application/json"}

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def search(self, query: str, count: int = 10) -> list[SearchResult]:
        response = self._post(
            SEARCH_URL,
            {"query": query, "count": count, "extraction": {"extraction_mode": "highlights"}},
        )
        payload = _response_object(response, "Search")
        raw_results = payload.get("results", [])
        if raw_results in (None, []):
            return []
        if isinstance(raw_results, dict):
            items: list[Any] = []
            for result_type in ("web", "news"):
                group = raw_results.get(result_type, [])
                if not isinstance(group, list):
                    raise YouAPIError(f"Malformed Search response: results.{result_type} is not a list")
                items.extend(group)
        elif isinstance(raw_results, list):
            items = raw_results
        else:
            raise YouAPIError("Malformed Search response: results is not an object or list")

        normalized: list[SearchResult] = []
        for item in items:
            if not isinstance(item, dict):
                raise YouAPIError("Malformed Search response: result is not an object")
            url = item.get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            contents = item.get("contents") or {}
            if not isinstance(contents, dict):
                raise YouAPIError("Malformed Search response: contents is not an object")
            highlights = contents.get("highlights") or []
            if not isinstance(highlights, list):
                raise YouAPIError("Malformed Search response: contents.highlights is not a list")
            normalized.append(
                SearchResult(
                    url=url,
                    title=_optional_string(item.get("title")) or "Untitled",
                    published_at=_publication_date(item),
                    highlights=[value for value in highlights if isinstance(value, str)],
                    description=_optional_string(item.get("description")),
                )
            )
        return normalized

    def research(self, question: str, learned_rule: str | None = None) -> ResearchAnswer:
        response = self._post(
            RESEARCH_URL,
            {
                "input": _research_prompt(question, learned_rule),
                "research_effort": "standard",
                "output_schema": research_output_schema(),
            },
        )
        payload = _response_object(response, "Research")
        output = payload.get("output")
        if not isinstance(output, dict):
            raise YouAPIError("Malformed Research response: output is not an object")
        content = output.get("content")
        if not isinstance(content, dict):
            raise YouAPIError("Malformed Research response: output.content is not an object")
        try:
            return ResearchAnswer.model_validate(content)
        except ValidationError as exc:
            raise YouAPIError(f"Malformed Research structured result: {exc}") from exc

    def audit(self, run: RunArtifact, *, max_claims: int = 8) -> list[ClaimAudit]:
        material = [claim for claim in run.claims if claim.material][:max_claims]
        referenced_ids = list(
            dict.fromkeys(
                evidence_id
                for claim in material
                for evidence_id in claim.evidence_ids
            )
        )
        by_id = {item.id: item for item in run.evidence}
        selected = [by_id[item] for item in referenced_ids if item in by_id]
        selected_ids = {item.id for item in selected}
        selected.extend(item for item in run.evidence if item.id not in selected_ids)
        selected = selected[:MAX_AUDIT_EVIDENCE]
        selected_ids = {item.id for item in selected}
        claims = [
            {
                "id": item.id,
                "text": _truncate(item.text, 800),
                "subject": _truncate(item.subject, 120),
                "category": item.category,
                "material": item.material,
                "evidence_ids": [
                    evidence_id
                    for evidence_id in item.evidence_ids
                    if evidence_id in selected_ids
                ],
            }
            for item in material
        ]
        evidence = [
            {
                "id": item.id,
                "url": _truncate(item.url, 600),
                "title": _truncate(item.title, 240),
                "publisher_domain": item.publisher_domain,
                "published_at": item.published_at,
                "source_type": item.source_type.value,
                "highlights": [_truncate(value, 600) for value in item.highlights[:2]],
            }
            for item in selected
        ]
        answer = _truncate(run.answer.text, 6_000)
        prompt = _audit_prompt(run.question, answer, claims, evidence)
        if len(prompt) > MAX_AUDIT_INPUT_CHARS:
            overflow = len(prompt) - MAX_AUDIT_INPUT_CHARS
            answer = _truncate(answer, max(1_000, len(answer) - overflow - 100))
            prompt = _audit_prompt(run.question, answer, claims, evidence)
        if len(prompt) > MAX_AUDIT_INPUT_CHARS:
            raise YouAPIError(
                "Audit input could not be bounded below the You.com 40,000-character limit."
            )
        response = self._post(
            RESEARCH_URL,
            {
                "input": prompt,
                "research_effort": "standard",
                "output_schema": audit_output_schema(),
            },
        )
        payload = _response_object(response, "Audit Research")
        output = payload.get("output")
        if not isinstance(output, dict) or not isinstance(output.get("content"), dict):
            raise YouAPIError("Malformed Audit Research response: output.content is not an object")
        claims = output["content"].get("claims")
        if not isinstance(claims, list):
            raise YouAPIError("Malformed Audit Research response: claims is not a list")
        try:
            return [ClaimAudit.model_validate(item) for item in claims]
        except ValidationError as exc:
            raise YouAPIError(f"Malformed Audit Research structured result: {exc}") from exc

    def _post(self, url: str, payload: dict[str, Any]) -> httpx.Response:
        try:
            response = self._client.post(url, headers=self._headers, json=payload)
        except httpx.TimeoutException as exc:
            raise YouAPIError(f"You.com request timed out: {url}") from exc
        except httpx.HTTPError as exc:
            raise YouAPIError(f"You.com request failed: {exc}") from exc

        if response.status_code in (401, 403):
            raise YouAPIError(
                f"You.com authentication/permission failed ({response.status_code}). "
                "Check YDC_API_KEY and its API scopes."
            )
        if response.status_code == 422:
            raise YouAPIError(f"You.com rejected the request schema (422): {_error_detail(response)}")
        if response.is_error:
            raise YouAPIError(
                f"You.com API returned HTTP {response.status_code}: {_error_detail(response)}"
            )
        return response


def research_output_schema() -> dict[str, Any]:
    claim_properties = {
        "claim": {"type": "string"},
        "subject": {"type": "string"},
        "category": {
            "type": "string",
            "enum": [
                "search",
                "extraction",
                "research",
                "freshness",
                "developer_experience",
                "pricing",
                "other",
            ],
        },
        "material": {"type": "boolean"},
    }
    return {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "recommendation": {
                "type": "string",
                "enum": ["you.com", "exa", "depends", "insufficient_evidence"],
            },
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": claim_properties,
                    "required": list(claim_properties),
                    "additionalProperties": False,
                },
            },
        },
        "required": ["answer", "recommendation", "claims"],
        "additionalProperties": False,
    }


def audit_output_schema() -> dict[str, Any]:
    properties = {
        "claim_id": {"type": "string"},
        "verdict": {
            "type": "string",
            "enum": ["verified", "weak", "conflicted", "unsupported"],
        },
        "failure_types": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "missing_primary_verification",
                    "competitor_claim_not_independently_verified",
                    "conflicting_evidence",
                    "possible_stale_evidence",
                    "endpoint_platform_overgeneralization",
                    "unsupported_comparison",
                    "insufficient_evidence",
                ],
            },
        },
        "explanation": {"type": "string"},
        "verification_evidence_ids": {
            "type": "array",
            "items": {"type": "string"},
        },
    }
    return {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                    "additionalProperties": False,
                },
            }
        },
        "required": ["claims"],
        "additionalProperties": False,
    }


def _research_prompt(question: str, learned_rule: str | None = None) -> str:
    learning = ""
    if learned_rule:
        learning = f'''\nPrevious research exposed an evidence-quality weakness.
Apply this research-method rule retrieved from external memory:

{learned_rule}

Do not favor either vendor because of this rule.\n'''
    return f'''Research and answer this question using current web evidence:

"{question}"
{learning}

Evaluate only meaningful developer-facing dimensions where evidence exists,
including web search/retrieval, extraction, research capabilities, freshness,
agent/developer usability, and pricing. Do not assume either platform is
universally better. If the appropriate answer depends on the use case, say so.
Separate material factual or comparative claims so they can be audited later.'''


def _audit_prompt(
    question: str,
    answer: str,
    claims: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> str:
    packet = json.dumps(
        {"question": question, "answer": answer, "claims": claims, "evidence": evidence},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f'''Audit only the material comparative claims in this research packet.
Use the supplied current web evidence and its provenance. For each claim, assess
support, primary-source verification, conflicting evidence, freshness, and
overgeneralization. A vendor assertion is not inherently false, but it is not
independent verification of a claim about a competitor. Do not infer that a
whole platform lacks a capability merely because one endpoint lacks it.

Return exactly one result per supplied claim. Use only the provided claim and
evidence IDs. A verified claim must have no failure types. Apply the fixed
verdict and failure vocabularies in the schema.

RESEARCH PACKET:
{packet}'''


def _response_object(response: httpx.Response, label: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise YouAPIError(f"Malformed {label} response: invalid JSON") from exc
    if not isinstance(payload, dict):
        raise YouAPIError(f"Malformed {label} response: root is not an object")
    return payload


def _optional_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _truncate(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _publication_date(item: dict[str, Any]) -> str | None:
    for key in ("published_at", "publishedAt", "page_age", "date"):
        value = _optional_string(item.get(key))
        if value:
            return value
    return None


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("message") or payload.get("error")
            if detail:
                return str(detail)[:500]
    except ValueError:
        pass
    return response.text[:500] or "no response detail"
