"""Prompt management commands."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax

from machina_cli.project_client import ProjectClient

app = typer.Typer(help="Prompt management")
console = Console()


@app.command("list")
def list_prompts(
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    page: int = typer.Option(1, "--page", help="Page number"),
    page_size: int = typer.Option(20, "--limit", "-l", help="Items per page"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List prompts in the current project."""
    client = ProjectClient(project_id)
    result = client.post("prompt/search", {
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
        console.print("[yellow]No prompts found.[/yellow]")
        return

    table = Table(title="Prompts")
    table.add_column("Name", style="bold")
    table.add_column("Model", style="dim")
    table.add_column("Status")
    table.add_column("ID", style="dim")

    for item in items:
        status = item.get("status", "")
        color = "green" if status == "active" else "dim"
        table.add_row(
            item.get("name", ""),
            item.get("model", item.get("llm_model", "")),
            f"[{color}]{status}[/{color}]",
            item.get("_id", ""),
        )

    console.print(table)

    pagination = result.get("pagination", {})
    total = pagination.get("total", pagination.get("total_documents", 0))
    if total:
        console.print(f"\n  [dim]Page {page} ({len(items)} of {total} prompts)[/dim]")


@app.command("get")
def get_prompt(
    name: str = typer.Argument(..., help="Prompt name"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Get prompt details by name."""
    client = ProjectClient(project_id)
    result = client.get(f"prompt/{name}")

    data = result.get("data", result)

    if json_output:
        import json
        console.print_json(json.dumps(data, default=str))
        return

    item = data if isinstance(data, dict) else {}

    # Header
    console.print(Panel.fit(
        f"[bold]Name:[/bold] {item.get('name', 'N/A')}\n"
        f"[bold]Model:[/bold] {item.get('model', item.get('llm_model', 'N/A'))}\n"
        f"[bold]Status:[/bold] {item.get('status', 'N/A')}\n"
        f"[bold]ID:[/bold] {item.get('_id', 'N/A')}",
        title="Prompt",
        border_style="#FF5C1F",
    ))

    # Show prompt content if available
    content = item.get("prompt", item.get("system_prompt", item.get("content", "")))
    if content and isinstance(content, str):
        if len(content) > 3000:
            content = content[:3000] + "\n... (use --json for full content)"
        console.print(Panel(content, title="Content"))
