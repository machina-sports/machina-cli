"""Workflow management commands."""

import json as json_lib
import sys

import typer
from rich.panel import Panel

from machina_cli import config_resources, execution_outcome
from machina_cli.project_client import ProjectAPIError, ProjectClient
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

app = typer.Typer(help="Workflow management")


@app.command("list")
def list_workflows(
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    page: int = typer.Option(1, "--page", help="Page number"),
    page_size: int = typer.Option(20, "--limit", "-l", help="Items per page"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List workflows in the current project."""
    validate_pagination(page, page_size)
    client = ProjectClient(project_id)
    result = client.post(
        "workflow/search",
        {
            "filters": {},
            "page": page,
            "page_size": page_size,
            "sorters": ["name", 1],
        },
    )

    workflows = extract_collection(result)

    if json_output:
        emit_json(workflows)
        return

    if not workflows:
        empty_state("workflows")
        return

    table = make_table("Workflows", expand=True)
    table.add_column("Name", ratio=2, overflow="ellipsis")
    table.add_column("Slug", ratio=2, overflow="ellipsis")
    table.add_column("Status", no_wrap=True)
    table.add_column("ID", ratio=2, overflow="ellipsis")

    for wf in workflows:
        table.add_row(
            cell(wf.get("name", ""), style="bold"),
            cell(wf.get("slug", ""), style="dim"),
            status_cell(wf.get("status", "")),
            cell(wf.get("_id", ""), style="dim"),
        )

    console.print(table)
    render_pagination(
        result, page=page, page_size=page_size, count=len(workflows), noun="workflows"
    )


@app.command("get")
def get_workflow(
    name: str = typer.Argument(..., help="Workflow name or slug"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
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

    console.print(
        Panel.fit(
            f"[bold]Name:[/bold] {wf.get('name', 'N/A')}\n"
            f"[bold]Slug:[/bold] {wf.get('slug', 'N/A')}\n"
            f"[bold]Status:[/bold] {wf.get('status', 'N/A')}\n"
            f"[bold]ID:[/bold] {wf.get('_id', 'N/A')}\n"
            f"[bold]Description:[/bold] {wf.get('description', 'N/A')}",
            title="Workflow",
            border_style="#FF5C1F",
        )
    )


@app.command("run")
def run_workflow(
    name: str = typer.Argument(..., help="Workflow name"),
    params: list[str] | None = typer.Argument(None, help="Parameters as key=value pairs"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    sync: bool = typer.Option(
        True, "--sync/--async", "-s/-a", help="Sync (wait) or async (schedule)"
    ),
    wait: bool = typer.Option(
        False, "--wait", help="With --async: wait (bounded by --timeout) for the real outcome"
    ),
    watch: bool = typer.Option(False, "--watch", "-w", help="Same as --wait"),
    timeout: float = typer.Option(300.0, "--timeout", help="Max seconds for sync/--wait"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Run a workflow with optional parameters.

    If no params are provided, shows available inputs and prompts interactively.

    Sync (default) executes in the request, then reads the persisted run: exit 0
    completed, 1 failed, 3 unknown. --async is submit-only: exit 0 with outcome
    "accepted" and a workflow_run_id — NOT complete; check it with
    `machina execution get --workflow <id>`. --async --wait/--watch waits for the
    real outcome (3 on timeout). A submit that times out is reported as unknown
    and never resubmitted.

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
                console.print(
                    f"  [yellow]Ignoring invalid param '{param}' (expected key=value)[/yellow]"
                )

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
            if isinstance(default_expr, str):  # noqa: SIM102 — nested ifs mirror the docs' decision tree
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

    if not json_output:  # --json keeps stdout to the one result document
        console.print()
        console.print(f"  [bold]Running workflow:[/bold] [#FF5C1F]{name}[/#FF5C1F]")
        for k, v in context.items():
            console.print(f"  [dim]{k}=[/dim]{v}")
        console.print(f"  [dim]Mode:[/dim] {'sync' if sync else 'async'}")
        console.print()

    # Execute. --async without --wait is submit-only (exit 0, outcome
    # "accepted"); sync and --wait report the persisted run's real outcome.
    try:
        if sync:
            with console.status("  Executing workflow..."):
                result = execution_outcome.submit(
                    client, f"workflow/execute/{name}", body, timeout=timeout + 30
                )
        else:
            result = execution_outcome.submit(client, f"workflow/schedule/{name}", body)
    except execution_outcome.SubmissionUncertain:
        execution_outcome.uncertain("workflow", json_output)

    data = result.get("data", result)
    data = data if isinstance(data, dict) else {"result": data}
    workflow_run_id = data.get("workflow_run_id", data.get("_id", ""))
    if not workflow_run_id:
        execution_outcome.uncertain("workflow", json_output)

    run = None
    try:
        if sync:
            # The execute response says "scheduled"/success even when the run
            # failed: the persisted run record is the truth.
            run = execution_outcome.get_workflow_run(client, workflow_run_id)
            outcome = execution_outcome.workflow_outcome(run)
            mode = "sync"
        elif wait or watch:
            with console.status("  Waiting for the run to finish..."):
                outcome, run = execution_outcome.wait_for(
                    "workflow", client, workflow_run_id, timeout
                )
            mode = "wait"
        else:
            outcome, mode = data.get("outcome") or "accepted", "submit"
    except (execution_outcome.PollFailed, ProjectAPIError) as exc:
        # The run was submitted; only reading its status failed: unknown (3).
        execution_outcome.poll_failed("workflow", workflow_run_id, exc, json_output)

    code = execution_outcome.report(
        "workflow", mode, outcome, workflow_run_id, data, run, json_output
    )
    if not json_output and outcome in ("completed", "partial"):
        output = {
            k: v
            for k, v in (run or data).items()
            if k
            not in (
                "workflow_run_id",
                "_id",
                "status",
                "message",
                "outcome",
                "request_data",
                "workflow_object",
                "audit",
            )
        }
        if output:
            formatted = json_lib.dumps(output, indent=2, default=str, ensure_ascii=False)
            if len(formatted) > 3000:
                formatted = formatted[:3000] + "\n... (use --json for full output)"
            from rich.syntax import Syntax

            console.print(Panel(Syntax(formatted, "json", theme="monokai"), title="Output"))
    if code:
        raise typer.Exit(code)


# --- configuration CRUD (see config_resources.py) ----------------------------


@app.command("create")
def create_workflow(
    file: str = typer.Option(..., "--file", "-f", help="JSON file with the workflow definition"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Create a workflow from a JSON file and print the persisted record."""
    config_resources.create("workflow", file, project_id, json_output)


@app.command("update")
def update_workflow(
    ref: str = typer.Argument(..., help="Workflow name or id"),
    file: str = typer.Option(..., "--file", "-f", help="JSON file with the fields to change"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Update a workflow's configuration; omitted fields are kept.

    Never changes status/scheduling: a file that would change status, scheduled,
    processing or last_execution is refused (activation is a separate operation).
    """
    config_resources.update("workflow", ref, file, project_id, json_output)


@app.command("delete")
def delete_workflow(
    ref: str = typer.Argument(..., help="Workflow name or id"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Delete a workflow (asks for confirmation unless --yes)."""
    config_resources.delete("workflow", ref, project_id, json_output, yes)
