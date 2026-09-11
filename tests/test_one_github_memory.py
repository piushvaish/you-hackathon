import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kojable_agent.github_memory import GitHubMemory, build_action_arguments
from kojable_agent.one_client import ActionArguments, OneClient, OneError


CREATE_KNOWLEDGE = {
    "method": "POST",
    "path": "/repos/{owner}/{repo}/issues",
    "requestBody": {
        "type": "object",
        "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
    },
}
GET_KNOWLEDGE = {
    "method": "GET",
    "path": "/repos/{owner}/{repo}/issues/{issue_number}",
}

MARKDOWN_CREATE_KNOWLEDGE = {
    "method": "POST",
    "knowledge": """
# Create an Issue for a Repository

## URL

`https://api.github.com/repos/{{owner}}/{{repo}}/issues`

## Required Path Parameters

| Parameter | Type | Description |
|---|---|---|
| `owner` | string | Account owner. |
| `repo` | string | Repository name. |

## Required Request Body Fields

| Parameter | Type | Description |
|---|---|---|
| `title` | string | Issue title. |

## Optional Request Body Fields

| Parameter | Type | Description |
|---|---|---|
| `body` | string | Issue contents. |

## Response Fields

| Field | Type | Description |
|---|---|---|
| `number` | integer | Created issue number. |
""",
}


class QueueRunner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        output = self.outputs.pop(0)
        return SimpleNamespace(returncode=0, stdout=json.dumps(output), stderr="")


def test_one_github_round_trip_is_list_search_knowledge_execute(tmp_path: Path) -> None:
    remote_rule = "Verify every material comparison against both primary sources."
    runner = QueueRunner(
        [
            {
                "connections": [
                    {
                        "platform": "github",
                        "connectionKey": "connection-key",
                        "state": "connected",
                        "access": {"methods": ["GET", "POST"]},
                    }
                ]
            },
            {"actions": [{"id": "dynamic-create", "name": "Create issue", "method": "POST"}]},
            CREATE_KNOWLEDGE,
            {"data": {"number": 42, "html_url": "https://github.com/example/issues/42"}},
            {"actions": []},
            {"actions": [{"id": "dynamic-get", "name": "Get issue", "method": "GET"}]},
            GET_KNOWLEDGE,
            {"data": {"body": f"## Learned rule\n\n{remote_rule}\n\n## Status\n\nActive"}},
        ]
    )
    one = OneClient(
        tmp_path,
        one_secret="secret-value",
        executable="one",
        runner=runner,
    )
    connection = one.github_connection()
    memory = GitHubMemory(one, connection)
    created = memory.create_issue(title="Learning", body="body")
    retrieved = memory.read_rule(created)

    operations = [call[0][2:4] for call in runner.calls]
    assert operations == [
        ["list", "--search"],
        ["actions", "search"],
        ["actions", "knowledge"],
        ["actions", "execute"],
        ["actions", "search"],
        ["actions", "search"],
        ["actions", "knowledge"],
        ["actions", "execute"],
    ]
    assert all(call[0][1] == "--agent" for call in runner.calls)
    assert all(call[1]["env"]["ONE_SECRET"] == "secret-value" for call in runner.calls)
    assert all(call[1]["encoding"] == "utf-8" for call in runner.calls)
    assert all(call[1]["errors"] == "replace" for call in runner.calls)
    assert created.number == 42
    assert retrieved.retrieved_rule == remote_rule
    assert runner.calls[5][0][5] == "get a repository issue"

    create_command = runner.calls[3][0]
    data = json.loads(create_command[create_command.index("-d") + 1])
    path = json.loads(create_command[create_command.index("--path-vars") + 1])
    assert data == {"title": "Learning", "body": "body"}
    assert path == {"owner": "piushvaish", "repo": "you-hackathon"}


def test_one_refuses_execute_without_knowledge(tmp_path: Path) -> None:
    one = OneClient(tmp_path, executable="one", runner=QueueRunner([]))
    with pytest.raises(OneError, match="before reading its knowledge"):
        one.execute_action(
            "github",
            "undocumented",
            "connection",
            ActionArguments(data={}, path_variables={}, query_parameters={}),
        )


def test_markdown_action_knowledge_maps_only_documented_inputs() -> None:
    arguments = build_action_arguments(
        MARKDOWN_CREATE_KNOWLEDGE,
        {
            "owner": "piushvaish",
            "repository": "you-hackathon",
            "title": "Learning",
            "body": "Rule body",
        },
    )

    assert arguments.path_variables == {
        "owner": "piushvaish",
        "repo": "you-hackathon",
    }
    assert arguments.data == {"title": "Learning", "body": "Rule body"}
    assert arguments.query_parameters == {}


def test_missing_github_connection_is_actionable(tmp_path: Path) -> None:
    one = OneClient(
        tmp_path,
        executable="one",
        runner=QueueRunner([{"connections": []}]),
    )
    with pytest.raises(OneError, match="one add github"):
        one.github_connection()


def test_malformed_one_json_is_rejected(tmp_path: Path) -> None:
    runner = lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0, stdout="not-json", stderr=""
    )
    one = OneClient(tmp_path, executable="one", runner=runner)
    with pytest.raises(OneError, match="malformed JSON"):
        one.list_connections()


def test_missing_one_stdout_is_reported_cleanly(tmp_path: Path) -> None:
    runner = lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0, stdout=None, stderr=None
    )
    one = OneClient(tmp_path, executable="one", runner=runner)
    with pytest.raises(OneError, match="no JSON output"):
        one.list_connections()
