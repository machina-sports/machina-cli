"""Configuration commands."""

import typer
from rich.console import Console
from rich.table import Table

from machina_cli.config import get_config, load_config, set_config

app = typer.Typer(help="Configuration management")
console = Console()


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
):
    """Get a configuration value."""
    value = get_config(key)
    if value is None:
        console.print(f"[yellow]Key '{key}' not found.[/yellow]")
    else:
        console.print(f"[bold]{key}[/bold] = {value}")


@app.command("list")
def config_list():
    """List all configuration values."""
    config = load_config()

    table = Table(title="Configuration")
    table.add_column("Key")
    table.add_column("Value")

    for key, value in sorted(config.items()):
        display_value = str(value) if value else "[dim]<empty>[/dim]"
        table.add_row(key, display_value)

    console.print(table)
