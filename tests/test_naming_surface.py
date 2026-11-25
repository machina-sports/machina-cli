"""The three naming decisions, pinned.

`template` vs `skills`, `login` vs `auth login`, and `connect` vs `mcp url` were
the open questions after the 0.11.0 rebrand. Each is resolved by making the
relationship explicit rather than by renaming anything, so these tests guard the
*behaviour* that makes the resolution true -- not the wording.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from machina_cli.catalog import ALL_COMMANDS, COMMAND_BY_NAME, command_catalog
from machina_cli.main import app

runner = CliRunner()


# --- 1. `template` is deprecated, but still works ----------------------------


def test_template_group_warns_that_it_is_deprecated():
    client = MagicMock()
    client.return_value.post.return_value = {"data": []}
    with patch("machina_cli.commands.template.ProjectClient", client):
        result = runner.invoke(app, ["template", "list"])

    assert "deprecated" in result.output
    assert "machina skills" in result.output


def test_skills_does_not_warn_though_it_calls_the_same_functions():
    """`skills` delegates into template.* as plain Python; only the CLI path warns."""
    client = MagicMock()
    client.return_value.post.return_value = {"data": []}
    with (
        patch("machina_cli.commands.template.ProjectClient", client),
        patch("machina_cli.commands.skills._ensure_constructor_installed"),
    ):
        result = runner.invoke(app, ["skills", "list"])

    assert "deprecated" not in result.output


def test_deprecated_commands_are_hidden_from_the_catalog_but_still_known():
    """Hidden from the printed map, still present for completion and the sync test."""
    spec = COMMAND_BY_NAME["template"]
    assert spec.deprecated == "machina skills"
    assert spec in ALL_COMMANDS  # tab completion and the Typer sync test still see it

    rendered = _render(command_catalog(width=120))
    assert "template" not in rendered
    assert "skills" in rendered


# --- 2. `login` and `auth login` differ only in what follows -----------------


def test_login_and_auth_login_take_the_same_flags():
    """The divergence was the bug: same intent, different flag sets."""
    top = _params(app, "login")
    nested = _params(_group(app, "auth"), "login")

    shared = {"api_key", "with_credentials", "username", "password"}
    assert shared <= top, f"missing on `machina login`: {shared - top}"
    assert shared <= nested, f"missing on `machina auth login`: {shared - nested}"


def test_only_the_top_level_login_opens_a_session():
    """That difference is the whole reason both exist, so it is documented."""
    top = _params(app, "login")
    nested = _params(_group(app, "auth"), "login")

    assert "no_interactive" in top
    assert "no_interactive" not in nested

    assert "interactive session" in _help(app, "login")
    assert "return to your shell" in _help(_group(app, "auth"), "login").lower()


# --- 3. `connect` is built on `mcp url`, and says so ------------------------


def test_connect_and_mcp_cross_reference_each_other():
    connect_help = _help(app, "connect")
    assert "machina mcp url" in connect_help

    mcp_url_help = _help(_group(app, "mcp"), "url")
    assert "machina connect" in mcp_url_help


# --- helpers ----------------------------------------------------------------


def _group(parent, name):
    return next(g.typer_instance for g in parent.registered_groups if g.name == name)


def _command(parent, name):
    return next(
        c
        for c in parent.registered_commands
        if (c.name or c.callback.__name__.replace("_", "-")) == name
    )


def _params(parent, name) -> set[str]:
    return set(inspect.signature(_command(parent, name).callback).parameters)


def _help(parent, name) -> str:
    return inspect.getdoc(_command(parent, name).callback) or ""


def _render(renderable) -> str:
    from rich.console import Console

    console = Console(width=120, record=True, highlight=False)
    console.print(renderable)
    return console.export_text()
