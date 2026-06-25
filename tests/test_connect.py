"""Tests for `machina connect` — the MCP connection bundle for external agents."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from machina_cli.main import app

runner = CliRunner()

_API_URL = "https://acme-proj.org.machina.gg"
_MCP_URL = "https://acme-proj.org.machina.gg/mcp/sse"
_TOKEN = "sk-1234567890abcdefghij"  # len > 20 -> masks to prefix...suffix


def _mock_project_client(api_url=_API_URL):
    client = MagicMock()
    client.return_value.api_url = api_url
    return client


def _patches(token=_TOKEN, header="X-Api-Token", api_url=_API_URL, project="proj_1"):
    return (
        patch("machina_cli.commands.connect.get_config", return_value=project),
        patch("machina_cli.commands.connect.resolve_auth_token", return_value=(header, token)),
        patch("machina_cli.commands.connect.ProjectClient", _mock_project_client(api_url)),
    )


def test_connect_json_reveal_emits_full_bundle():
    p1, p2, p3 = _patches()
    with p1, p2, p3:
        result = runner.invoke(app, ["connect", "proj_1", "--json", "--reveal"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "name": "proj_1",
        "url": _MCP_URL,
        "transport": "sse",
        "auth_header": "X-Api-Token",
        "token": _TOKEN,
        "masked": False,
    }


def test_connect_json_masks_token_by_default():
    p1, p2, p3 = _patches()
    with p1, p2, p3:
        result = runner.invoke(app, ["connect", "proj_1", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert _TOKEN not in result.output
    assert payload["masked"] is True
    assert payload["token"] == "sk-123456789...efghij"


def test_connect_name_override():
    p1, p2, p3 = _patches()
    with p1, p2, p3:
        result = runner.invoke(app, ["connect", "proj_1", "--json", "--name", "my-server"])
    assert result.exit_code == 0
    assert json.loads(result.output)["name"] == "my-server"


def test_connect_console_masks_token_and_prints_command():
    p1, p2, p3 = _patches()
    with p1, p2, p3:
        result = runner.invoke(app, ["connect", "proj_1"])
    assert result.exit_code == 0
    assert _TOKEN not in result.output
    assert "sportsclaw mcp add" in result.output
    assert _MCP_URL in result.output


def test_connect_session_token_warns():
    p1, p2, p3 = _patches(header="X-Session-Token")
    with p1, p2, p3:
        result = runner.invoke(app, ["connect", "proj_1"])
    assert result.exit_code == 0
    assert "session token" in result.output.lower()


def test_connect_json_no_project_errors():
    with patch("machina_cli.commands.connect.get_config", return_value=""):
        result = runner.invoke(app, ["connect", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output) == {"error": "no project specified"}


def test_connect_json_not_authenticated_errors():
    with (
        patch("machina_cli.commands.connect.get_config", return_value="proj_1"),
        patch("machina_cli.commands.connect.resolve_auth_token", return_value=("", "")),
    ):
        result = runner.invoke(app, ["connect", "proj_1", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output) == {"error": "not authenticated"}


def test_connect_json_empty_api_url_errors():
    p1, p2, p3 = _patches(api_url="")
    with p1, p2, p3:
        result = runner.invoke(app, ["connect", "proj_1", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output) == {"error": "project has no client-api address"}


def test_connect_json_probe_failure_errors():
    p1, p2, p3 = _patches()
    with p1, p2, p3, patch("machina_cli.commands.connect._probe", return_value=False):
        result = runner.invoke(app, ["connect", "proj_1", "--json", "--probe"])
    assert result.exit_code == 1
    assert json.loads(result.output) == {"error": "endpoint not reachable", "url": _MCP_URL}
