"""GitHub Issue memory accessed exclusively through dynamically discovered One actions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .learning import parse_learned_rule
from .models import GitHubMemoryReference
from .one_client import ActionArguments, OneClient, OneConnection, OneError


GITHUB_OWNER = "piushvaish"
GITHUB_REPOSITORY = "you-hackathon"


@dataclass(frozen=True)
class CreatedIssue:
    number: int
    title: str
    url: str | None


@dataclass(frozen=True)
class _Parameter:
    name: str
    location: str


class GitHubMemory:
    def __init__(
        self,
        one: OneClient,
        connection: OneConnection,
        *,
        owner: str = GITHUB_OWNER,
        repository: str = GITHUB_REPOSITORY,
    ) -> None:
        self.one = one
        self.connection = connection
        self.owner = owner
        self.repository = repository
        self._created: CreatedIssue | None = None

    def create_issue(self, *, title: str, body: str) -> CreatedIssue:
        """Create at most once per memory instance, even if a later stage fails."""
        if self._created is not None:
            return self._created
        action = self.one.select_action("github", "create issue", method="post")
        knowledge = self.one.get_action_knowledge("github", action.action_id)
        _require_method(knowledge, "post")
        arguments = build_action_arguments(
            knowledge,
            {
                "owner": self.owner,
                "repository": self.repository,
                "title": title,
                "body": body,
            },
        )
        response = self.one.execute_action(
            "github", action.action_id, self.connection.connection_key, arguments
        )
        number = _integer_value(response, ("number", "issue_number", "issueNumber"))
        if number is None:
            raise OneError("GitHub create-issue response did not contain an issue number.")
        url = _string_value(response, ("html_url", "htmlUrl", "issue_url", "url"))
        returned_title = _string_value(response, ("title",)) or title
        self._created = CreatedIssue(number=number, title=returned_title, url=url)
        return self._created

    def read_rule(self, issue: CreatedIssue) -> GitHubMemoryReference:
        action = self.one.select_action(
            "github",
            "get issue",
            method="get",
            fallback_queries=("get a repository issue", "repository issue"),
        )
        knowledge = self.one.get_action_knowledge("github", action.action_id)
        _require_method(knowledge, "get")
        arguments = build_action_arguments(
            knowledge,
            {
                "owner": self.owner,
                "repository": self.repository,
                "issue_number": issue.number,
            },
        )
        try:
            response = self.one.execute_action(
                "github", action.action_id, self.connection.connection_key, arguments
            )
            body = _string_value(response, ("body",))
            if not body:
                raise OneError("GitHub get-issue response did not contain the issue body.")
            retrieved_rule = parse_learned_rule(body)
        except (OneError, ValueError) as exc:
            raise OneError(
                "External learning persistence succeeded, but memory retrieval failed. "
                "Run 2 aborted."
            ) from exc
        return GitHubMemoryReference(
            issue_number=issue.number,
            issue_url=issue.url,
            issue_title=issue.title,
            retrieved_rule=retrieved_rule,
        )


def build_action_arguments(
    knowledge: dict[str, Any], logical_values: dict[str, Any]
) -> ActionArguments:
    """Map logical values only to fields documented by One action knowledge."""
    parameters = _parameters_from_knowledge(knowledge)
    aliases = {
        "owner": ("owner", "organization", "org"),
        "repository": ("repo", "repository"),
        "title": ("title",),
        "body": ("body",),
        "issue_number": ("issue_number", "issuenumber", "number"),
    }
    data: dict[str, Any] = {}
    path: dict[str, Any] = {}
    query: dict[str, Any] = {}
    for logical_name, value in logical_values.items():
        documented = _select_parameter(parameters, aliases[logical_name])
        if documented is None:
            raise OneError(
                "One action knowledge did not document required GitHub field: "
                f"{logical_name}."
            )
        target = path if documented.location == "path" else query if documented.location == "query" else data
        target[documented.name] = value
    return ActionArguments(data=data, path_variables=path, query_parameters=query)


def _parameters_from_knowledge(knowledge: dict[str, Any]) -> list[_Parameter]:
    found: dict[str, _Parameter] = {}
    path_names: set[str] = set()

    def walk(node: Any, context: str | None = None) -> None:
        if isinstance(node, str):
            path_names.update(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", node))
            for parameter in _parameters_from_documentation(node):
                found.setdefault(parameter.name.lower(), parameter)
            return
        if isinstance(node, list):
            for item in node:
                walk(item, context)
            return
        if not isinstance(node, dict):
            return
        name = node.get("name")
        location = node.get("in") or node.get("location")
        if isinstance(name, str) and (isinstance(location, str) or context):
            normalized_location = (
                _normalize_location(location) if isinstance(location, str) else context
            )
            if normalized_location:
                found.setdefault(name.lower(), _Parameter(name, normalized_location))
        properties = node.get("properties")
        if isinstance(properties, dict):
            for property_name, schema in properties.items():
                if isinstance(property_name, str):
                    found.setdefault(
                        property_name.lower(),
                        _Parameter(property_name, context or "unknown"),
                    )
                walk(schema, context)
        for key, value in node.items():
            child_context = _context_for_key(key) or context
            normalized_key = re.sub(r"[^a-z]", "", key.lower())
            if normalized_key in {"parameters", "params", "arguments", "inputs"}:
                if isinstance(value, dict):
                    for field_name, schema in value.items():
                        if not isinstance(field_name, str) or not isinstance(schema, dict):
                            continue
                        raw_location = schema.get("in") or schema.get("location")
                        documented_location = (
                            _normalize_location(raw_location)
                            if isinstance(raw_location, str)
                            else child_context or "unknown"
                        )
                        if documented_location:
                            found.setdefault(
                                field_name.lower(),
                                _Parameter(field_name, documented_location),
                            )
            if child_context and isinstance(value, dict) and key != "properties":
                for field_name in value:
                    if isinstance(field_name, str) and field_name not in {
                        "type",
                        "required",
                        "properties",
                        "schema",
                        "description",
                    }:
                        found.setdefault(
                            field_name.lower(), _Parameter(field_name, child_context)
                        )
            walk(value, child_context)

    walk(knowledge)
    for name in path_names:
        existing = found.get(name.lower())
        found[name.lower()] = _Parameter(existing.name if existing else name, "path")
    return list(found.values())


def _parameters_from_documentation(documentation: str) -> list[_Parameter]:
    """Read input fields from One's Markdown action-knowledge format."""
    found: dict[str, _Parameter] = {}
    context: str | None = None
    for line in documentation.splitlines():
        heading = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", line)
        if heading:
            context = _documentation_heading_context(heading.group(1))
            continue
        if context is None:
            continue
        table_field = re.match(
            r"^\s*\|\s*`?([A-Za-z_][A-Za-z0-9_.-]*)`?\s*\|", line
        )
        bullet_field = re.match(
            r"^\s*[-*]\s+`([A-Za-z_][A-Za-z0-9_.-]*)`(?:\s|:|$)", line
        )
        match = table_field or bullet_field
        if not match:
            continue
        name = match.group(1)
        if name.lower() in {"parameter", "field", "name", "type"}:
            continue
        found.setdefault(name.lower(), _Parameter(name, context))
    return list(found.values())


def _documentation_heading_context(heading: str) -> str | None:
    normalized = re.sub(r"[^a-z]+", " ", heading.lower()).strip()
    if "path" in normalized and "parameter" in normalized:
        return "path"
    if "query" in normalized and "parameter" in normalized:
        return "query"
    if "request body" in normalized or "body field" in normalized:
        return "body"
    return None


def _context_for_key(key: str) -> str | None:
    normalized = re.sub(r"[^a-z]", "", key.lower())
    if normalized in {
        "path",
        "pathparams",
        "pathparameters",
        "pathvariables",
    }:
        return "path"
    if normalized in {"query", "queryparams", "queryparameters"}:
        return "query"
    if normalized in {
        "body",
        "data",
        "requestbody",
        "bodyparameters",
        "bodyparams",
        "dataparameters",
        "bodyschema",
        "inputschema",
        "requestschema",
    }:
        return "body"
    return None


def _normalize_location(value: str) -> str | None:
    normalized = value.lower().replace("_", "").replace("-", "")
    if "path" in normalized:
        return "path"
    if "query" in normalized:
        return "query"
    if normalized in {"body", "data", "requestbody"}:
        return "body"
    return None


def _select_parameter(
    parameters: list[_Parameter], aliases: tuple[str, ...]
) -> _Parameter | None:
    normalized_aliases = {item.lower().replace("_", "") for item in aliases}
    matches = [
        item
        for item in parameters
        if item.name.lower().replace("_", "") in normalized_aliases
    ]
    if not matches:
        return None
    matches.sort(key=lambda item: item.location == "unknown")
    selected = matches[0]
    if selected.location == "unknown":
        return _Parameter(selected.name, "body")
    return selected


def _walk_objects(value: Any):
    if isinstance(value, dict):
        preferred = ("response", "result", "data", "issue")
        for key in preferred:
            if key in value:
                yield from _walk_objects(value[key])
        yield value
        for key, child in value.items():
            if key not in preferred:
                yield from _walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_objects(child)


def _string_value(value: Any, keys: tuple[str, ...]) -> str | None:
    for item in _walk_objects(value):
        for key in keys:
            candidate = item.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return None


def _integer_value(value: Any, keys: tuple[str, ...]) -> int | None:
    for item in _walk_objects(value):
        for key in keys:
            candidate = item.get(key)
            if isinstance(candidate, int) and not isinstance(candidate, bool):
                return candidate
            if isinstance(candidate, str) and candidate.isdigit():
                return int(candidate)
    return None


def _require_method(knowledge: dict[str, Any], expected: str) -> None:
    documented = _string_value(knowledge, ("method", "httpMethod", "http_method"))
    if documented and documented.lower() != expected.lower():
        raise OneError(
            f"One action knowledge documented {documented.upper()}, expected "
            f"{expected.upper()}."
        )
