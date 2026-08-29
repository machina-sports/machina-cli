"""Prompt management commands."""

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

app = typer.Typer(help="Prompt management")


@app.command("list")
def list_prompts(
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    page: int = typer.Option(1, "--page", help="Page number"),
    page_size: int = typer.Option(20, "--limit", "-l", help="Items per page"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List prompts in the current project."""
    validate_pagination(page, page_size)
    client = ProjectClient(project_id)
    result = client.post(
        "prompt/search",
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
        empty_state("prompts")
        return

    table = make_table("Prompts", expand=True)
    table.add_column("Name", ratio=2, overflow="ellipsis")
    table.add_column("Model", ratio=2, overflow="ellipsis")
    table.add_column("Status", no_wrap=True)
    table.add_column("ID", ratio=2, overflow="ellipsis")

    for item in items:
        table.add_row(
            cell(item.get("name", ""), style="bold"),
            cell(item.get("model", item.get("llm_model", "")), style="dim"),
            status_cell(item.get("status", "")),
            cell(item.get("_id", ""), style="dim"),
        )

    console.print(table)
    render_pagination(result, page=page, page_size=page_size, count=len(items), noun="prompts")


@app.command("get")
def get_prompt(
    name: str = typer.Argument(..., help="Prompt name"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
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
    console.print(
        Panel.fit(
            f"[bold]Name:[/bold] {item.get('name', 'N/A')}\n"
            f"[bold]Model:[/bold] {item.get('model', item.get('llm_model', 'N/A'))}\n"
            f"[bold]Status:[/bold] {item.get('status', 'N/A')}\n"
            f"[bold]ID:[/bold] {item.get('_id', 'N/A')}",
            title="Prompt",
            border_style="#FF5C1F",
        )
    )

    # Show prompt content if available
    content = item.get("prompt", item.get("system_prompt", item.get("content", "")))
    if content and isinstance(content, str):
        if len(content) > 3000:
            content = content[:3000] + "\n... (use --json for full content)"
        console.print(Panel(content, title="Content"))
