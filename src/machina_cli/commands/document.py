"""Document management commands."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from machina_cli.project_client import ProjectClient

app = typer.Typer(help="Document management")
console = Console()


@app.command("list")
def list_documents(
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    page: int = typer.Option(1, "--page", help="Page number"),
    page_size: int = typer.Option(20, "--limit", "-l", help="Items per page"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List documents in the current project."""
    client = ProjectClient(project_id)
    result = client.post("document/search", {
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
        console.print("[yellow]No documents found.[/yellow]")
        return

    table = Table(title="Documents")
    table.add_column("Name", style="bold")
    table.add_column("Type", style="dim")
    table.add_column("Status")
    table.add_column("ID", style="dim")

    for item in items:
        status = item.get("status", "")
        color = "green" if status == "active" else "dim"
        table.add_row(
            item.get("name", item.get("title", "")),
            item.get("type", item.get("document_type", item.get("filetype", ""))),
            f"[{color}]{status}[/{color}]",
            item.get("_id", ""),
        )

    console.print(table)

    pagination = result.get("pagination", {})
    total = pagination.get("total", pagination.get("total_documents", 0))
    if total:
        console.print(f"\n  [dim]Page {page} ({len(items)} of {total} documents)[/dim]")


@app.command("get")
def get_document(
    doc_id: str = typer.Argument(..., help="Document ID"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Get document details by ID."""
    client = ProjectClient(project_id)
    result = client.get(f"document/{doc_id}")

    data = result.get("data", result)

    if json_output:
        import json
        console.print_json(json.dumps(data, default=str))
        return

    item = data if isinstance(data, dict) else {}

    console.print(Panel.fit(
        f"[bold]Name:[/bold] {item.get('name', item.get('title', 'N/A'))}\n"
        f"[bold]Type:[/bold] {item.get('type', item.get('document_type', item.get('filetype', 'N/A')))}\n"
        f"[bold]Status:[/bold] {item.get('status', 'N/A')}\n"
        f"[bold]ID:[/bold] {item.get('_id', 'N/A')}\n"
        f"[bold]Created:[/bold] {str(item.get('created', ''))[:19]}",
        title="Document",
        border_style="#FF5C1F",
    ))

    # Show content preview if available
    content = item.get("content", item.get("text", ""))
    if content and isinstance(content, str):
        if len(content) > 2000:
            content = content[:2000] + "\n... (use --json for full content)"
        console.print(Panel(content, title="Content"))
