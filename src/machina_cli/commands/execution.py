"""Execution management commands."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax

from machina_cli.project_client import ProjectClient

app = typer.Typer(help="Execution management")
console = Console()


@app.command("get")
def get_execution(
    execution_id: str = typer.Argument(..., help="Workflow execution ID"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    compact: bool = typer.Option(False, "--compact", "-c", help="Compact output (less detail)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Get execution details by workflow ID."""
    client = ProjectClient(project_id)
    compact_param = "true" if compact else "false"
    result = client.get(f"execution/workflow/{execution_id}?compact={compact_param}")

    data = result.get("data", result)

    if json_output:
        import json
        console.print_json(json.dumps(data, default=str))
        return

    # Handle single execution or list
    executions = data if isinstance(data, list) else [data] if isinstance(data, dict) else []

    if not executions:
        console.print("[yellow]No execution data found.[/yellow]")
        return

    for i, ex in enumerate(executions):
        if not isinstance(ex, dict):
            continue

        status = ex.get("status", "unknown")
        color = "green" if status in ("completed", "success") else "red" if status in ("failed", "error") else "yellow"

        # Header panel
        header = (
            f"[bold]Status:[/bold] [{color}]{status}[/{color}]\n"
            f"[bold]ID:[/bold] {ex.get('_id', 'N/A')}\n"
            f"[bold]Workflow:[/bold] {ex.get('workflow_name', ex.get('workflow_slug', ex.get('workflow_id', 'N/A')))}\n"
            f"[bold]Agent:[/bold] {ex.get('agent_name', ex.get('agent_slug', 'N/A'))}\n"
            f"[bold]Created:[/bold] {str(ex.get('created', ex.get('created_at', '')))[:19]}\n"
            f"[bold]Updated:[/bold] {str(ex.get('updated', ex.get('updated_at', '')))[:19]}"
        )
        console.print(Panel(header, title=f"Execution {i + 1}", border_style="#FF5C1F"))

        # Steps / Tasks
        steps = ex.get("steps", ex.get("tasks", ex.get("nodes", [])))
        if steps and isinstance(steps, list):
            table = Table(title="Steps")
            table.add_column("#", style="dim", width=4)
            table.add_column("Name", style="bold")
            table.add_column("Status")
            table.add_column("Duration", style="dim")

            for idx, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                step_status = step.get("status", "")
                step_color = "green" if step_status in ("completed", "success") else "red" if step_status in ("failed", "error") else "yellow"
                duration = step.get("duration", step.get("elapsed", ""))
                table.add_row(
                    str(idx + 1),
                    step.get("name", step.get("slug", step.get("node_name", ""))),
                    f"[{step_color}]{step_status}[/{step_color}]",
                    f"{duration}ms" if duration else "",
                )
            console.print(table)

        # Output / Result
        output = ex.get("output", ex.get("result", ex.get("response", None)))
        if output:
            if isinstance(output, dict) or isinstance(output, list):
                import json
                formatted = json.dumps(output, indent=2, default=str, ensure_ascii=False)
                if len(formatted) > 2000:
                    formatted = formatted[:2000] + "\n... (truncated, use --json for full output)"
                console.print(Panel(Syntax(formatted, "json", theme="monokai"), title="Output"))
            elif isinstance(output, str):
                if len(output) > 2000:
                    output = output[:2000] + "\n... (truncated)"
                console.print(Panel(output, title="Output"))

        if i < len(executions) - 1:
            console.print()


@app.command("list")
def list_executions(
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    page: int = typer.Option(1, "--page", help="Page number"),
    page_size: int = typer.Option(20, "--limit", "-l", help="Items per page"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List recent agent executions."""
    client = ProjectClient(project_id)
    result = client.post("execution/agent-search", {
        "filters": {},
        "page": page,
        "page_size": page_size,
        "sorters": ["_id", -1],
    })

    executions = result.get("data", [])

    if json_output:
        import json
        console.print_json(json.dumps(executions, default=str))
        return

    if not executions:
        console.print("[yellow]No executions found.[/yellow]")
        return

    table = Table(title="Executions")
    table.add_column("ID", style="dim")
    table.add_column("Agent/Workflow", style="bold")
    table.add_column("Status")
    table.add_column("Created", style="dim")

    for ex in executions:
        status = ex.get("status", "")
        color = "green" if status in ("completed", "success") else "red" if status in ("failed", "error") else "yellow"
        name = ex.get("agent_name", ex.get("workflow_name", ex.get("agent_slug", "")))
        table.add_row(
            ex.get("_id", ""),
            name,
            f"[{color}]{status}[/{color}]",
            str(ex.get("created", ex.get("created_at", "")))[:19],
        )

    console.print(table)

    pagination = result.get("pagination", {})
    total = pagination.get("total", pagination.get("total_documents", 0))
    if total:
        console.print(f"\n  [dim]Showing page {page} ({len(executions)} of {total} executions)[/dim]")
