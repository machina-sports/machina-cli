"""Workflow management commands."""

import json as json_lib
import sys
import time
from typing import Optional, List

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
        console.print_json(json_lib.dumps(workflows, default=str))
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
        console.print(f"\n  [dim]Page {page} ({len(workflows)} of {total} workflows)[/dim]")


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
        console.print_json(json_lib.dumps(data, default=str))
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


@app.command("run")
def run_workflow(
    name: str = typer.Argument(..., help="Workflow name"),
    params: Optional[List[str]] = typer.Argument(None, help="Parameters as key=value pairs"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    sync: bool = typer.Option(True, "--sync/--async", "-s/-a", help="Sync (wait) or async (schedule)"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Watch async execution progress"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Run a workflow with optional parameters.

    If no params are provided, shows available inputs and prompts interactively.

    Examples:
        machina workflow run my-workflow
        machina workflow run my-workflow season_id=sr:season:123
        machina workflow run my-workflow --async
        machina workflow run my-workflow --async --watch
    """
    client = ProjectClient(project_id)

    # Fetch workflow to get available inputs
    try:
        wf_data = client.get(f"workflow/{name}").get("data", {})
    except SystemExit:
        wf_data = {}

    available_inputs = wf_data.get("inputs", {})

    # Parse key=value parameters
    context = {}
    if params:
        for param in params:
            if "=" in param:
                key, value = param.split("=", 1)
                if value.lower() in ("true", "false"):
                    value = value.lower() == "true"
                elif value.isdigit():
                    value = int(value)
                context[key] = value
            else:
                console.print(f"  [yellow]Ignoring invalid param '{param}' (expected key=value)[/yellow]")

    # Interactive mode: if no params and there are available inputs, show them
    if not params and available_inputs and sys.stdin.isatty():
        wf_title = wf_data.get("name", name)
        wf_desc = wf_data.get("description", "")
        console.print()
        console.print(f"  [bold]Workflow:[/bold] [#FF5C1F]{wf_title}[/#FF5C1F]")
        if wf_desc:
            console.print(f"  [dim]{wf_desc}[/dim]")
        console.print()
        console.print("  [bold]Available inputs:[/bold] [dim](press Enter to skip)[/dim]")
        console.print()

        for key, default_expr in available_inputs.items():
            # Extract a readable default hint from the expression
            hint = ""
            if isinstance(default_expr, str):
                # e.g. "$.get('limit', 50)" → default: 50
                if "," in default_expr and "$.get(" in default_expr:
                    parts = default_expr.split(",", 1)
                    raw = parts[1].strip().rstrip(")")
                    if raw and raw not in ("None", "{}"):
                        hint = f" [dim](default: {raw})[/dim]"

            value = typer.prompt(f"  {key}{hint}", default="", show_default=False)
            if value:
                if value.lower() in ("true", "false"):
                    value = value.lower() == "true"
                elif value.isdigit():
                    value = int(value)
                context[key] = value

        if not context:
            console.print()
            console.print("  [dim]No inputs provided, running with defaults.[/dim]")

    body = {}
    if context:
        body["context-workflow"] = context

    console.print()
    console.print(f"  [bold]Running workflow:[/bold] [#FF5C1F]{name}[/#FF5C1F]")
    if context:
        for k, v in context.items():
            console.print(f"  [dim]{k}=[/dim]{v}")
    mode = "sync" if sync else "async"
    console.print(f"  [dim]Mode:[/dim] {mode}")
    console.print()

    # Choose endpoint based on mode
    if sync:
        endpoint = f"workflow/execute/{name}"
        with console.status("  Executing workflow..."):
            result = client.post(endpoint, body)
    else:
        endpoint = f"workflow/schedule/{name}"
        result = client.post(endpoint, body)

    data = result.get("data", result)

    if json_output:
        console.print_json(json_lib.dumps(data, default=str))
        return

    workflow_run_id = data.get("workflow_run_id", data.get("_id", ""))
    status = data.get("status", "scheduled" if not sync else "executed")
    color = "green" if status in ("executed", "completed") else "yellow" if status == "scheduled" else "red"

    console.print(Panel(
        f"[bold]Status:[/bold] [{color}]{status}[/{color}]\n"
        f"[bold]Workflow Run ID:[/bold] {workflow_run_id}",
        title="Workflow " + ("Complete" if sync else "Scheduled"),
        border_style="#FF5C1F",
    ))

    # Show response for sync execution
    if sync:
        # Filter out internal fields, show the workflow output
        output = {k: v for k, v in data.items()
                  if k not in ("workflow_run_id", "_id", "status", "message")}
        if output:
            formatted = json_lib.dumps(output, indent=2, default=str, ensure_ascii=False)
            if len(formatted) > 3000:
                formatted = formatted[:3000] + "\n... (use --json for full output)"
            from rich.syntax import Syntax
            console.print(Panel(Syntax(formatted, "json", theme="monokai"), title="Output"))

    # Async: show tracking hint
    if not sync and workflow_run_id:
        console.print(f"  [dim]Track with:[/dim] [bold]machina execution get {workflow_run_id}[/bold]")

    # Watch mode for async
    if watch and not sync and workflow_run_id:
        console.print()
        elapsed = 0
        with console.status("  Watching execution..."):
            while elapsed < 300:
                time.sleep(3)
                elapsed += 3
                try:
                    run_result = client.get(f"workflow/schedule/{workflow_run_id}")
                    run_data = run_result.get("data", {})
                    run_status = run_data.get("status", "")

                    if run_status in ("executed", "completed", "failed"):
                        console.print()
                        run_color = "green" if run_status in ("executed", "completed") else "red"
                        console.print(Panel(
                            f"[bold]Status:[/bold] [{run_color}]{run_status}[/{run_color}]",
                            title="Execution Complete",
                            border_style="#FF5C1F",
                        ))

                        output = run_data.get("workflow_output", {})
                        if output:
                            formatted = json_lib.dumps(output, indent=2, default=str, ensure_ascii=False)
                            from rich.syntax import Syntax
                            console.print(Panel(Syntax(formatted, "json", theme="monokai"), title="Output"))
                        break
                except Exception:
                    pass

            if elapsed >= 300:
                console.print("  [yellow]Timed out. Workflow may still be running.[/yellow]")
                console.print(f"  [dim]Check with:[/dim] [bold]machina execution get {workflow_run_id}[/bold]")
