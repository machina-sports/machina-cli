"""Tests for ProjectClient's precondition ordering.

Login precedes project selection in onboarding, so when both are missing the
error must say "not authenticated" — telling an unauthenticated user to pick a
project first sends them to a command that fails with the login error anyway.
"""

from unittest.mock import patch

import pytest

from machina_cli.project_client import ProjectClient


def _init(auth=("", ""), default_project=""):
    with (
        patch("machina_cli.project_client.resolve_auth_token", return_value=auth),
        patch("machina_cli.project_client.get_config", return_value=default_project),
    ):
        ProjectClient()


class TestPreconditionOrder:
    def test_unauthenticated_and_no_project_says_login_first(self, capsys):
        with pytest.raises(SystemExit):
            _init(auth=("", ""), default_project="")
        err = capsys.readouterr().err
        assert "Not authenticated" in err
        assert "machina login" in err
        assert "No project selected" not in err

    def test_authenticated_but_no_project_says_select_project(self, capsys):
        with pytest.raises(SystemExit):
            _init(auth=("X-Session-Token", "tok"), default_project="")
        err = capsys.readouterr().err
        assert "No project selected" in err
        assert "machina project use" in err
        assert "Not authenticated" not in err

    def test_api_key_auth_counts_as_authenticated(self, capsys):
        """API-key users (env or stored) must not be told to log in."""
        with pytest.raises(SystemExit):
            _init(auth=("X-Api-Token", "key"), default_project="")
        err = capsys.readouterr().err
        assert "No project selected" in err
        assert "Not authenticated" not in err

    def test_selected_project_skips_both_checks(self):
        """With a project set, neither precondition message fires — the session
        lookup proceeds (stubbed here)."""
        with (
            patch("machina_cli.project_client.resolve_auth_token", return_value=("", "")),
            patch(
                "machina_cli.project_client._get_project_session",
                return_value={"token": "t", "api_url": "https://x.machina.gg"},
            ),
        ):
            client = ProjectClient(project_id="proj_1")
        assert client.project_id == "proj_1"
        assert client.api_url == "https://x.machina.gg"
