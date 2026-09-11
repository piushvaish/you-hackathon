"""Read-only readiness check for One-managed GitHub memory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .one_client import OneClient, OneError, access_allows_issue_write


@dataclass(frozen=True)
class OneReadiness:
    cli_available: bool
    authenticated: bool
    github_connected: bool
    github_write_access: bool = False


def check_one_readiness(
    root: Path, *, one_secret: str | None = None, timeout: float = 10.0
) -> OneReadiness:
    one = OneClient(root, one_secret=one_secret, timeout=timeout)
    if not one.cli_available:
        return OneReadiness(False, False, False, False)
    try:
        connections = one.list_connections("github")
    except OneError:
        return OneReadiness(True, False, False, False)
    github = next(
        (
            item
            for item in connections
            if item.platform.lower() == "github"
            and item.state.lower() in {"operational", "connected", "active", "ready"}
        ),
        None,
    )
    if github is None:
        return OneReadiness(True, True, False, False)
    write_access = access_allows_issue_write(github)
    try:
        write_access = write_access or bool(one.search_actions("github", "create issue"))
    except OneError:
        pass
    return OneReadiness(True, True, True, write_access)
