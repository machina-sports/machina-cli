"""Mapping management commands."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from machina_cli.project_client import ProjectClient

app = typer.Typer(help="Mapping management")
console = Console()


@app.command("list")
def list_mappings(
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    page: int = typer.Option(1, "--page", help="Page number"),
    page_size: int = typer.Option(20, "--limit", "-l", help="Items per page"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List mappings in the current project."""
    client = ProjectClient(project_id)
    result = client.post("mapping/search", {
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
        console.print("[yellow]No mappings found.[/yellow]")
        return

    table = Table(title="Mappings")
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("ID", style="dim")

    for item in items:
        status = item.get("status", "")
        color = "green" if status == "active" else "dim"
        table.add_row(
            item.get("name", ""),
            f"[{color}]{status}[/{color}]",
            item.get("_id", ""),
        )

    console.print(table)

    pagination = result.get("pagination", {})
    total = pagination.get("total", pagination.get("total_documents", 0))
    if total:
        console.print(f"\n  [dim]Page {page} ({len(items)} of {total} mappings)[/dim]")


@app.command("get")
def get_mapping(
    name: str = typer.Argument(..., help="Mapping name"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Get mapping details by name."""
    client = ProjectClient(project_id)
    result = client.get(f"mapping/{name}")

    data = result.get("data", result)

    if json_output:
        import json
        console.print_json(json.dumps(data, default=str))
        return

    item = data if isinstance(data, dict) else {}

    console.print(Panel.fit(
        f"[bold]Name:[/bold] {item.get('name', 'N/A')}\n"
        f"[bold]Status:[/bold] {item.get('status', 'N/A')}\n"
        f"[bold]ID:[/bold] {item.get('_id', 'N/A')}\n"
        f"[bold]Description:[/bold] {item.get('description', 'N/A')}",
        title="Mapping",
        border_style="#FF5C1F",
    ))
