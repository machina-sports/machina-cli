"""Tests for `machina create ai-app`."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from machina_cli.main import app

runner = CliRunner()


def _template_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr("machina-boilerplate-main/package.json", '{"name":"{{APP_SLUG}}"}')
        bundle.writestr("machina-boilerplate-main/README.md", "# {{APP_NAME}}")
        bundle.writestr("machina-boilerplate-main/.env.example", "MACHINA_AGENT=assistant")
        bundle.writestr("machina-boilerplate-main/public/logo.bin", b"\x00\x01")
    return output.getvalue()


def test_create_ai_app_scaffolds_and_renders_placeholders(tmp_path: Path):
    destination = tmp_path / "acme-app"
    with patch("machina_cli.commands.create._download_archive", return_value=_template_zip()):
        result = runner.invoke(
            app,
            [
                "create",
                "ai-app",
                "Acme Match Center",
                "--directory",
                str(destination),
                "--no-git",
                "--json",
            ],
        )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["slug"] == "acme-match-center"
    assert payload["git_initialized"] is False
    assert (destination / "package.json").read_text() == '{"name":"acme-match-center"}'
    assert (destination / "README.md").read_text() == "# Acme Match Center"
    assert (destination / "public/logo.bin").read_bytes() == b"\x00\x01"


def test_create_ai_app_refuses_non_empty_destination(tmp_path: Path):
    destination = tmp_path / "existing"
    destination.mkdir()
    (destination / "keep.txt").write_text("user data")

    result = runner.invoke(
        app,
        ["create", "ai-app", "Acme", "--directory", str(destination), "--json"],
    )

    assert result.exit_code == 1
    assert "destination is not empty" in json.loads(result.output)["error"]
    assert (destination / "keep.txt").read_text() == "user data"


def test_create_ai_app_rejects_archive_path_traversal(tmp_path: Path):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr("machina-boilerplate-main/../../escaped.txt", "nope")
        bundle.writestr("machina-boilerplate-main/README.md", "safe")

    destination = tmp_path / "safe"
    with patch("machina_cli.commands.create._download_archive", return_value=output.getvalue()):
        result = runner.invoke(
            app,
            ["create", "ai-app", "Safe App", "--directory", str(destination), "--no-git"],
        )

    assert result.exit_code == 0
    assert not (tmp_path / "escaped.txt").exists()
    assert (destination / "README.md").read_text() == "safe"
