"""Tests for `machina mcp url` — the per-project MCP endpoint resolver."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from machina_cli.main import app

runner = CliRunner()


def _mock_project_client(api_url="https://acme-proj.org.machina.gg"):
    client = MagicMock()
    client.return_value.api_url = api_url
    return client


def test_mcp_url_json_resolves_endpoint():
    with (
        patch("machina_cli.commands.mcp.get_config", return_value="proj_1"),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
    ):
        result = runner.invoke(app, ["mcp", "url", "proj_1", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "project_id": "proj_1",
        "url": "https://acme-proj.org.machina.gg/mcp/sse",
        "transport": "sse",
        "auth_header": "X-Api-Token",
    }


def test_mcp_url_uses_default_project_when_arg_omitted():
    with (
        patch("machina_cli.commands.mcp.get_config", return_value="default_proj"),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
    ):
        result = runner.invoke(app, ["mcp", "url", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["project_id"] == "default_proj"


def test_mcp_url_json_no_project_errors():
    with patch("machina_cli.commands.mcp.get_config", return_value=""):
        result = runner.invoke(app, ["mcp", "url", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output) == {"error": "no project specified"}


def test_mcp_url_json_session_failure_errors():
    client = MagicMock()
    client.side_effect = SystemExit(1)
    with (
        patch("machina_cli.commands.mcp.get_config", return_value="proj_1"),
        patch("machina_cli.commands.mcp.ProjectClient", client),
    ):
        result = runner.invoke(app, ["mcp", "url", "proj_1", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output) == {"error": "could not resolve project session"}


def test_mcp_url_probe_success_reports_reachable():
    with (
        patch("machina_cli.commands.mcp.get_config", return_value="proj_1"),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
        patch("machina_cli.commands.mcp._probe", return_value=True),
    ):
        result = runner.invoke(app, ["mcp", "url", "proj_1", "--json", "--probe"])
    assert result.exit_code == 0
    assert json.loads(result.output)["reachable"] is True


def test_mcp_url_probe_failure_exits_nonzero():
    with (
        patch("machina_cli.commands.mcp.get_config", return_value="proj_1"),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
        patch("machina_cli.commands.mcp._probe", return_value=False),
    ):
        result = runner.invoke(app, ["mcp", "url", "proj_1", "--json", "--probe"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["reachable"] is False
    assert payload["url"] == "https://acme-proj.org.machina.gg/mcp/sse"
