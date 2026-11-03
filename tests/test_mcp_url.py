"""Tests for `machina mcp url` — the per-project MCP endpoint resolver."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from machina_cli.main import app
from machina_cli.mcp_session import SCHEMA, MCPConnectError

runner = CliRunner()


_TOKEN = "sk-1234567890abcdefghij"
_PROBED = {
    "transport": "streamable-http",
    "url": "https://acme-proj.org.machina.gg/mcp",
    "protocol_version": "2025-06-18",
    "server": {"name": "machina", "version": "1.28.1"},
    "tool_count": 42,
    "health_check": "ok",
}
_UNVERIFIED = {
    "schema": SCHEMA,
    "project_id": "proj_1",
    "url": "https://acme-proj.org.machina.gg/mcp/sse",
    "transport": "sse",
    "auth_header": "X-Api-Token",
    "verified": False,
}


def _error(code, message, **extra):
    return MCPConnectError(code, message, **extra).to_payload()


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
    assert json.loads(result.output) == _UNVERIFIED


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
    assert json.loads(result.output) == _error("wrong_project", "no project specified")


def test_mcp_url_json_session_failure_errors():
    client = MagicMock()
    client.side_effect = SystemExit(1)
    with (
        patch("machina_cli.commands.mcp.get_config", return_value="proj_1"),
        patch("machina_cli.commands.mcp.ProjectClient", client),
    ):
        result = runner.invoke(app, ["mcp", "url", "proj_1", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output) == _error("wrong_project", "could not resolve project session")


def test_mcp_url_probe_success_reports_negotiated_transport():
    with (
        patch("machina_cli.commands.mcp.get_config", return_value="proj_1"),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
        patch("machina_cli.commands.mcp.resolve_auth_token", return_value=("X-Api-Token", _TOKEN)),
        patch("machina_cli.mcp_session.probe", return_value=_PROBED) as probe,
    ):
        result = runner.invoke(app, ["mcp", "url", "proj_1", "--json", "--probe"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {
        **_UNVERIFIED,
        "url": "https://acme-proj.org.machina.gg/mcp",
        "transport": "streamable-http",
        "verified": True,
        "protocol_version": "2025-06-18",
        "server": {"name": "machina", "version": "1.28.1"},
        "tool_count": 42,
        "health_check": "ok",
    }
    assert probe.call_args.args[:2] == (
        "https://acme-proj.org.machina.gg",
        ("X-Api-Token", _TOKEN),
    )
    assert _TOKEN not in result.output


def test_mcp_url_probe_failure_uses_typed_error_envelope():
    denied = MCPConnectError(
        "access_denied",
        "MCP server denied access (HTTP 403)",
        http_status=403,
        url="https://acme-proj.org.machina.gg/mcp",
        transport="streamable-http",
    )
    with (
        patch("machina_cli.commands.mcp.get_config", return_value="proj_1"),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
        patch("machina_cli.commands.mcp.resolve_auth_token", return_value=("X-Api-Token", _TOKEN)),
        patch("machina_cli.mcp_session.probe", side_effect=denied),
    ):
        result = runner.invoke(app, ["mcp", "url", "proj_1", "--json", "--probe"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["schema"] == SCHEMA
    assert payload["error_code"] == "access_denied"
    assert payload["hint"]
    assert payload["http_status"] == 403
    assert _TOKEN not in result.output


def test_mcp_url_probe_without_credentials_fails_typed():
    with (
        patch("machina_cli.commands.mcp.get_config", return_value="proj_1"),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
        patch("machina_cli.commands.mcp.resolve_auth_token", return_value=("", "")),
    ):
        result = runner.invoke(app, ["mcp", "url", "proj_1", "--json", "--probe"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "missing_credentials"


def test_mcp_url_empty_api_url_errors():
    with (
        patch("machina_cli.commands.mcp.get_config", return_value="proj_1"),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client(api_url="")),
    ):
        result = runner.invoke(app, ["mcp", "url", "proj_1", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output) == _error("wrong_project", "project has no client-api address")


def test_mcp_url_console_happy_path():
    with (
        patch("machina_cli.commands.mcp.get_config", return_value="proj_1"),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
    ):
        result = runner.invoke(app, ["mcp", "url", "proj_1"])
    assert result.exit_code == 0
    assert "https://acme-proj.org.machina.gg/mcp/sse" in result.output


def test_mcp_url_console_probe_failure_exits_nonzero():
    with (
        patch("machina_cli.commands.mcp.get_config", return_value="proj_1"),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
        patch("machina_cli.commands.mcp.resolve_auth_token", return_value=("X-Api-Token", _TOKEN)),
        patch(
            "machina_cli.mcp_session.probe",
            side_effect=MCPConnectError("endpoint_unavailable", "MCP endpoint timed out"),
        ),
    ):
        result = runner.invoke(app, ["mcp", "url", "proj_1", "--probe"])
    assert result.exit_code == 1
    assert "timed out" in result.output
    assert _TOKEN not in result.output
