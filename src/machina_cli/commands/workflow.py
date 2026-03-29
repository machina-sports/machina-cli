"""Workflow management commands."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from machina_cli.project_client import ProjectClient

app = typer.Typer(help="Workflow management")
console = Console()


@app.command("list")
def list_workflows(
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    page: int = typer.Option(1, "--page", help="Page number"),
    page_size: int = typer.Option(20, "--limit", "-l", help="Items per page"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List workflows in the current project."""
    client = ProjectClient(project_id)
    result = client.post("workflow/search", {
        "filters": {},
        "page": page,
        "page_size": page_size,
        "sorters": ["name", 1],
    })

    workflows = result.get("data", [])

    if json_output:
        import json
        console.print_json(json.dumps(workflows, default=str))
        return

    if not workflows:
        console.print("[yellow]No workflows found.[/yellow]")
        return

    table = Table(title="Workflows")
    table.add_column("Name", style="bold")
    table.add_column("Slug", style="dim")
    table.add_column("Status")
    table.add_column("ID", style="dim")

    for wf in workflows:
        status = wf.get("status", "")
        color = "green" if status == "active" else "yellow" if status == "draft" else "dim"
        table.add_row(
            wf.get("name", ""),
            wf.get("slug", ""),
            f"[{color}]{status}[/{color}]",
            wf.get("_id", ""),
        )

    console.print(table)

    pagination = result.get("pagination", {})
    total = pagination.get("total", pagination.get("total_documents", 0))
    if total:
        console.print(f"\n  [dim]Showing page {page} ({len(workflows)} of {total} workflows)[/dim]")


@app.command("get")
def get_workflow(
    name: str = typer.Argument(..., help="Workflow name or slug"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Get workflow details by name."""
    client = ProjectClient(project_id)
    result = client.get(f"workflow/{name}")

    data = result.get("data", result)

    if json_output:
        import json
        console.print_json(json.dumps(data, default=str))
        return

    wf = data if not isinstance(data, list) else data[0] if data else {}

    console.print(Panel.fit(
        f"[bold]Name:[/bold] {wf.get('name', 'N/A')}\n"
        f"[bold]Slug:[/bold] {wf.get('slug', 'N/A')}\n"
        f"[bold]Status:[/bold] {wf.get('status', 'N/A')}\n"
        f"[bold]ID:[/bold] {wf.get('_id', 'N/A')}\n"
        f"[bold]Description:[/bold] {wf.get('description', 'N/A')}",
        title="Workflow",
        border_style="#FF5C1F",
    ))
