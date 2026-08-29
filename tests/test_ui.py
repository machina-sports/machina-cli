"""Regression tests for shared terminal rendering and command discovery."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from machina_cli.catalog import (
    ALL_COMMANDS,
    CLI_SESSION_COMMANDS,
    COMMAND_BY_NAME,
    REPL_COMMANDS,
    SUB_COMMANDS,
)
from machina_cli.main import app
from machina_cli.repl import _completion_options
from machina_cli.ui import extract_collection, pagination_total
from machina_cli.versioning import is_newer

runner = CliRunner()


def test_collection_helpers_accept_flat_and_nested_api_envelopes():
    row = {"_id": "one"}
    assert extract_collection({"data": [row]}) == [row]
    assert extract_collection({"data": {"data": [row]}}) == [row]
    assert extract_collection({"data": {"documents": [row]}}) == [row]
    assert pagination_total({"data": {"pagination": {"total_documents": "42"}}}) == 42


def test_catalog_and_completion_include_recent_commands():
    assert "context-graph" in REPL_COMMANDS
    assert "usage" in SUB_COMMANDS["org"]
    assert "clear-session" in SUB_COMMANDS["auth"]
    assert "timeline" in COMMAND_BY_NAME["context-graph"].actions
    assert "usage " in _completion_options("org ", "")
    assert "--page " in _completion_options("project list --", "--")
    assert "--check " in _completion_options("update --", "--")


def test_catalog_stays_in_sync_with_registered_typer_commands():
    catalog_names = {spec.name for spec in (*ALL_COMMANDS, *CLI_SESSION_COMMANDS)}
    registered_names = {group.name for group in app.registered_groups}
    registered_names.update(
        command.name or command.callback.__name__.replace("_", "-")
        for command in app.registered_commands
        if not command.hidden
    )
    assert catalog_names == registered_names

    for group in app.registered_groups:
        expected_actions = set(COMMAND_BY_NAME[group.name].actions)
        actual_actions = {
            command.name or command.callback.__name__.replace("_", "-")
            for command in group.typer_instance.registered_commands
            if not command.hidden
        }
        assert expected_actions == actual_actions, group.name


def test_project_list_renders_nested_rows_and_accurate_pagination():
    client = MagicMock()
    client.return_value.post.return_value = {
        "data": {
            "data": [
                {
                    "_id": "proj_1",
                    "name": "Scores [live]",
                    "slug": "scores-live",
                    "organization_id": "org_1",
                    "status": "active",
                }
            ],
            "pagination": {"total_documents": 41},
        }
    }
    with (
        patch("machina_cli.commands.project.MachinaClient", client),
        patch("machina_cli.commands.project.get_config", return_value="proj_1"),
    ):
        result = runner.invoke(app, ["project", "list", "--page", "2", "--limit", "20"])

    assert result.exit_code == 0, result.output
    assert "Scores [live]" in result.output
    assert "Page 2/3" in result.output
    assert "21–21 of 41 projects" in result.output


def test_project_list_json_is_parseable_for_nested_response():
    rows = [{"_id": "proj_1", "name": "Scores"}]
    client = MagicMock()
    client.return_value.post.return_value = {"data": {"items": rows}}
    with (
        patch("machina_cli.commands.project.MachinaClient", client),
        patch("machina_cli.commands.project.get_config", return_value=None),
    ):
        result = runner.invoke(app, ["project", "list", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == rows


def test_invalid_pagination_stops_before_api_call():
    client = MagicMock()
    with patch("machina_cli.commands.project.MachinaClient", client):
        result = runner.invoke(app, ["project", "list", "--page", "0"])
    assert result.exit_code != 0
    assert "--page" in result.output
    client.assert_not_called()


def test_release_version_order_handles_prereleases_and_padding():
    assert is_newer("1.2.0", "1.2.0rc1")
    assert not is_newer("1.2", "1.2.0")
    assert not is_newer("1.2.0+build.2", "1.2.0+build.1")
    assert is_newer("1.10.0", "1.9.9")


def test_update_check_does_not_start_install():
    with (
        patch("machina_cli.updater.get_latest_version", return_value="99.0.0"),
        patch("machina_cli.updater._show_release_notes") as release_notes,
    ):
        result = runner.invoke(app, ["update", "--check"])
    assert result.exit_code == 0, result.output
    assert "Update available" in result.output
    release_notes.assert_not_called()


def test_update_routes_python_install_through_current_environment():
    with (
        patch("machina_cli.updater.__version__", "1.0.0"),
        patch("machina_cli.updater.get_latest_version", return_value="1.1.0"),
        patch("machina_cli.updater._show_release_notes"),
        patch("machina_cli.updater._installation_kind", return_value="python"),
        patch("machina_cli.updater._update_python_package", return_value=True) as update_python,
    ):
        result = runner.invoke(app, ["update"])
    assert result.exit_code == 0, result.output
    update_python.assert_called_once_with("1.1.0", False)


def test_update_never_overwrites_an_editable_install():
    with (
        patch("machina_cli.updater.__version__", "1.0.0"),
        patch("machina_cli.updater.get_latest_version", return_value="1.1.0"),
        patch("machina_cli.updater._show_release_notes"),
        patch("machina_cli.updater._installation_kind", return_value="editable"),
        patch("machina_cli.updater._update_binary") as update_binary,
        patch("machina_cli.updater._update_python_package") as update_python,
    ):
        result = runner.invoke(app, ["update"])
    assert result.exit_code == 0, result.output
    assert "Editable development install" in result.output
    update_binary.assert_not_called()
    update_python.assert_not_called()
