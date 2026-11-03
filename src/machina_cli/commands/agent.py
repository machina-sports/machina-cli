"""Agent management commands."""

import sys

import typer
from rich.panel import Panel
from rich.tree import Tree

from machina_cli import config_resources, execution_outcome
from machina_cli.project_client import ProjectAPIError, ProjectClient
from machina_cli.ui import (
    bool_cell,
    cell,
    console,
    datetime_cell,
    emit_json,
    empty_state,
    extract_collection,
    make_table,
    render_pagination,
    status_cell,
    validate_pagination,
)

app = typer.Typer(help="Agent management")


@app.command("list")
def list_agents(
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    page: int = typer.Option(1, "--page", help="Page number"),
    page_size: int = typer.Option(20, "--limit", "-l", help="Items per page"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List agents in the current project."""
    validate_pagination(page, page_size)
    client = ProjectClient(project_id)
    result = client.post(
        "agent/search",
        {
            "filters": {},
            "page": page,
            "page_size": page_size,
            "sorters": ["name", 1],
        },
    )

    agents = extract_collection(result)

    if json_output:
        emit_json(agents)
        return

    if not agents:
        empty_state("agents")
        return

    table = make_table("Agents", expand=True)
    table.add_column("Name", ratio=2, overflow="ellipsis")
    table.add_column("Title", ratio=2, overflow="ellipsis")
    table.add_column("Status", no_wrap=True)
    table.add_column("Scheduled", justify="center")
    table.add_column("Last Execution", no_wrap=True)
    table.add_column("ID", ratio=2, overflow="ellipsis")

    for agent in agents:
        table.add_row(
            cell(agent.get("name", ""), style="bold"),
            cell(agent.get("title", "")),
            status_cell(agent.get("status", "")),
            bool_cell(agent.get("scheduled")),
            datetime_cell(agent.get("last_execution", "")),
            cell(agent.get("_id", ""), style="dim"),
        )

    console.print(table)
    render_pagination(result, page=page, page_size=page_size, count=len(agents), noun="agents")


@app.command("get")
def get_agent(
    name: str = typer.Argument(..., help="Agent name or slug"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Get agent details by name — shows workflows, context, and activity."""
    client = ProjectClient(project_id)
    result = client.get(f"agent/{name}")

    data = result.get("data", result)

    if json_output:
        import json

        console.print_json(json.dumps(data, default=str))
        return

    agent = data if isinstance(data, dict) else {}
    if not agent:
        console.print("[yellow]Agent not found.[/yellow]")
        return

    # Status colors
    status = agent.get("status", "unknown")
    color = "green" if status == "active" else "yellow" if status == "inactive" else "dim"
    processing = agent.get("processing", False)
    proc_str = "[yellow]yes[/yellow]" if processing else "[dim]no[/dim]"
    scheduled = agent.get("scheduled", False)
    sched_str = "[green]yes[/green]" if scheduled else "[dim]no[/dim]"

    # Context frequency
    context = agent.get("context", {})
    frequency = context.get("config-frequency")
    freq_str = f"{frequency} min" if frequency else "N/A"

    # Header
    header = (
        f"[bold]Title:[/bold] {agent.get('title', agent.get('name', 'N/A'))}\n"
        f"[bold]Name:[/bold] {agent.get('name', 'N/A')}\n"
        f"[bold]Status:[/bold] [{color}]{status}[/{color}]"
        f"  [bold]Scheduled:[/bold] {sched_str}"
        f"  [bold]Processing:[/bold] {proc_str}"
        f"  [bold]Frequency:[/bold] {freq_str}\n"
        f"[bold]ID:[/bold] {agent.get('_id', 'N/A')}\n"
        f"[bold]Description:[/bold] {agent.get('description', 'N/A')}\n"
        f"[bold]Last Execution:[/bold] {str(agent.get('last_execution', 'N/A'))[:25]}\n"
        f"[bold]Created:[/bold] {str(agent.get('created', ''))[:25]}"
    )
    console.print(Panel(header, title=f"Agent: {agent.get('name', '')}", border_style="#FF5C1F"))

    # Workflows
    workflows = agent.get("workflows", [])
    if workflows:
        table = make_table(f"Workflows ({len(workflows)})", expand=True)
        table.add_column("#", width=3)
        table.add_column("Name", ratio=2, overflow="ellipsis")
        table.add_column("Description", ratio=3, overflow="fold")
        table.add_column("Condition", ratio=2, overflow="fold")

        for idx, wf in enumerate(workflows):
            if not isinstance(wf, dict):
                continue
            condition = wf.get("condition", "")
            cond_display = condition[:50] + "..." if len(condition) > 50 else condition
            table.add_row(
                cell(idx + 1, style="dim"),
                cell(wf.get("name", ""), style="bold"),
                cell(wf.get("description", "")[:60]),
                cell(cond_display, style="dim"),
            )
        console.print(table)

    # Context variables
    context_agent = agent.get("context-agent", {})
    if context_agent:
        tree = Tree("[bold]Context Variables[/bold]")
        for key, val in sorted(context_agent.items()):
            val_str = str(val)
            if len(val_str) > 60:
                val_str = val_str[:60] + "..."
            tree.add(f"[bold]{key}:[/bold] [dim]{val_str}[/dim]")
        console.print(tree)


@app.command("run")
def run_agent(
    name: str = typer.Argument(..., help="Agent name"),
    params: list[str] | None = typer.Argument(None, help="Parameters as key=value pairs"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    sync: bool = typer.Option(
        False, "--sync", "-s", help="Execute in the request, then report the run's real outcome"
    ),
    wait: bool = typer.Option(
        False, "--wait", help="Submit, then wait (bounded by --timeout) for the real outcome"
    ),
    watch: bool = typer.Option(False, "--watch", "-w", help="Same as --wait"),
    timeout: float = typer.Option(300.0, "--timeout", help="Max seconds for --wait/--sync"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Run an agent with optional parameters.

    If no params are provided, shows available inputs and prompts interactively.

    Submit-only (default): schedules the run and exits 0 with outcome "accepted"
    and the agent_run_id — the run is NOT complete; check it with
    `machina execution get <id>`. With --wait/--watch (or --sync) the command
    reports the run's persisted outcome and exits 0 completed, 1 failed,
    2 partial (some workflows did not complete), 3 timeout/unknown. A submit that
    times out is reported as unknown and never resubmitted.

    Examples:
        machina agent run my-agent
        machina agent run my-agent season_id=sr:season:123
        machina agent run my-agent --sync
        machina agent run my-agent --wait --timeout 600
        machina agent run my-agent force-competitors=true season_id=sr:season:123 --watch
    """
    client = ProjectClient(project_id)

    # Fetch agent to get available context-agent inputs
    try:
        agent_data = client.get(f"agent/{name}").get("data", {})
    except SystemExit:
        agent_data = {}

    available_inputs = agent_data.get("context-agent", {})

    # Parse key=value parameters
    context_agent = {}
    if params:
        for param in params:
            if "=" in param:
                key, value = param.split("=", 1)
                if value.lower() in ("true", "false"):
                    value = value.lower() == "true"
                elif value.isdigit():
                    value = int(value)
                context_agent[key] = value
            else:
                console.print(
                    f"  [yellow]Ignoring invalid param '{param}' (expected key=value)[/yellow]"
                )

    # Interactive mode: if no params and there are available inputs, show them
    if not params and available_inputs and sys.stdin.isatty():
        agent_title = agent_data.get("title", agent_data.get("name", name))
        agent_desc = agent_data.get("description", "")
        console.print()
        console.print(f"  [bold]Agent:[/bold] [#FF5C1F]{agent_title}[/#FF5C1F]")
        if agent_desc:
            console.print(f"  [dim]{agent_desc}[/dim]")
        console.print()
        console.print("  [bold]Available inputs:[/bold] [dim](press Enter to skip)[/dim]")
        console.print()

        for key, default_expr in available_inputs.items():
            hint = ""
            if isinstance(default_expr, str):  # noqa: SIM102 — nested ifs mirror the docs' decision tree
                # e.g. "$.get('force-competitors', False)" → default: False
                if "," in default_expr and "$.get(" in default_expr:
                    parts = default_expr.split(",", 1)
                    raw = parts[1].strip().rstrip(")")
                    if raw and raw not in ("None",):
                        hint = f" [dim](default: {raw})[/dim]"

            value = typer.prompt(f"  {key}{hint}", default="", show_default=False)
            if value:
                if value.lower() in ("true", "false"):
                    value = value.lower() == "true"
                elif value.isdigit():
                    value = int(value)
                context_agent[key] = value

        if not context_agent:
            console.print()
            console.print("  [dim]No inputs provided, running with defaults.[/dim]")

    # Build request body
    body = {}
    if context_agent:
        body["context-agent"] = context_agent

    if sync:
        body["agent-config"] = {"delay": False}
    else:
        body["agent-config"] = {"delay": True}

    if not json_output:  # --json keeps stdout to the one result document
        console.print()
        console.print(f"  [bold]Running agent:[/bold] [#FF5C1F]{name}[/#FF5C1F]")
        for k, v in context_agent.items():
            console.print(f"  [dim]{k}=[/dim]{v}")
        console.print()

    # Execute. Submit-only (default) returns an accepted run id; --sync and
    # --wait report the run record's real outcome and exit by it.
    path = f"agent/executor/{name}"
    try:
        if sync:
            with console.status("  Executing agent (sync)..."):
                result = execution_outcome.submit(client, path, body, timeout=timeout + 30)
        else:
            result = execution_outcome.submit(client, path, body)
    except execution_outcome.SubmissionUncertain:
        execution_outcome.uncertain("agent", json_output)

    data = result.get("data", result)
    data = data if isinstance(data, dict) else {"result": data}
    agent_run_id = data.get("agent_run_id") or data.get("runner_id") or ""
    if not agent_run_id:
        execution_outcome.uncertain("agent", json_output)

    run = None
    try:
        if sync:
            # The sync response never proved success: read the persisted run.
            run = execution_outcome.get_agent_run(client, agent_run_id)
            outcome = execution_outcome.agent_outcome(run)
            mode = "sync"
        elif wait or watch:
            with console.status("  Waiting for the run to finish..."):
                outcome, run = execution_outcome.wait_for("agent", client, agent_run_id, timeout)
            mode = "wait"
        else:
            outcome, mode = data.get("outcome") or "accepted", "submit"
    except (execution_outcome.PollFailed, ProjectAPIError) as exc:
        # The run was submitted; only reading its status failed: unknown (3).
        execution_outcome.poll_failed("agent", agent_run_id, exc, json_output)

    code = execution_outcome.report("agent", mode, outcome, agent_run_id, data, run, json_output)
    if code:
        raise typer.Exit(code)


@app.command("executions")
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

    table = make_table("Agent executions", expand=True)
    table.add_column("Name", ratio=2, overflow="ellipsis")
    table.add_column("Status", no_wrap=True)
    table.add_column("Time", justify="right", no_wrap=True)
    table.add_column("Workflows", justify="right", no_wrap=True)
    table.add_column("Created", no_wrap=True)
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
            datetime_cell(ex.get("date", ex.get("created", ""))),
            cell(ex.get("_id", ""), style="dim"),
        )

    console.print(table)
    render_pagination(
        result, page=page, page_size=page_size, count=len(executions), noun="executions"
    )


# --- configuration CRUD (see config_resources.py) ----------------------------


@app.command("create")
def create_agent(
    file: str = typer.Option(..., "--file", "-f", help="JSON file with the agent definition"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Create a agent from a JSON file and print the persisted record."""
    config_resources.create("agent", file, project_id, json_output)


@app.command("update")
def update_agent(
    ref: str = typer.Argument(..., help="Agent name or id"),
    file: str = typer.Option(..., "--file", "-f", help="JSON file with the fields to change"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Update a agent's configuration; omitted fields are kept.

    Never changes status/scheduling: a file that would change status, scheduled,
    processing or last_execution is refused (activation is a separate operation).
    """
    config_resources.update("agent", ref, file, project_id, json_output)


@app.command("delete")
def delete_agent(
    ref: str = typer.Argument(..., help="Agent name or id"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Delete a agent (asks for confirmation unless --yes)."""
    config_resources.delete("agent", ref, project_id, json_output, yes)
