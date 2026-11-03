"""ProjectClient session resolution: direct mode honours the selected project,
and the in-memory cache is keyed on (project, endpoint)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from machina_cli import project_client


@pytest.fixture(autouse=True)
def _clean_cache():
    project_client._project_cache.clear()
    yield
    project_client._project_cache.clear()


def _config(values):
    return patch("machina_cli.project_client.get_config", side_effect=values.get)


def _core(api_url="https://other-proj.org.machina.gg"):
    import base64
    import json
    import time

    claims = {"api": api_url, "exp": time.time() + 3600}
    token = "h." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".s"
    core = MagicMock()
    core.return_value.post.return_value = {"data": {"token": token}}
    return core


DIRECT = {"client_api_url": "https://acme-proj.org.machina.gg", "default_project_id": "proj_a"}


def test_direct_mode_serves_the_configured_project():
    with (
        _config(DIRECT),
        patch("machina_cli.project_client.get_credential", return_value="sk-key"),
    ):
        session = project_client._get_project_session("proj_a")
    assert session["api_url"] == "https://acme-proj.org.machina.gg"
    assert session["direct_api_key"] is True


def test_direct_mode_does_not_hijack_another_selected_project():
    with (
        _config(DIRECT),
        patch(
            "machina_cli.project_client.get_credential",
            side_effect=lambda k: "sk-key" if k == "api_key" else None,
        ),
        patch("machina_cli.project_client.store_credential"),
        patch("machina_cli.project_client.MachinaClient", _core()) as core,
    ):
        session = project_client._get_project_session("proj_b")
    assert session["api_url"] == "https://other-proj.org.machina.gg"
    assert not session.get("direct_api_key")
    core.return_value.post.assert_called_once_with("login/project", {"project_id": "proj_b"})


def test_direct_mode_without_a_default_project_keeps_legacy_behaviour():
    with (
        _config({"client_api_url": "https://acme-proj.org.machina.gg"}),
        patch("machina_cli.project_client.get_credential", return_value="sk-key"),
    ):
        session = project_client._get_project_session("proj_x")
    assert session["direct_api_key"] is True


def test_cache_is_keyed_on_project_and_endpoint():
    creds = patch(
        "machina_cli.project_client.get_credential",
        side_effect=lambda k: "sk-key" if k == "api_key" else None,
    )
    with _config(DIRECT), creds:
        project_client._get_project_session("proj_a")
    with (
        _config({**DIRECT, "client_api_url": "https://staging-proj.org.machina.gg"}),
        creds,
    ):
        session = project_client._get_project_session("proj_a")
    # A changed endpoint never reuses the session cached for the old one.
    assert session["api_url"] == "https://staging-proj.org.machina.gg"
    assert len(project_client._project_cache) == 2
