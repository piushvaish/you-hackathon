"""Deterministic selection and serialization of one reusable research lesson."""

from __future__ import annotations

import re

from .models import AuditArtifact, AuditVerdict, Claim, FailureType, LearnedRule


LEARNING_PRIORITY: tuple[FailureType, ...] = (
    FailureType.UNSUPPORTED_COMPARISON,
    FailureType.CONFLICTING_EVIDENCE,
    FailureType.COMPETITOR_CLAIM_NOT_INDEPENDENTLY_VERIFIED,
    FailureType.MISSING_PRIMARY_VERIFICATION,
    FailureType.POSSIBLE_STALE_EVIDENCE,
    FailureType.ENDPOINT_PLATFORM_OVERGENERALIZATION,
    FailureType.INSUFFICIENT_EVIDENCE,
)

_RULES: dict[FailureType, tuple[str, list[str]]] = {
    FailureType.UNSUPPORTED_COMPARISON: (
        "For product comparisons, support every material comparative conclusion with current evidence for each product.",
        ["Separate sourced facts from inference.", "Withhold comparisons that lack evidence."],
    ),
    FailureType.CONFLICTING_EVIDENCE: (
        "When current sources conflict, surface the conflict and compare source scope and update dates before concluding.",
        ["Prefer current primary documentation.", "State unresolved disagreement explicitly."],
    ),
    FailureType.COMPETITOR_CLAIM_NOT_INDEPENDENTLY_VERIFIED: (
        "For product comparisons, independently verify material capability claims against current primary documentation from both vendors.",
        ["Check both vendors' primary documentation.", "Compare source and update dates when sources conflict."],
    ),
    FailureType.MISSING_PRIMARY_VERIFICATION: (
        "Verify material product-capability claims against the product's current primary documentation before concluding.",
        ["Seek an official source for each vendor.", "Label unverified assertions."],
    ),
    FailureType.POSSIBLE_STALE_EVIDENCE: (
        "Check publication or update dates for material product claims and re-verify stale evidence before relying on it.",
        ["Prefer current documentation.", "Disclose when freshness cannot be established."],
    ),
    FailureType.ENDPOINT_PLATFORM_OVERGENERALIZATION: (
        "Do not generalize an endpoint limitation to an entire platform without checking the platform's current capabilities.",
        ["Name the exact endpoint and scope.", "Check adjacent platform APIs before generalizing."],
    ),
    FailureType.INSUFFICIENT_EVIDENCE: (
        "Do not make a material comparison until enough current evidence exists to support it.",
        ["Retrieve additional evidence.", "Return insufficient evidence when verification remains incomplete."],
    ),
}


class NoLearningNeededError(RuntimeError):
    """Raised when a clean audit provides no honest failure to learn from."""


def select_learned_rule(audit: AuditArtifact) -> LearnedRule | None:
    observed: dict[FailureType, str] = {}
    for claim in audit.claims:
        if claim.verdict == AuditVerdict.VERIFIED.value:
            continue
        for raw_failure in claim.failure_types:
            failure = FailureType(raw_failure)
            observed.setdefault(failure, claim.explanation)
    for trigger in LEARNING_PRIORITY:
        if trigger in observed:
            rule, behaviors = _RULES[trigger]
            return LearnedRule(
                trigger=trigger,
                failure=observed[trigger],
                rule=rule,
                behaviors=behaviors,
            )
    return None


def issue_body(
    *, question: str, learned: LearnedRule, run_score: int, created_at: str
) -> str:
    behaviors = "\n".join(f"- {item}" for item in learned.behaviors)
    return f"""# Kojable Agent Learning

## Question

{question}

## Failure observed

{learned.failure}

## Learned rule

{learned.rule}

## Supporting behaviors

{behaviors}

## Trigger

{learned.trigger}

## Evidence

- run: run_1
- baseline alignment: {run_score}%
- created: {created_at}

## Status

Active research rule.
"""


def parse_learned_rule(body: str) -> str:
    match = re.search(
        r"(?ims)^## Learned rule\s*\r?\n+(.+?)(?=\r?\n+## |\Z)", body
    )
    if not match or not match.group(1).strip():
        raise ValueError("GitHub Issue did not contain a readable 'Learned rule' section.")
    return " ".join(match.group(1).strip().split())


def targeted_queries(
    audit: AuditArtifact, claims: list[Claim], learned: LearnedRule
) -> list[str]:
    failed_ids = {
        item.claim_id
        for item in audit.claims
        if learned.trigger in item.failure_types
    }
    queries = []
    for claim in claims:
        if claim.id in failed_ids:
            text = " ".join(claim.text.split())[:180]
            queries.append(f"current primary documentation verify: {text}")
        if len(queries) == 2:
            break
    return queries
