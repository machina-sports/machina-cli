"""Connector management commands."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from machina_cli.project_client import ProjectClient

app = typer.Typer(help="Connector management")
console = Console()


@app.command("list")
def list_connectors(
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    page: int = typer.Option(1, "--page", help="Page number"),
    page_size: int = typer.Option(20, "--limit", "-l", help="Items per page"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List connectors in the current project."""
    client = ProjectClient(project_id)
    result = client.post("connector/search", {
        "filters": {},
        "page": page,
        "page_size": page_size,
        "sorters": ["name", 1],
    })

    items = result.get("data", [])

    if json_output:
        import json
        console.print_json(json.dumps(items, default=str))
        return

    if not items:
        console.print("[yellow]No connectors found.[/yellow]")
        return

    table = Table(title="Connectors")
    table.add_column("Name", style="bold")
    table.add_column("Type", style="dim")
    table.add_column("Status")
    table.add_column("ID", style="dim")

    for item in items:
        status = item.get("status", item.get("enabled", ""))
        color = "green" if status in ("active", True) else "dim"
        table.add_row(
            item.get("name", ""),
            item.get("type", item.get("connector_type", "")),
            f"[{color}]{status}[/{color}]",
            item.get("_id", ""),
        )

    console.print(table)

    pagination = result.get("pagination", {})
    total = pagination.get("total", pagination.get("total_documents", 0))
    if total:
        console.print(f"\n  [dim]Page {page} ({len(items)} of {total} connectors)[/dim]")


@app.command("get")
def get_connector(
    name: str = typer.Argument(..., help="Connector name"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Get connector details by name."""
    client = ProjectClient(project_id)
    result = client.get(f"connector/{name}")

    data = result.get("data", result)

    if json_output:
        import json
        console.print_json(json.dumps(data, default=str))
        return

    item = data if isinstance(data, dict) else {}

    console.print(Panel.fit(
        f"[bold]Name:[/bold] {item.get('name', 'N/A')}\n"
        f"[bold]Type:[/bold] {item.get('type', item.get('connector_type', 'N/A'))}\n"
        f"[bold]Status:[/bold] {item.get('status', 'N/A')}\n"
        f"[bold]ID:[/bold] {item.get('_id', 'N/A')}\n"
        f"[bold]Description:[/bold] {item.get('description', 'N/A')}",
        title="Connector",
        border_style="#FF5C1F",
    ))
