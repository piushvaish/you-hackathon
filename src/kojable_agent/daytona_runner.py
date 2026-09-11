"""Execute the deterministic scorer inside an ephemeral Daytona sandbox."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any

from .models import (
    AnswerAlignmentScore,
    BaselineScore,
    Claim,
    ClaimAudit,
    EvidenceRecord,
    EvidenceValidation,
)
from .scoring import (
    alignment_scoring_payload,
    score_answer_alignment,
    score_baseline,
    scoring_payload,
)


class DaytonaScoringError(RuntimeError):
    """Raised when isolated scoring does not complete and validate."""


class DaytonaRunner:
    def __init__(
        self,
        api_key: str,
        *,
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.api_key = api_key
        self._client_factory = client_factory or _official_client

    def score(
        self,
        claims: list[Claim],
        evidence: list[EvidenceRecord],
        validations: list[EvidenceValidation],
    ) -> BaselineScore:
        if not self.api_key:
            raise DaytonaScoringError("Daytona unavailable — baseline run incomplete.")
        payload = scoring_payload(claims, evidence, validations)
        client = self._client_factory(self.api_key)
        sandbox = None
        primary_error: Exception | None = None
        try:
            sandbox = client.create()
            response = sandbox.process.code_run(build_scoring_script(payload), timeout=30)
            if getattr(response, "exit_code", 0) != 0:
                raise DaytonaScoringError(
                    f"Daytona scorer exited with code {response.exit_code}."
                )
            raw_output = getattr(response, "result", None)
            if not isinstance(raw_output, str):
                raise DaytonaScoringError("Daytona scorer returned no text result.")
            lines = [line for line in raw_output.splitlines() if line.strip()]
            if not lines:
                raise DaytonaScoringError("Daytona scorer returned an empty result.")
            score = BaselineScore.model_validate_json(lines[-1])
            expected = score_baseline(claims, evidence, validations)
            if score != expected:
                raise DaytonaScoringError(
                    "Daytona scorer result disagreed with the local deterministic reference."
                )
            return score
        except DaytonaScoringError as exc:
            primary_error = exc
            raise
        except Exception as exc:
            primary_error = exc
            raise DaytonaScoringError(
                f"Daytona unavailable — baseline run incomplete. {exc}"
            ) from exc
        finally:
            if sandbox is not None:
                try:
                    client.delete(sandbox, wait=True)
                except Exception as cleanup_error:
                    if primary_error is None:
                        raise DaytonaScoringError(
                            f"Daytona sandbox cleanup failed: {cleanup_error}"
                        ) from cleanup_error

    def score_alignment(
        self,
        claims: list[Claim],
        evidence: list[EvidenceRecord],
        validations: list[EvidenceValidation],
        audits: list[ClaimAudit],
    ) -> AnswerAlignmentScore:
        if not self.api_key:
            raise DaytonaScoringError("Daytona unavailable — alignment run incomplete.")
        payload = alignment_scoring_payload(claims, evidence, validations, audits)
        client = self._client_factory(self.api_key)
        sandbox = None
        primary_error: Exception | None = None
        try:
            sandbox = client.create()
            response = sandbox.process.code_run(
                build_alignment_scoring_script(payload), timeout=30
            )
            if getattr(response, "exit_code", 0) != 0:
                raise DaytonaScoringError(
                    f"Daytona scorer exited with code {response.exit_code}."
                )
            raw_output = getattr(response, "result", None)
            if not isinstance(raw_output, str):
                raise DaytonaScoringError("Daytona scorer returned no text result.")
            lines = [line for line in raw_output.splitlines() if line.strip()]
            if not lines:
                raise DaytonaScoringError("Daytona scorer returned an empty result.")
            score = AnswerAlignmentScore.model_validate_json(lines[-1])
            expected = score_answer_alignment(claims, evidence, validations, audits)
            if score != expected:
                raise DaytonaScoringError(
                    "Daytona scorer result disagreed with the local deterministic reference."
                )
            return score
        except DaytonaScoringError as exc:
            primary_error = exc
            raise
        except Exception as exc:
            primary_error = exc
            raise DaytonaScoringError(
                f"Daytona unavailable — alignment run incomplete. {exc}"
            ) from exc
        finally:
            if sandbox is not None:
                try:
                    client.delete(sandbox, wait=True)
                except Exception as cleanup_error:
                    if primary_error is None:
                        raise DaytonaScoringError(
                            f"Daytona sandbox cleanup failed: {cleanup_error}"
                        ) from cleanup_error


def build_scoring_script(payload: dict[str, Any]) -> str:
    encoded = base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return f'''import base64
import json
import math

payload = json.loads(base64.b64decode("{encoded}").decode("utf-8"))
material = [claim for claim in payload["claims"] if claim["material"]]
statuses = {{record["id"]: record["status"] for record in payload["evidence"]}}
supported = 0
clean_supported = 0
for claim in material:
    referenced = [item for item in claim["evidence_ids"] if item in statuses]
    supported += bool(referenced)
    clean_supported += any(statuses[item] == "valid" for item in referenced)
possible = len(material) * 2
earned = supported + clean_supported
score = math.floor((earned / possible * 100) + 0.5) if possible else 0
result = {{
    "alignment_score": score,
    "material_claims": len(material),
    "supported_claims": supported,
    "unsupported_claims": len(material) - supported,
    "clean_evidence_records": sum(value == "valid" for value in statuses.values()),
    "incomplete_evidence_records": sum(value == "incomplete" for value in statuses.values()),
}}
print(json.dumps(result, separators=(",", ":")))
'''


def build_alignment_scoring_script(payload: dict[str, Any]) -> str:
    encoded = base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return f'''import base64
import json
import math

payload = json.loads(base64.b64decode("{encoded}").decode("utf-8"))
material = [claim for claim in payload["claims"] if claim["material"]]
statuses = {{record["id"]: record["status"] for record in payload["evidence"]}}
verdicts = {{audit["claim_id"]: audit["verdict"] for audit in payload["audits"]}}
counts = {{"verified": 0, "weak": 0, "conflicted": 0, "unsupported": 0}}
supported = 0
clean_supported = 0
for claim in material:
    referenced = [item for item in claim["evidence_ids"] if item in statuses]
    supported += bool(referenced)
    clean_supported += any(statuses[item] == "valid" for item in referenced)
    verdict = verdicts.get(claim["id"], "unsupported")
    counts[verdict if verdict in counts else "unsupported"] += 1
earned = supported + clean_supported + counts["verified"]
possible = len(material) * 3
score = math.floor((earned / possible * 100) + 0.5) if possible else 0
result = {{
    "alignment_score": score,
    "material_claims": len(material),
    "verified_claims": counts["verified"],
    "weak_claims": counts["weak"],
    "conflicted_claims": counts["conflicted"],
    "unsupported_claims": counts["unsupported"],
    "supported_claims": supported,
    "clean_evidence_records": sum(value == "valid" for value in statuses.values()),
}}
print(json.dumps(result, separators=(",", ":")))
'''


def _official_client(api_key: str) -> Any:
    from daytona import Daytona, DaytonaConfig

    return Daytona(DaytonaConfig(api_key=api_key))
