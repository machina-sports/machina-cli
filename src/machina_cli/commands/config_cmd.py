"""Configuration commands."""

import json
import re

import typer
from rich.console import Console
from rich.table import Table

from machina_cli.config import get_config, load_config, set_config

app = typer.Typer(help="Configuration management")
console = Console()

# Keys whose values are secrets and must never be printed in bulk output.
_SECRET_KEY = re.compile(r"(api[_-]?key|token|secret|password)", re.IGNORECASE)


def _redact(config: dict) -> dict:
    """Mask secret-looking values so bulk config output never leaks credentials."""
    return {
        k: ("***redacted***" if v and _SECRET_KEY.search(k) else v)
        for k, v in config.items()
    }


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

    table = Table(title="Configuration")
    table.add_column("Key")
    table.add_column("Value")

    for key, value in sorted(config.items()):
        display_value = str(value) if value else "[dim]<empty>[/dim]"
        table.add_row(key, display_value)

    console.print(table)
