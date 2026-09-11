"""Command-line entry point for the Kojable baseline and learning loop."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from dataclasses import dataclass

from .config import DEMO_QUESTION, ConfigurationError, Settings
from .daytona_runner import DaytonaScoringError
from .learning import NoLearningNeededError
from .one_client import OneError
from .one_preflight import check_one_readiness
from .you_client import YouAPIError, YouClient


@dataclass(frozen=True)
class Check:
    label: str
    ready: bool


def main(argv: list[str] | None = None) -> int:
    try:
        _configure_output()
        parser = argparse.ArgumentParser(description="Run the Kojable alignment agent")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--preflight", action="store_true", help="check setup only")
        mode.add_argument("--baseline", action="store_true", help="run the PR1 baseline")
        mode.add_argument("--loop", action="store_true", help="run the complete PR2 loop")
        mode.add_argument("--summary", action="store_true", help="show saved results offline")
        args = parser.parse_args(argv)
        if args.summary:
            from .config import repository_root
            from .summary import show_summary

            return show_summary(repository_root() / "data")
        settings = Settings.load(require_credentials=not args.preflight)
        if args.preflight:
            return run_preflight(settings)
        if args.loop:
            return run_loop(settings)
        return run_baseline(settings)
    except (
        ConfigurationError,
        YouAPIError,
        DaytonaScoringError,
        NoLearningNeededError,
        OneError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        return 1


def run_preflight(settings: Settings) -> int:
    one = check_one_readiness(settings.root, one_secret=settings.one_secret)
    crewai_ready = importlib.util.find_spec("crewai") is not None
    daytona_ready = importlib.util.find_spec("daytona") is not None
    checks = [
        Check("Python", (3, 11) <= sys.version_info[:2] < (3, 14)),
        Check("Root .env", (settings.root / ".env").is_file()),
        Check("YDC_API_KEY", bool(settings.ydc_api_key)),
        Check("DAYTONA_API_KEY", bool(settings.daytona_api_key)),
        Check("CrewAI", crewai_ready),
        Check("You.com", bool(settings.ydc_api_key)),
        Check("Daytona", bool(settings.daytona_api_key) and daytona_ready),
        Check("One CLI", one.cli_available),
        Check("One authentication", one.authenticated),
        Check("GitHub connection via One", one.github_connected),
        Check("GitHub write access", one.github_write_access),
    ]
    print("KOJABLE HACKATHON — PREFLIGHT\n")
    for check in checks:
        status = "✓" if check.ready else "NOT READY"
        print(f"{check.label:<30} {status}")
    if not one.cli_available:
        print("\nOne setup: npm install -g @withone/cli, then run: one init")
    elif one.authenticated and not one.github_connected:
        print("\nGitHub through One is required for PR2: one add github")
    return 0


def _configure_output() -> None:
    """Keep the documented Unicode console UI reliable on Windows terminals."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def run_baseline(settings: Settings) -> int:
    from .flow import AlignmentFlow

    print("KOJABLE — SELF-IMPROVING ANSWER ALIGNMENT\n")
    print("RUN 1 — BASELINE\n")
    print(f"Question:\n{DEMO_QUESTION}\n")
    client = YouClient(settings.ydc_api_key or "")
    try:
        artifact = AlignmentFlow(
            settings,
            you_client=client,
            progress=print,
        ).kickoff()
    finally:
        client.close()
    print(f"\nRecommendation:\n{artifact.answer.recommendation.upper()}\n")
    print("PR1 COMPLETE\n")
    print("Next:\nAudit → Learn → Persist → Retry")
    return 0


def run_loop(settings: Settings) -> int:
    from .flow import ImprovementFlow

    print("KOJABLE — SELF-IMPROVING ANSWER ALIGNMENT\n")
    print("QUESTION")
    print(f"{DEMO_QUESTION}\n")
    client = YouClient(settings.ydc_api_key or "")
    try:
        comparison = ImprovementFlow(
            settings,
            you_client=client,
            progress=print,
        ).kickoff()
    finally:
        client.close()
    sign = "+" if comparison.delta > 0 else ""
    print("\nRESULT")
    print(
        f"Run 1: {comparison.run_1.alignment_score}%\n"
        f"Run 2: {comparison.run_2.alignment_score}%\n"
        f"Delta: {sign}{comparison.delta}\n"
        f"Status: {comparison.status.upper()}"
    )
    if comparison.learning.issue_url:
        print(f"\nGitHub memory: {comparison.learning.issue_url}")
    else:
        print(f"\nGitHub memory: issue #{comparison.learning.issue_number}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
