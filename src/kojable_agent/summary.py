"""Read-only presentation of completed local comparisons."""

import re
import textwrap
from pathlib import Path

from .models import ComparisonArtifact, AuditArtifact


def _safe(value: str) -> str:
    value = re.sub(r"https?://\S+", "[URL omitted]", value)
    value = re.sub(r"(?i)(?:TRACE-|sk_|sk-|ghp_|github_pat_|live::)\S+", "[redacted]", value)
    value = re.sub(r"(?i)(?:\w*(?:api_key|secret|token)|authorization|access_code)\s*[:=]\s*\S+", "[redacted]", value)
    return "".join(c for c in value if c.isprintable() or c == "\n")


def _weaknesses(directory: Path, index: int) -> str:
    try:
        audit = AuditArtifact.model_validate_json(
            (directory / f"audit_{index}.json").read_text(encoding="utf-8")
        )
        return str(sum(item.verdict != "verified" for item in audit.claims))
    except (OSError, ValueError):
        return "unavailable"


def show_summary(directory: Path) -> int:
    path = directory / "comparison.json"
    if not path.exists():
        print("No completed comparison found.\n\nRun:\npython -m kojable_agent --loop")
        return 0
    try:
        result = ComparisonArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        delta = result.run_2.alignment_score - result.run_1.alignment_score
        status = "improved" if delta > 0 else "regressed" if delta < 0 else "unchanged"
        if result.delta != delta or result.status != status:
            raise ValueError("inconsistent comparison")
    except (OSError, ValueError):
        print("Saved comparison is invalid or unreadable. No summary displayed.")
        return 1
    print("KOJABLE — SELF-IMPROVING ANSWER ALIGNMENT\n")
    print(f"QUESTION\n{_safe(result.question)}\n")
    print(f"RUN 1\nAnswer Alignment       {result.run_1.alignment_score}%")
    print(f"Evidence weaknesses    {_weaknesses(directory, 1)}\n")
    print(f"LEARNED\nTrigger: {result.learning.trigger.value}\n")
    print(f"Rule:\n{textwrap.fill(_safe(result.learning.rule), width=68)}\n")
    print("Memory: GitHub via One (recorded in completed comparison)")
    url = result.learning.issue_url or ""
    if re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[0-9]+", url):
        print(url)
    print(f"\nRUN 2\nAnswer Alignment       {result.run_2.alignment_score}%")
    print(f"Evidence weaknesses    {_weaknesses(directory, 2)}\n")
    print(f"RESULT\n{result.run_1.alignment_score}% → {result.run_2.alignment_score}%")
    print(f"{delta:+d} percentage points\nSTATUS: {status.upper()}\n")
    print("The same buyer question was retried using research behavior learned\nfrom Run 1 and retrieved from an external system.")
    return 0
