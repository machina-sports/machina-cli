"""Tests for --json output and secret redaction/masking across CLI commands.

These guard the PR's core invariant: secret values never leak in table or JSON
output, and --json error paths emit parseable JSON with a non-zero exit.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from machina_cli.commands.credentials import _mask_key
from machina_cli.main import app

runner = CliRunner()


# --- credentials._mask_key (unit) -------------------------------------------


def test_mask_key_long_value_is_truncated():
    value = "sk-1234567890abcdefghijklmnop"  # len > 20
    masked = _mask_key(value)
    assert masked == "sk-123456789...klmnop"
    assert value not in masked


def test_mask_key_short_value_never_returned_verbatim():
    # A short key must not be echoed back as-is (the pre-fix leak).
    assert _mask_key("shortkey123") == "***"
    assert _mask_key("a") == "***"


def test_mask_key_empty_value_stays_empty():
    assert _mask_key("") == ""


# --- config get redaction ----------------------------------------------------


def test_config_get_masks_secret_key_by_default():
    with patch("machina_cli.commands.config_cmd.get_config", return_value="supersecrettoken"):
        result = runner.invoke(app, ["config", "get", "session_token"])
    assert result.exit_code == 0
    assert "supersecrettoken" not in result.output
    assert "***redacted***" in result.output


def test_config_get_reveal_shows_secret():
    with patch("machina_cli.commands.config_cmd.get_config", return_value="supersecrettoken"):
        result = runner.invoke(app, ["config", "get", "session_token", "--reveal"])
    assert result.exit_code == 0
    assert "supersecrettoken" in result.output


def test_config_get_non_secret_key_untouched():
    with patch("machina_cli.commands.config_cmd.get_config", return_value="proj_123"):
        result = runner.invoke(app, ["config", "get", "default_project_id", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {"key": "default_project_id", "value": "proj_123"}


def test_config_get_json_secret_redacted():
    with patch("machina_cli.commands.config_cmd.get_config", return_value="supersecrettoken"):
        result = runner.invoke(app, ["config", "get", "api_key", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["value"] == "***redacted***"


def test_config_get_json_missing_key_signals_error():
    with patch("machina_cli.commands.config_cmd.get_config", return_value=None):
        result = runner.invoke(app, ["config", "get", "nope", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["value"] is None
    assert payload["error"] == "key not found"


# --- config list redaction ---------------------------------------------------


def test_config_list_json_redacts_secret_values():
    cfg = {"api_key": "supersecrettoken", "default_project_id": "proj_123"}
    with patch("machina_cli.commands.config_cmd.load_config", return_value=cfg):
        result = runner.invoke(app, ["config", "list", "--json"])
    assert result.exit_code == 0
    assert "supersecrettoken" not in result.output
    payload = json.loads(result.output)
    assert payload["api_key"] == "***redacted***"
    assert payload["default_project_id"] == "proj_123"


# --- credentials list --json -------------------------------------------------


def _mock_client_with_keys(keys):
    client = MagicMock()
    client.return_value.post.return_value = {"data": keys}
    return client


def test_credentials_list_json_masks_by_default():
    keys = [
        {"name": "long", "_id": "1", "key": "sk-1234567890abcdefghijklmnop"},
        {"name": "short", "_id": "2", "key": "shortkey123"},
    ]
    with (
        patch("machina_cli.commands.credentials.get_config", return_value="proj_1"),
        patch("machina_cli.commands.credentials.MachinaClient", _mock_client_with_keys(keys)),
    ):
        result = runner.invoke(app, ["credentials", "list", "--json"])
    assert result.exit_code == 0
    assert "sk-1234567890abcdefghijklmnop" not in result.output
    assert "shortkey123" not in result.output
    payload = json.loads(result.output)
    assert all(entry["masked"] is True for entry in payload)


def test_credentials_list_json_show_keys_reveals_full():
    keys = [{"name": "long", "_id": "1", "key": "sk-1234567890abcdefghijklmnop"}]
    with (
        patch("machina_cli.commands.credentials.get_config", return_value="proj_1"),
        patch("machina_cli.commands.credentials.MachinaClient", _mock_client_with_keys(keys)),
    ):
        result = runner.invoke(app, ["credentials", "list", "--json", "--show-keys"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload[0]["key"] == "sk-1234567890abcdefghijklmnop"
    assert payload[0]["masked"] is False


def test_credentials_list_json_api_failure_emits_error():
    client = MagicMock()
    client.return_value.post.side_effect = SystemExit(1)
    with (
        patch("machina_cli.commands.credentials.get_config", return_value="proj_1"),
        patch("machina_cli.commands.credentials.MachinaClient", client),
    ):
        result = runner.invoke(app, ["credentials", "list", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output) == {"error": "api request failed"}


# --- whoami --json -----------------------------------------------------------


def test_whoami_json_not_authenticated():
    with patch("machina_cli.commands.auth.resolve_auth_token", return_value=("", "")):
        result = runner.invoke(app, ["auth", "whoami", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["authenticated"] is False


def test_whoami_json_session_lookup_failure():
    client = MagicMock()
    client.return_value.get.side_effect = SystemExit(1)
    with (
        patch(
            "machina_cli.commands.auth.resolve_auth_token", return_value=("X-Session-Token", "tok")
        ),
        patch("machina_cli.commands.auth.MachinaClient", client),
    ):
        result = runner.invoke(app, ["auth", "whoami", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["authenticated"] is False
    assert payload["error"] == "session lookup failed"


def test_whoami_json_success_excludes_token():
    client = MagicMock()
    client.return_value.get.return_value = {
        "data": {"name": "Ada", "email": "ada@example.com", "_id": "u1"}
    }
    with (
        patch(
            "machina_cli.commands.auth.resolve_auth_token",
            return_value=("X-Api-Token", "secret-token-value"),
        ),
        patch("machina_cli.commands.auth.MachinaClient", client),
    ):
        result = runner.invoke(app, ["auth", "whoami", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload == {
        "authenticated": True,
        "name": "Ada",
        "email": "ada@example.com",
        "user_id": "u1",
        "auth_method": "API Key",
    }
    assert "secret-token-value" not in result.output


# --- deploy status --json ----------------------------------------------------


def test_deploy_status_json_no_org_emits_error():
    with (
        patch("machina_cli.commands.deploy.get_config", return_value=""),
        patch("machina_cli.commands.deploy.MachinaClient", MagicMock()),
    ):
        result = runner.invoke(app, ["deploy", "status", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output) == {"error": "no organization specified"}


def test_deploy_status_json_api_failure_emits_error():
    client = MagicMock()
    client.return_value.get.side_effect = SystemExit(1)
    with (
        patch("machina_cli.commands.deploy.get_config", return_value="org_1"),
        patch("machina_cli.commands.deploy.MachinaClient", client),
    ):
        result = runner.invoke(app, ["deploy", "status", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output) == {"error": "api request failed"}
