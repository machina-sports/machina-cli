"""Configuration commands."""

import json
import re

import typer

from machina_cli.config import get_config, load_config, set_config
from machina_cli.ui import cell, console, make_table

app = typer.Typer(help="Configuration management")

# Keys whose values are secrets and must never be printed in bulk output.
_SECRET_KEY = re.compile(r"(api[_-]?key|token|secret|password)", re.IGNORECASE)


def _redact(config: dict) -> dict:
    """Mask secret-looking values so bulk config output never leaks credentials."""
    return {k: ("***redacted***" if v and _SECRET_KEY.search(k) else v) for k, v in config.items()}


@app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Configuration key"),
    value: str = typer.Argument(..., help="Configuration value"),
):
    """Set a configuration value."""
    set_config(key, value)
    console.print(f"[green]{key}[/green] = {value}")


@app.command("get")
def config_get(
    key: str = typer.Argument(..., help="Configuration key"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    reveal: bool = typer.Option(False, "--reveal", help="Show secret values (masked by default)"),
):
    """Get a configuration value."""
    value = get_config(key)
    if value is None:
        if json_output:
            print(json.dumps({"key": key, "value": None, "error": "key not found"}))
            raise typer.Exit(1)
        console.print(f"[yellow]Key '{key}' not found.[/yellow]")
        return
    if value and not reveal and _SECRET_KEY.search(key):
        value = "***redacted***"
    if json_output:
        print(json.dumps({"key": key, "value": value}))
        return
    console.print(f"[bold]{key}[/bold] = {value}")


@app.command("list")
def config_list(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List all configuration values."""
    config = _redact(load_config())

    if json_output:
        print(json.dumps(config))
        return

    table = make_table("Configuration", expand=True)
    table.add_column("Key", ratio=2, overflow="ellipsis")
    table.add_column("Value", ratio=3, overflow="fold")

    for key, value in sorted(config.items()):
        table.add_row(
            cell(key, style="bold"),
            cell(value, empty="<empty>", style="" if value else "dim"),
        )

    console.print(table)
