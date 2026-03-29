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
    execution_id: str = typer.Argument(..., help="Agent execution ID"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    compact: bool = typer.Option(False, "--compact", "-c", help="Compact output (no workflow details)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Get execution details by ID."""
    client = ProjectClient(project_id)
    compact_param = "true" if compact else "false"
    result = client.get(f"execution/agent-run/{execution_id}?compact={compact_param}")

    data = result.get("data", result)

    if json_output:
        import json
        console.print_json(json.dumps(data, default=str))
        return

    if not data or not isinstance(data, dict):
        console.print("[yellow]No execution data found.[/yellow]")
        return

    status = data.get("status", "unknown")
    color = "green" if status in ("agent-executed", "completed", "success") else "red" if "fail" in status else "yellow"

    # Execution time formatting
    exec_time = data.get("execution_time")
    exec_time_str = f"{exec_time:.1f}s" if isinstance(exec_time, (int, float)) else str(exec_time or "N/A")

    # Tokens
    tokens = data.get("execution_tokens", {})
    tokens_str = ""
    if tokens and isinstance(tokens, dict):
        total = tokens.get("total_tokens", 0)
        if total:
            tokens_str = f"\n[bold]Tokens:[/bold] {total:,} total ({tokens.get('prompt_tokens', 0):,} prompt, {tokens.get('completion_tokens', 0):,} completion)"

    # Workflow count
    total_wf = data.get("total_workflows") or 0
    completed_wf = data.get("completed_workflows") or 0
    wf_str = f"{completed_wf}/{total_wf}" if total_wf else "N/A"

    header = (
        f"[bold]Name:[/bold] {data.get('name', 'N/A')}\n"
        f"[bold]Status:[/bold] [{color}]{status}[/{color}]\n"
        f"[bold]ID:[/bold] {data.get('_id', 'N/A')}\n"
        f"[bold]Time:[/bold] {exec_time_str}\n"
        f"[bold]Workflows:[/bold] {wf_str}\n"
        f"[bold]Started:[/bold] {str(data.get('started_time', ''))[:19]}\n"
        f"[bold]Finished:[/bold] {str(data.get('finished_time', ''))[:19]}"
        f"{tokens_str}"
    )
    console.print(Panel(header, title="Execution", border_style="#FF5C1F"))

    # Response / output
    response = data.get("response")
    if response and isinstance(response, dict):
        import json
        formatted = json.dumps(response, indent=2, default=str, ensure_ascii=False)
        if len(formatted) > 2000:
            formatted = formatted[:2000] + "\n... (use --json for full output)"
        console.print(Panel(Syntax(formatted, "json", theme="monokai"), title="Response"))

    # Workflow list (if not compact)
    workflows = data.get("workflows", [])
    if workflows and not compact:
        table = Table(title=f"Workflows ({len(workflows)})")
        table.add_column("#", style="dim", width=3)
        table.add_column("Name", style="bold")
        table.add_column("Status")
        table.add_column("Time", style="dim")
        table.add_column("ID", style="dim")

        for idx, wf in enumerate(workflows):
            if not isinstance(wf, dict):
                continue
            wf_status = wf.get("status", "")
            wf_color = "green" if wf_status in ("completed", "success") else "red" if "fail" in wf_status else "yellow"
            wf_time = wf.get("execution_time")
            wf_time_str = f"{wf_time:.1f}s" if isinstance(wf_time, (int, float)) else ""
            table.add_row(
                str(idx + 1),
                wf.get("name", ""),
                f"[{wf_color}]{wf_status}[/{wf_color}]",
                wf_time_str,
                wf.get("_id", ""),
            )
        console.print(table)


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
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Time", style="dim")
    table.add_column("Workflows", justify="right", style="dim")

    for ex in executions:
        status = ex.get("status", "")
        color = "green" if status in ("agent-executed", "completed", "success") else "red" if "fail" in status else "yellow"
        exec_time = ex.get("execution_time")
        time_str = f"{exec_time:.1f}s" if isinstance(exec_time, (int, float)) else ""
        total_wf = ex.get("total_workflows")
        completed_wf = ex.get("completed_workflows")
        wf_str = f"{completed_wf}/{total_wf}" if total_wf else ""
        table.add_row(
            ex.get("_id", ""),
            ex.get("name", ""),
            f"[{color}]{status}[/{color}]",
            time_str,
            wf_str,
        )

    console.print(table)

    pagination = result.get("pagination", {})
    total = pagination.get("total", pagination.get("total_documents", 0))
    if total:
        console.print(f"\n  [dim]Page {page} ({len(executions)} of {total} executions)[/dim]")
