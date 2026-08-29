"""Connector management commands."""

import typer
from rich.panel import Panel

from machina_cli.project_client import ProjectClient
from machina_cli.ui import (
    cell,
    console,
    emit_json,
    empty_state,
    extract_collection,
    make_table,
    render_pagination,
    status_cell,
    validate_pagination,
)

app = typer.Typer(help="Connector management")


@app.command("list")
def list_connectors(
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    page: int = typer.Option(1, "--page", help="Page number"),
    page_size: int = typer.Option(20, "--limit", "-l", help="Items per page"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List connectors in the current project."""
    validate_pagination(page, page_size)
    client = ProjectClient(project_id)
    result = client.post(
        "connector/search",
        {
            "filters": {},
            "page": page,
            "page_size": page_size,
            "sorters": ["name", 1],
        },
    )

    items = extract_collection(result)

    if json_output:
        emit_json(items)
        return

    if not items:
        empty_state("connectors")
        return

    table = make_table("Connectors", expand=True)
    table.add_column("Name", ratio=2, overflow="ellipsis")
    table.add_column("Type", ratio=2, overflow="ellipsis")
    table.add_column("Status", no_wrap=True)
    table.add_column("ID", ratio=2, overflow="ellipsis")

    for item in items:
        status = item.get("status", item.get("enabled", ""))
        table.add_row(
            cell(item.get("name", ""), style="bold"),
            cell(item.get("type", item.get("connector_type", "")), style="dim"),
            status_cell(status),
            cell(item.get("_id", ""), style="dim"),
        )

    console.print(table)
    render_pagination(result, page=page, page_size=page_size, count=len(items), noun="connectors")


@app.command("get")
def get_connector(
    name: str = typer.Argument(..., help="Connector name"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
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

    console.print(
        Panel.fit(
            f"[bold]Name:[/bold] {item.get('name', 'N/A')}\n"
            f"[bold]Type:[/bold] {item.get('type', item.get('connector_type', 'N/A'))}\n"
            f"[bold]Status:[/bold] {item.get('status', 'N/A')}\n"
            f"[bold]ID:[/bold] {item.get('_id', 'N/A')}\n"
            f"[bold]Description:[/bold] {item.get('description', 'N/A')}",
            title="Connector",
            border_style="#FF5C1F",
        )
    )
