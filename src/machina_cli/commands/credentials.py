"""API key and credentials management commands."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from machina_cli.client import MachinaClient
from machina_cli.config import get_config

app = typer.Typer(help="API key management")
console = Console()


@app.command()
def generate(
    name: str = typer.Option("client-api", "--name", "-n", help="Name for the API key"),
    org_id: Optional[str] = typer.Option(None, "--org", "-o", help="Organization ID"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    level: str = typer.Option("SERVICE_ACCESS", "--level", "-l", help="Permission level"),
):
    """Generate a new API key."""
    client = MachinaClient()

    if not org_id:
        org_id = get_config("default_organization_id")
    if not project_id:
        project_id = get_config("default_project_id")

    if not org_id or not project_id:
        console.print("[red]Organization and project are required. Set defaults or use --org/--project.[/red]")
        raise typer.Exit(1)

    result = client.post("system/api/generate-key", {
        "organization_id": org_id,
        "project_id": project_id,
        "name": name,
        "level": level,
    })

    api_key = result.get("data", {}).get("api_key", "")
    console.print(f"\n[green]API key generated:[/green]\n")
    console.print(f"  [bold]{api_key}[/bold]\n")
    console.print("[dim]Save this key securely — it won't be shown again.[/dim]")


@app.command("list")
def list_keys(
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
):
    """List API keys for a project."""
    client = MachinaClient()

    if not project_id:
        project_id = get_config("default_project_id")
    if not project_id:
        console.print("[red]Project ID required. Set default or use --project.[/red]")
        raise typer.Exit(1)

    result = client.post("system/api/search-key", {
        "filters": {"project_id": project_id},
        "sorters": ["name", 1],
        "page": 1,
        "page_size": 50,
    })

    keys = result.get("data", [])

    if not keys:
        console.print("[yellow]No API keys found.[/yellow]")
        return

    table = Table(title="API Keys")
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Key", style="dim")
    table.add_column("Project", style="dim")

    for key in keys:
        key_value = key.get("key", "")
        # Mask the key, showing only first/last 8 chars
        masked = f"{key_value[:8]}...{key_value[-8:]}" if len(key_value) > 20 else key_value
        table.add_row(
            key.get("_id", ""),
            key.get("name", ""),
            masked,
            key.get("project_id", ""),
        )

    console.print(table)


@app.command()
def revoke(
    key_id: str = typer.Argument(..., help="API key ID to revoke"),
):
    """Revoke an API key."""
    client = MachinaClient()

    result = client.post("system/api/revoke-key", {"api_key_id": key_id})

    console.print(f"[green]API key {key_id} revoked.[/green]")
