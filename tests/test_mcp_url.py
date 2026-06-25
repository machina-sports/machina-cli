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


def test_mcp_url_probe_success_emits_normal_payload():
    with (
        patch("machina_cli.commands.mcp.get_config", return_value="proj_1"),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
        patch("machina_cli.commands.mcp._probe", return_value=True),
    ):
        result = runner.invoke(app, ["mcp", "url", "proj_1", "--json", "--probe"])
    assert result.exit_code == 0
    # On success the payload is the normal contract (no extra fields); exit 0 signals reachable.
    assert json.loads(result.output) == {
        "project_id": "proj_1",
        "url": "https://acme-proj.org.machina.gg/mcp/sse",
        "transport": "sse",
        "auth_header": "X-Api-Token",
    }


def test_mcp_url_probe_failure_uses_error_envelope():
    with (
        patch("machina_cli.commands.mcp.get_config", return_value="proj_1"),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
        patch("machina_cli.commands.mcp._probe", return_value=False),
    ):
        result = runner.invoke(app, ["mcp", "url", "proj_1", "--json", "--probe"])
    assert result.exit_code == 1
    assert json.loads(result.output) == {
        "error": "endpoint not reachable",
        "url": "https://acme-proj.org.machina.gg/mcp/sse",
    }


def test_mcp_url_empty_api_url_errors():
    with (
        patch("machina_cli.commands.mcp.get_config", return_value="proj_1"),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client(api_url="")),
    ):
        result = runner.invoke(app, ["mcp", "url", "proj_1", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output) == {"error": "project has no client-api address"}


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
        patch("machina_cli.commands.mcp._probe", return_value=False),
    ):
        result = runner.invoke(app, ["mcp", "url", "proj_1", "--probe"])
    assert result.exit_code == 1
    assert "not reachable" in result.output


# --- _probe internals (httpx mocked) ----------------------------------------


def _mock_httpx_client(status, content_type):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {"content-type": content_type}
    stream_cm = MagicMock()
    stream_cm.__enter__.return_value = resp
    client = MagicMock()
    client.stream.return_value = stream_cm
    client_cm = MagicMock()
    client_cm.__enter__.return_value = client
    return client_cm


def test_probe_true_on_200_event_stream():
    from machina_cli.commands.mcp import _probe

    with (
        patch("httpx.Client", return_value=_mock_httpx_client(200, "text/event-stream")),
        patch("machina_cli.commands.mcp.resolve_auth_token", return_value=("X-Api-Token", "tok")),
    ):
        assert _probe("https://acme-proj.org.machina.gg/mcp/sse") is True


def test_probe_false_on_wrong_content_type():
    from machina_cli.commands.mcp import _probe

    with (
        patch("httpx.Client", return_value=_mock_httpx_client(200, "application/json")),
        patch("machina_cli.commands.mcp.resolve_auth_token", return_value=("X-Api-Token", "tok")),
    ):
        assert _probe("https://acme-proj.org.machina.gg/mcp/sse") is False


def test_probe_false_on_non_200():
    from machina_cli.commands.mcp import _probe

    with (
        patch("httpx.Client", return_value=_mock_httpx_client(401, "text/event-stream")),
        patch("machina_cli.commands.mcp.resolve_auth_token", return_value=("X-Api-Token", "tok")),
    ):
        assert _probe("https://acme-proj.org.machina.gg/mcp/sse") is False


def test_probe_false_on_exception():
    from machina_cli.commands.mcp import _probe

    with (
        patch("httpx.Client", side_effect=RuntimeError("boom")),
        patch("machina_cli.commands.mcp.resolve_auth_token", return_value=("X-Api-Token", "tok")),
    ):
        assert _probe("https://acme-proj.org.machina.gg/mcp/sse") is False
