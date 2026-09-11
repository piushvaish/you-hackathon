import json
import socket
import subprocess

import pytest

from kojable_agent import __main__ as cli
from kojable_agent import config
from kojable_agent.summary import show_summary


def comparison():
    return {
        "question": "The same question?",
        "run_1": {"alignment_score": 77, "recommendation": "depends"},
        "run_2": {"alignment_score": 67, "recommendation": "depends"},
        "learning": {
            "trigger": "missing_primary_verification",
            "rule": "Verify primary documentation.",
            "issue_number": 2,
            "issue_url": "https://github.com/piushvaish/you-hackathon/issues/2",
        },
        "delta": -10,
        "status": "regressed",
    }


def test_summary_cli_is_offline_and_read_only(tmp_path, monkeypatch, capsys):
    data = tmp_path / "data"
    data.mkdir()
    artifact = data / "comparison.json"
    artifact.write_text(json.dumps(comparison()), encoding="utf-8")
    before = artifact.read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError("summary attempted credentials, network, or subprocess")

    monkeypatch.setattr(config, "repository_root", lambda: tmp_path)
    monkeypatch.setattr(config.Settings, "load", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    assert cli.main(["--summary"]) == 0
    output = capsys.readouterr().out
    for expected in ("77%", "67%", "-10 percentage points", "REGRESSED", "Verify primary documentation.", "/issues/2"):
        assert expected in output
    assert artifact.read_bytes() == before
    assert list(data.iterdir()) == [artifact]


def test_missing_summary(tmp_path, capsys):
    assert show_summary(tmp_path) == 0
    assert "No completed comparison found." in capsys.readouterr().out


def test_summary_does_not_echo_extra_secrets(tmp_path, capsys):
    payload = comparison()
    payload["ONE_SECRET"] = "private-value"
    payload["trace"] = "private-trace"
    payload["learning"]["rule"] += " ONE_SECRET=secret-value TRACE-private"
    payload["learning"]["issue_url"] = "https://app.crewai.com/private?access_code=private-code"
    (tmp_path / "comparison.json").write_text(json.dumps(payload), encoding="utf-8")
    assert show_summary(tmp_path) == 0
    output = capsys.readouterr().out
    for secret in ("private-value", "private-trace", "secret-value", "TRACE-private", "private-code"):
        assert secret not in output


@pytest.mark.parametrize("content", ["{", json.dumps({}), json.dumps({**comparison(), "delta": 20})])
def test_invalid_summary_is_clean(tmp_path, capsys, content):
    (tmp_path / "comparison.json").write_text(content, encoding="utf-8")
    assert show_summary(tmp_path) == 1
    assert "invalid or unreadable" in capsys.readouterr().out
