"""Tests for `machina connect` — the MCP connection bundle for external agents."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from machina_cli.main import app
from machina_cli.mcp_session import SCHEMA, MCPConnectError

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
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client(api_url)),
    )


def test_connect_json_reveal_emits_full_bundle():
    p1, p2, p3 = _patches()
    with p1, p2, p3:
        result = runner.invoke(app, ["connect", "proj_1", "--json", "--reveal"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "schema": SCHEMA,
        "project_id": "proj_1",
        "name": "proj_1",
        "url": _MCP_URL,
        "transport": "sse",
        "auth_header": "X-Api-Token",
        "verified": False,
        "token": _TOKEN,
        "masked": False,
        "durable": True,
    }


def test_connect_json_token_null_when_not_revealed():
    p1, p2, p3 = _patches()
    with p1, p2, p3:
        result = runner.invoke(app, ["connect", "proj_1", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert _TOKEN not in result.output
    assert payload["masked"] is True
    # token is null (not a masked preview) so a script can't use a redacted string
    assert payload["token"] is None


def test_connect_json_durable_false_for_session_token():
    p1, p2, p3 = _patches(header="X-Session-Token")
    with p1, p2, p3:
        result = runner.invoke(app, ["connect", "proj_1", "--json", "--reveal"])
    assert result.exit_code == 0
    assert json.loads(result.output)["durable"] is False


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
    assert (
        json.loads(result.output)
        == MCPConnectError("wrong_project", "no project specified").to_payload()
    )


def test_connect_json_not_authenticated_errors():
    with (
        patch("machina_cli.commands.connect.get_config", return_value="proj_1"),
        patch("machina_cli.commands.connect.resolve_auth_token", return_value=("", "")),
    ):
        result = runner.invoke(app, ["connect", "proj_1", "--json"])
    assert result.exit_code == 1
    assert (
        json.loads(result.output)
        == MCPConnectError("missing_credentials", "not authenticated").to_payload()
    )


def test_connect_json_empty_api_url_errors():
    p1, p2, p3 = _patches(api_url="")
    with p1, p2, p3:
        result = runner.invoke(app, ["connect", "proj_1", "--json"])
    assert result.exit_code == 1
    assert (
        json.loads(result.output)
        == MCPConnectError("wrong_project", "project has no client-api address").to_payload()
    )


def test_connect_json_probe_failure_errors():
    p1, p2, p3 = _patches()
    failure = MCPConnectError("endpoint_unavailable", "MCP endpoint timed out", url=_MCP_URL)
    with p1, p2, p3, patch("machina_cli.mcp_session.probe", side_effect=failure):
        result = runner.invoke(app, ["connect", "proj_1", "--json", "--probe"])
    assert result.exit_code == 1
    assert json.loads(result.output) == failure.to_payload()
    assert _TOKEN not in result.output


def test_connect_probe_failure_json_reveal_still_never_leaks_token():
    failure = MCPConnectError("access_denied", "MCP server denied access (HTTP 403)")
    p1, p2, p3 = _patches()
    with p1, p2, p3, patch("machina_cli.mcp_session.probe", side_effect=failure):
        result = runner.invoke(app, ["connect", "proj_1", "--json", "--reveal", "--probe"])
    assert result.exit_code == 1
    assert _TOKEN not in result.output


# --- --mint -----------------------------------------------------------------


def _mint_client(search_data, generated_key="sk-minted-0987654321zzz"):
    """MachinaClient mock: search-key returns search_data, generate-key returns a key."""
    client = MagicMock()

    def _post(path, payload=None):
        if path == "system/api/search-key":
            return {"data": search_data}
        if path == "system/api/generate-key":
            return {"data": {"api_key": generated_key}}
        return {"data": {}}

    client.return_value.post.side_effect = _post
    return client


def test_connect_mint_generates_key_when_absent():
    # session token + --mint + no existing sportsclaw key -> generate one
    with (
        patch("machina_cli.commands.connect.get_config", return_value="proj_1"),
        patch(
            "machina_cli.commands.connect.resolve_auth_token",
            return_value=("X-Session-Token", "session-jwt"),
        ),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
        patch("machina_cli.commands.connect.MachinaClient", _mint_client(search_data=[])),
    ):
        result = runner.invoke(app, ["connect", "proj_1", "--json", "--reveal", "--mint"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["auth_header"] == "X-Api-Token"
    assert payload["token"] == "sk-minted-0987654321zzz"


def test_connect_mint_reuses_existing_key():
    existing = [{"name": "sportsclaw-proj_1", "_id": "k1", "key": "sk-existing-1122334455xx"}]
    with (
        patch("machina_cli.commands.connect.get_config", return_value="proj_1"),
        patch(
            "machina_cli.commands.connect.resolve_auth_token",
            return_value=("X-Session-Token", "session-jwt"),
        ),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
        patch("machina_cli.commands.connect.MachinaClient", _mint_client(search_data=existing)),
    ):
        result = runner.invoke(app, ["connect", "proj_1", "--json", "--reveal", "--mint"])
    assert result.exit_code == 0
    assert json.loads(result.output)["token"] == "sk-existing-1122334455xx"


def test_connect_mint_requires_org():
    # get_config returns "" for default_organization_id -> mint cannot proceed
    with (
        patch("machina_cli.commands.connect.get_config", return_value=""),
        patch(
            "machina_cli.commands.connect.resolve_auth_token",
            return_value=("X-Session-Token", "session-jwt"),
        ),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
    ):
        result = runner.invoke(app, ["connect", "proj_1", "--json", "--mint"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error"] == (
        "organization required to mint an api key (set a default org or pass --org)"
    )
    assert payload["error_code"] == "credential_mint_failed"


def test_connect_mint_sends_correct_generate_payload():
    captured = {}

    client = MagicMock()

    def _post(path, payload=None):
        if path == "system/api/search-key":
            return {"data": []}
        if path == "system/api/generate-key":
            captured["payload"] = payload
            return {"data": {"api_key": "sk-minted-0987654321zzz"}}
        return {"data": {}}

    client.return_value.post.side_effect = _post
    with (
        patch("machina_cli.commands.connect.get_config", return_value="org_1"),
        patch(
            "machina_cli.commands.connect.resolve_auth_token",
            return_value=("X-Session-Token", "s"),
        ),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
        patch("machina_cli.commands.connect.MachinaClient", client),
    ):
        result = runner.invoke(app, ["connect", "proj_1", "--json", "--reveal", "--mint"])
    assert result.exit_code == 0
    assert captured["payload"] == {
        "organization_id": "org_1",
        "project_id": "proj_1",
        "name": "sportsclaw-proj_1",
        "level": "SERVICE_ACCESS",
    }


def test_connect_mint_json_masks_minted_token_without_reveal():
    with (
        patch("machina_cli.commands.connect.get_config", return_value="org_1"),
        patch(
            "machina_cli.commands.connect.resolve_auth_token",
            return_value=("X-Session-Token", "s"),
        ),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
        patch("machina_cli.commands.connect.MachinaClient", _mint_client(search_data=[])),
    ):
        result = runner.invoke(app, ["connect", "proj_1", "--json", "--mint"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["token"] is None
    assert payload["masked"] is True
    assert payload["durable"] is True
    assert "sk-minted-0987654321zzz" not in result.output


def test_connect_mint_refuses_duplicate_when_value_unavailable():
    search = [{"name": "sportsclaw-proj_1", "_id": "k1", "key": ""}]
    with (
        patch("machina_cli.commands.connect.get_config", return_value="org_1"),
        patch(
            "machina_cli.commands.connect.resolve_auth_token",
            return_value=("X-Session-Token", "s"),
        ),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
        patch("machina_cli.commands.connect.MachinaClient", _mint_client(search_data=search)),
    ):
        result = runner.invoke(app, ["connect", "proj_1", "--json", "--reveal", "--mint"])
    assert result.exit_code == 1
    assert "already exists but its value is unavailable" in json.loads(result.output)["error"]


def test_connect_mint_org_flag_supplies_org():
    with (
        patch("machina_cli.commands.connect.get_config", return_value=""),
        patch(
            "machina_cli.commands.connect.resolve_auth_token",
            return_value=("X-Session-Token", "s"),
        ),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
        patch("machina_cli.commands.connect.MachinaClient", _mint_client(search_data=[])),
    ):
        result = runner.invoke(
            app, ["connect", "proj_1", "--json", "--reveal", "--mint", "--org", "org_xyz"]
        )
    assert result.exit_code == 0
    assert json.loads(result.output)["token"] == "sk-minted-0987654321zzz"


def test_connect_probe_success_emits_bundle():
    p1, p2, p3 = _patches()
    probed = {
        "transport": "streamable-http",
        "url": f"{_API_URL}/mcp",
        "protocol_version": "2025-06-18",
        "server": {"name": "machina", "version": "1.28.1"},
        "tool_count": 3,
        "health_check": "ok",
    }
    with p1, p2, p3, patch("machina_cli.mcp_session.probe", return_value=probed) as probe:
        result = runner.invoke(app, ["connect", "proj_1", "--json", "--probe"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["url"] == f"{_API_URL}/mcp"
    assert payload["transport"] == "streamable-http"
    assert payload["verified"] is True
    assert payload["schema"] == SCHEMA
    # the probe uses the exact credential being handed off, but never prints it
    assert probe.call_args.args[1] == ("X-Api-Token", _TOKEN)
    assert _TOKEN not in result.output


def test_connect_and_mcp_url_share_schema_keys():
    p1, p2, p3 = _patches()
    with p1, p2, p3:
        connect_out = json.loads(runner.invoke(app, ["connect", "proj_1", "--json"]).output)
    with (
        patch("machina_cli.commands.mcp.get_config", return_value="proj_1"),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
    ):
        url_out = json.loads(runner.invoke(app, ["mcp", "url", "proj_1", "--json"]).output)
    assert set(url_out) <= set(connect_out)
    assert {k: connect_out[k] for k in url_out} == url_out


def test_connect_console_mint_no_session_warning():
    with (
        patch("machina_cli.commands.connect.get_config", return_value="org_1"),
        patch(
            "machina_cli.commands.connect.resolve_auth_token",
            return_value=("X-Session-Token", "s"),
        ),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
        patch("machina_cli.commands.connect.MachinaClient", _mint_client(search_data=[])),
    ):
        result = runner.invoke(app, ["connect", "proj_1", "--mint"])
    assert result.exit_code == 0
    assert "session token" not in result.output.lower()  # mint -> X-Api-Token
    assert "sk-minted-0987654321zzz" not in result.output  # masked in console


def test_connect_sanitizes_unsafe_project_name():
    with (
        patch("machina_cli.commands.connect.get_config", return_value="org.proj:1"),
        patch(
            "machina_cli.commands.connect.resolve_auth_token",
            return_value=("X-Api-Token", _TOKEN),
        ),
        patch("machina_cli.commands.mcp.ProjectClient", _mock_project_client()),
    ):
        result = runner.invoke(app, ["connect", "org.proj:1", "--json", "--reveal"])
    assert result.exit_code == 0
    assert json.loads(result.output)["name"] == "org-proj-1"
