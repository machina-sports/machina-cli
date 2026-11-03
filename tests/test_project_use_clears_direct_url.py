"""`project use` must not keep another project's direct client-api URL."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from machina_cli.commands import project


def _run(store):
    def get_config(key):
        return store.get(key)

    def set_config(key, value):
        store[key] = value

    with (
        patch.object(project, "get_config", side_effect=get_config),
        patch.object(project, "set_config", side_effect=set_config),
        patch.object(project, "MachinaClient", side_effect=RuntimeError("offline")),
    ):
        return CliRunner().invoke(project.app, ["use", "proj_b"])


def test_switching_project_clears_the_previous_direct_url():
    store = {"default_project_id": "proj_a", "client_api_url": "https://a.org.machina.gg"}
    result = _run(store)
    assert result.exit_code == 0
    assert store["default_project_id"] == "proj_b"
    assert store["client_api_url"] == ""
    assert "Cleared client_api_url" in result.output


def test_reselecting_the_same_project_keeps_the_direct_url():
    store = {"default_project_id": "proj_b", "client_api_url": "https://b.org.machina.gg"}
    _run(store)
    assert store["client_api_url"] == "https://b.org.machina.gg"
