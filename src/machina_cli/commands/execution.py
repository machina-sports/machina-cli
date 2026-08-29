"""Execution management commands."""

import typer
from rich.panel import Panel
from rich.syntax import Syntax

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

app = typer.Typer(help="Execution management")


@app.command("get")
def get_execution(
    execution_id: str = typer.Argument(..., help="Agent execution ID"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    compact: bool = typer.Option(
        False, "--compact", "-c", help="Compact output (no workflow details)"
    ),
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
    color = (
        "green"
        if status in ("agent-executed", "completed", "success")
        else "red"
        if "fail" in status
        else "yellow"
    )

    # Execution time formatting
    exec_time = data.get("execution_time")
    exec_time_str = (
        f"{exec_time:.1f}s" if isinstance(exec_time, (int, float)) else str(exec_time or "N/A")
    )

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
        table = make_table(f"Workflows ({len(workflows)})", expand=True)
        table.add_column("#", width=3)
        table.add_column("Name", ratio=2, overflow="ellipsis")
        table.add_column("Status", no_wrap=True)
        table.add_column("Time", justify="right", no_wrap=True)
        table.add_column("ID", ratio=2, overflow="ellipsis")

        for idx, wf in enumerate(workflows):
            if not isinstance(wf, dict):
                continue
            wf_status = wf.get("status", "")
            wf_time = wf.get("execution_time")
            wf_time_str = f"{wf_time:.1f}s" if isinstance(wf_time, (int, float)) else ""
            table.add_row(
                cell(idx + 1, style="dim"),
                cell(wf.get("name", ""), style="bold"),
                status_cell(wf_status),
                cell(wf_time_str, style="dim"),
                cell(wf.get("_id", ""), style="dim"),
            )
        console.print(table)


@app.command("list")
def list_executions(
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    page: int = typer.Option(1, "--page", help="Page number"),
    page_size: int = typer.Option(20, "--limit", "-l", help="Items per page"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List recent agent executions."""
    validate_pagination(page, page_size)
    client = ProjectClient(project_id)
    result = client.post(
        "execution/agent-search",
        {
            "filters": {},
            "page": page,
            "page_size": page_size,
            "sorters": ["_id", -1],
        },
    )

    executions = extract_collection(result)

    if json_output:
        emit_json(executions)
        return

    if not executions:
        empty_state("executions")
        return

    table = make_table("Executions", expand=True)
    table.add_column("Name", ratio=2, overflow="ellipsis")
    table.add_column("Status", no_wrap=True)
    table.add_column("Time", justify="right", no_wrap=True)
    table.add_column("Workflows", justify="right", no_wrap=True)
    table.add_column("ID", ratio=2, overflow="ellipsis")

    for ex in executions:
        status = ex.get("status", "")
        exec_time = ex.get("execution_time")
        time_str = f"{exec_time:.1f}s" if isinstance(exec_time, (int, float)) else ""
        total_wf = ex.get("total_workflows")
        completed_wf = ex.get("completed_workflows")
        wf_str = f"{completed_wf}/{total_wf}" if total_wf else ""
        table.add_row(
            cell(ex.get("name", ""), style="bold"),
            status_cell(status),
            cell(time_str, style="dim"),
            cell(wf_str, style="dim"),
            cell(ex.get("_id", ""), style="dim"),
        )

    console.print(table)
    render_pagination(
        result, page=page, page_size=page_size, count=len(executions), noun="executions"
    )
