"""Centralized machine-readable One CLI integration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class OneError(RuntimeError):
    """Actionable One failure that never includes credentials."""


@dataclass(frozen=True)
class OneConnection:
    platform: str
    connection_key: str
    state: str
    access: Any


@dataclass(frozen=True)
class OneAction:
    action_id: str
    name: str
    method: str | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class ActionArguments:
    data: dict[str, Any]
    path_variables: dict[str, Any]
    query_parameters: dict[str, Any]


Runner = Callable[..., subprocess.CompletedProcess[str]]


class OneClient:
    def __init__(
        self,
        root: Path,
        *,
        one_secret: str | None = None,
        executable: str | None = None,
        runner: Runner = subprocess.run,
        timeout: float = 20.0,
    ) -> None:
        self.root = root
        self.one_secret = one_secret
        self.executable = executable or shutil.which("one")
        self.runner = runner
        self.timeout = timeout
        self._documented_actions: set[tuple[str, str]] = set()

    @property
    def cli_available(self) -> bool:
        return bool(self.executable)

    def list_connections(self, search: str = "github") -> list[OneConnection]:
        payload = self._call(["list", "--search", search])
        items = _object_list(payload, ("connections", "integrations", "items", "data"))
        connections = []
        for item in items:
            platform = _platform_name(item)
            key = _first_string(item, "connectionKey", "connection_key", "key")
            state = _first_string(item, "state", "status") or (
                "connected" if item.get("connected") is True else ""
            )
            if platform and key:
                connections.append(
                    OneConnection(
                        platform=platform,
                        connection_key=key,
                        state=state,
                        access=item.get("accessPolicy", item.get("access", item.get("policy"))),
                    )
                )
        return connections

    def github_connection(self) -> OneConnection:
        ready_states = {"operational", "connected", "active", "ready"}
        for connection in self.list_connections("github"):
            if (
                connection.platform.lower() == "github"
                and connection.state.lower() in ready_states
            ):
                return connection
        raise OneError("GitHub is not connected through One.\n\nRun:\none add github")

    def search_actions(self, platform: str, query: str) -> list[OneAction]:
        payload = self._call(["actions", "search", platform, query, "-t", "execute"])
        items = _object_list(payload, ("actions", "results", "items", "data"))
        actions = []
        for item in items:
            action_id = _first_string(item, "actionId", "action_id", "id", "key")
            name = _first_string(item, "name", "title", "description") or ""
            method = _first_string(item, "method", "httpMethod", "http_method")
            if action_id:
                actions.append(OneAction(action_id, name, method, item))
        return actions

    def select_action(
        self,
        platform: str,
        query: str,
        *,
        method: str | None = None,
        fallback_queries: tuple[str, ...] = (),
    ) -> OneAction:
        for candidate_query in (query, *fallback_queries):
            actions = self.search_actions(platform, candidate_query)
            if method:
                actions = [
                    action
                    for action in actions
                    if action.method is None
                    or action.method.lower() == method.lower()
                ]
            if not actions:
                continue
            wanted = {
                word for word in candidate_query.lower().split() if len(word) > 2
            }

            def rank(action: OneAction) -> tuple[int, int]:
                name_words = {
                    word.strip(".,:;()[]") for word in action.name.lower().split()
                }
                haystack = f"{action.name} {json.dumps(action.raw)}".lower()
                word_score = sum(word in haystack for word in wanted)
                specificity = -len(name_words - wanted)
                return word_score, specificity

            return max(actions, key=rank)
        raise OneError(f"One found no executable {platform} action for '{query}'.")

    def get_action_knowledge(self, platform: str, action_id: str) -> dict[str, Any]:
        payload = self._call(["actions", "knowledge", platform, action_id])
        if not isinstance(payload, dict):
            raise OneError("One action knowledge was not a JSON object.")
        self._documented_actions.add((platform.lower(), action_id))
        return payload

    def execute_action(
        self,
        platform: str,
        action_id: str,
        connection_key: str,
        arguments: ActionArguments,
    ) -> Any:
        if (platform.lower(), action_id) not in self._documented_actions:
            raise OneError(
                "Refusing to execute a One action before reading its knowledge."
            )
        command = ["actions", "execute", platform, action_id, connection_key]
        if arguments.data:
            command.extend(["-d", json.dumps(arguments.data, separators=(",", ":"))])
        if arguments.path_variables:
            command.extend(
                [
                    "--path-vars",
                    json.dumps(arguments.path_variables, separators=(",", ":")),
                ]
            )
        if arguments.query_parameters:
            command.extend(
                [
                    "--query-params",
                    json.dumps(arguments.query_parameters, separators=(",", ":")),
                ]
            )
        return self._call(command)

    def _call(self, arguments: list[str]) -> Any:
        if not self.executable:
            raise OneError(
                "One CLI is not installed.\n\nRun:\nnpm install -g @withone/cli\none init"
            )
        environment = os.environ.copy()
        environment["ONE_NO_AUTO_UPDATE"] = "1"
        if os.name == "nt" and "--use-system-ca" not in environment.get(
            "NODE_OPTIONS", ""
        ).split():
            environment["NODE_OPTIONS"] = (
                f'{environment.get("NODE_OPTIONS", "")} --use-system-ca'.strip()
            )
        if self.one_secret:
            environment["ONE_SECRET"] = self.one_secret
        try:
            completed = self.runner(
                [self.executable, "--agent", *arguments],
                cwd=self.root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise OneError("One CLI timed out. Check One connectivity and try again.") from exc
        except OSError as exc:
            raise OneError("One CLI could not be started. Reinstall @withone/cli.") from exc
        stdout = completed.stdout if isinstance(completed.stdout, str) else ""
        stderr = completed.stderr if isinstance(completed.stderr, str) else ""
        if completed.returncode != 0:
            detail = (stderr or stdout or "unknown error").strip()[:500]
            if self.one_secret:
                detail = detail.replace(self.one_secret, "[redacted]")
            raise OneError(
                f"One CLI command failed ({completed.returncode}): {detail}"
            )
        if not stdout.strip():
            raise OneError("One CLI returned no JSON output in --agent mode.")
        try:
            payload = json.loads(stdout)
        except ValueError as exc:
            raise OneError("One CLI returned malformed JSON in --agent mode.") from exc
        if isinstance(payload, dict) and payload.get("error"):
            raise OneError(f"One CLI reported an error: {str(payload['error'])[:500]}")
        return payload


def access_allows_issue_write(connection: OneConnection) -> bool:
    """Infer non-destructively from One's access metadata; never test-write."""
    if connection.access is None:
        return False
    text = json.dumps(connection.access).lower()
    return any(
        token in text
        for token in ('"full"', '"write"', '"admin"', '"post"', "create issue")
    )


def _object_list(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = _object_list(value, keys)
                if nested:
                    return nested
        if any(key in payload for key in ("actionId", "connectionKey")):
            return [payload]
    return []


def _first_string(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _platform_name(item: dict[str, Any]) -> str:
    direct = _first_string(item, "platform", "provider", "app", "name")
    if direct:
        return direct
    for key in ("platform", "provider", "app"):
        nested = item.get(key)
        if isinstance(nested, dict):
            value = _first_string(nested, "key", "slug", "name")
            if value:
                return value
    return ""
