"""Smoke tests for the `machina sports` passthrough to sports-skills.

The integration is intentionally dynamic: we introspect the installed
sports-skills registry and assert every module it advertises surfaces through
``machina sports`` without any hard-coded list.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from typer.testing import CliRunner

from machina_cli.main import app


@pytest.fixture(scope="module")
def sports_skills_modules() -> list[str]:
    """Read the list of modules directly from the installed sports-skills."""
    from sports_skills.cli import _REGISTRY  # type: ignore[attr-defined]

    modules = list(_REGISTRY.keys())
    assert modules, "sports-skills exposes no modules — registry is empty"
    return modules


def test_sports_help_delegates_to_sports_skills(sports_skills_modules):
    """`machina sports --help` should render sports-skills' own help text."""
    runner = CliRunner()
    result = runner.invoke(app, ["sports", "--help"])

    assert result.exit_code == 0, result.output
    # sports-skills prints its argparse help — look for its prog name & usage.
    assert "sports-skills" in result.output
    assert "Module name" in result.output


def test_sports_no_args_lists_every_registered_module(sports_skills_modules):
    """With no subcommand we expect the Available-modules dump.

    Every module registered in sports-skills must appear in the output so
    that new sports-skills releases surface automatically through machina.
    """
    runner = CliRunner()
    result = runner.invoke(app, ["sports"])

    assert result.exit_code == 0, result.output
    assert "Available modules:" in result.output
    missing = [m for m in sports_skills_modules if m not in result.output]
    assert not missing, f"Modules missing from `machina sports` output: {missing}"


def test_sports_catalog_matches_native_invocation(sports_skills_modules):
    """`machina sports catalog` must produce identical JSON to the native CLI."""
    machina = subprocess.run(
        [sys.executable, "-m", "machina_cli.main", "sports", "catalog"],
        capture_output=True,
        text=True,
        check=False,
    )
    native = subprocess.run(
        [sys.executable, "-m", "sports_skills", "catalog"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert machina.returncode == 0, machina.stderr
    assert native.returncode == 0, native.stderr
    assert machina.stdout == native.stdout
