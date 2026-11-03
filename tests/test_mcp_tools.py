"""Tests for `machina mcp tools` — read-only capability discovery over real MCP."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from machina_cli.main import app
from tests.mcp_server_fixture import GOOD_TOKEN, Recorder, build_server, serve

runner = CliRunner()


def _invoke(base, *args):
    client = MagicMock()
    client.return_value.api_url = base
    with (
        patch("machina_cli.commands.mcp.get_config", return_value="proj_1"),
        patch("machina_cli.commands.mcp.ProjectClient", client),
        patch(
            "machina_cli.commands.mcp.resolve_auth_token",
            return_value=("X-Api-Token", GOOD_TOKEN),
        ),
    ):
        return runner.invoke(app, ["mcp", "tools", "proj_1", *args])


def test_tools_walks_every_page_and_never_calls_a_tool():
    calls: list = []
    server = build_server(read=None, tools=25, page_size=4, calls=calls)
    with serve(server.streamable_http_app()) as base:
        result = _invoke(base, "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "machina.mcp.tools/v1"
    assert payload["transport"] == "streamable-http"
    assert payload["total"] == payload["count"] == 26
    assert {tool["name"] for tool in payload["tools"]} >= {"health_check", "extra_tool_024"}
    assert calls == []  # discovery is read-only
    assert GOOD_TOKEN not in result.output


def test_tools_compact_entries_carry_only_served_fields():
    with serve(build_server(read=None, tools=1).streamable_http_app()) as base:
        result = _invoke(base, "--json")
    extra = next(t for t in json.loads(result.output)["tools"] if t["name"] == "extra_tool_000")
    # No inferred executable/prerequisite flags — only what the server supplies.
    assert set(extra) == {"name", "title", "summary", "required"}
    assert extra["required"] == ["query"]
    assert extra["summary"] == "Extra tool 0"


def test_tools_search_filters_after_full_walk():
    with serve(build_server(read=None, tools=12, page_size=5).streamable_http_app()) as base:
        result = _invoke(base, "--json", "--search", "HEALTH")
    payload = json.loads(result.output)
    assert payload["total"] == 13
    assert [tool["name"] for tool in payload["tools"]] == ["health_check"]


def test_tools_describe_matches_served_schema_exactly():
    server = build_server(read=None, tools=3, page_size=2)
    with serve(server.streamable_http_app()) as base:
        result = _invoke(base, "--json", "--describe", "extra_tool_002")
    assert result.exit_code == 0, result.output
    detail = json.loads(result.output)["tool"]

    import anyio

    served = next(t for t in anyio.run(server.list_tools) if t.name == "extra_tool_002")
    assert detail == served.model_dump(by_alias=True, exclude_none=True, mode="json")
    assert detail["inputSchema"]["properties"]["query"]["type"] == "string"


def test_tools_describe_unknown_tool_fails_typed():
    with serve(build_server(read=None).streamable_http_app()) as base:
        result = _invoke(base, "--json", "--describe", "nope")
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "tool_not_found"


def test_tools_over_legacy_sse():
    with serve(Recorder(build_server(read=None, tools=2).sse_app())) as base:
        result = _invoke(base, "--json")
    payload = json.loads(result.output)
    assert payload["transport"] == "sse"
    assert payload["total"] == 3


def test_tools_auth_denial_is_typed_and_not_downgraded():
    app_ = Recorder(build_server(read=None).sse_app(), deny=401)
    with serve(app_) as base:
        result = _invoke(base, "--json")
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "expired_credentials"
    assert all(path != "/mcp/sse" for _, path in app_.paths)


def test_tools_console_table():
    with serve(build_server(read=None, tools=1).streamable_http_app()) as base:
        result = _invoke(base)
    assert result.exit_code == 0, result.output
    assert "extra_tool_000" in result.output
    assert "2 of 2 tools" in result.output
