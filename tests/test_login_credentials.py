"""Tests for credential precedence across a login.

resolve_auth_token() ranks a stored api_key above a stored session_token. That
makes a leftover api_key a trap: logging in stores a session_token that can never
be reached, so the CLI reports "Login successful." and then fails every request
with "Invalid API Key" — and re-running `machina login` never clears it.

Logging in as a user has to supersede the old key.
"""

import json

import pytest

from machina_cli import config


@pytest.fixture
def creds_file(tmp_path, monkeypatch):
    """Point the config module at a throwaway ~/.machina."""
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CREDS_FILE", tmp_path / "credentials.json")
    return tmp_path / "credentials.json"


def _write(creds_file, payload):
    creds_file.write_text(json.dumps(payload))


class TestStoreSessionToken:
    def test_evicts_stale_api_key(self, creds_file):
        _write(creds_file, {"api_key": "stale-project-key"})

        config.store_session_token("fresh.session.token")

        creds = json.loads(creds_file.read_text())
        assert "api_key" not in creds
        assert creds["session_token"] == "fresh.session.token"

    def test_session_token_is_actually_used_after_login(self, creds_file):
        """The regression: the whole point is that resolve_auth_token picks it up."""
        _write(creds_file, {"api_key": "stale-project-key"})

        config.store_session_token("fresh.session.token")

        header, value = config.resolve_auth_token()
        assert header == "X-Session-Token"
        assert value == "fresh.session.token"

    def test_preserves_unrelated_credentials(self, creds_file):
        """Project tokens live in the same file and must survive a login."""
        _write(creds_file, {"api_key": "stale", "project_token_abc": "keep-me"})

        config.store_session_token("fresh.session.token")

        creds = json.loads(creds_file.read_text())
        assert creds["project_token_abc"] == "keep-me"

    def test_works_when_no_credentials_exist(self, creds_file):
        config.store_session_token("fresh.session.token")

        assert json.loads(creds_file.read_text()) == {"session_token": "fresh.session.token"}

    def test_replaces_previous_session_token(self, creds_file):
        _write(creds_file, {"session_token": "old.token"})

        config.store_session_token("new.token")

        assert json.loads(creds_file.read_text())["session_token"] == "new.token"


class TestExplicitApiKeyLoginStillWins:
    def test_api_key_mode_is_unaffected(self, creds_file):
        """`login --api-key` still stores a key that takes precedence, as documented."""
        config.store_credential("api_key", "ci-key")

        header, value = config.resolve_auth_token()
        assert header == "X-Api-Token"
        assert value == "ci-key"
