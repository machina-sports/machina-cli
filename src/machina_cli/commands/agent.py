"""Agent management commands."""

import json as json_lib
import sys
import time
from typing import Optional, List

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.tree import Tree

from machina_cli.project_client import ProjectClient

app = typer.Typer(help="Agent management")
console = Console()


@app.command("list")
def list_agents(
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    page: int = typer.Option(1, "--page", help="Page number"),
    page_size: int = typer.Option(20, "--limit", "-l", help="Items per page"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List agents in the current project."""
    client = ProjectClient(project_id)
    result = client.post("agent/search", {
        "filters": {},
        "page": page,
        "page_size": page_size,
        "sorters": ["name", 1],
    })

    agents = result.get("data", [])

    if json_output:
        import json
        console.print_json(json.dumps(agents, default=str))
        return

    if not agents:
        console.print("[yellow]No agents found.[/yellow]")
        return

    table = Table(title="Agents")
    table.add_column("Name", style="bold")
    table.add_column("Title")
    table.add_column("Status")
    table.add_column("Scheduled", justify="center")
    table.add_column("Last Execution", style="dim")
    table.add_column("ID", style="dim")

    for agent in agents:
        status = agent.get("status", "")
        color = "green" if status == "active" else "yellow" if status == "inactive" else "dim"
        scheduled = "yes" if agent.get("scheduled") else "no"
        sched_color = "green" if agent.get("scheduled") else "dim"
        last_exec = str(agent.get("last_execution", ""))[:19]
        table.add_row(
            agent.get("name", ""),
            agent.get("title", ""),
            f"[{color}]{status}[/{color}]",
            f"[{sched_color}]{scheduled}[/{sched_color}]",
            last_exec,
            agent.get("_id", ""),
        )

    console.print(table)

    pagination = result.get("pagination", {})
    total = pagination.get("total", pagination.get("total_documents", 0))
    if total:
        console.print(f"\n  [dim]Page {page} ({len(agents)} of {total} agents)[/dim]")


@app.command("get")
def get_agent(
    name: str = typer.Argument(..., help="Agent name or slug"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
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
        table = Table(title=f"Workflows ({len(workflows)})")
        table.add_column("#", style="dim", width=3)
        table.add_column("Name", style="bold")
        table.add_column("Description")
        table.add_column("Condition", style="dim")

        for idx, wf in enumerate(workflows):
            if not isinstance(wf, dict):
                continue
            condition = wf.get("condition", "")
            cond_display = condition[:50] + "..." if len(condition) > 50 else condition
            table.add_row(
                str(idx + 1),
                wf.get("name", ""),
                wf.get("description", "")[:60],
                cond_display,
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
    params: Optional[List[str]] = typer.Argument(None, help="Parameters as key=value pairs"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    sync: bool = typer.Option(False, "--sync", "-s", help="Wait for result (synchronous)"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Watch execution progress"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Run an agent with optional parameters.

    If no params are provided, shows available inputs and prompts interactively.

    Examples:
        machina agent run my-agent
        machina agent run my-agent season_id=sr:season:123
        machina agent run my-agent --sync
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
                console.print(f"  [yellow]Ignoring invalid param '{param}' (expected key=value)[/yellow]")

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
            if isinstance(default_expr, str):
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

    console.print()
    console.print(f"  [bold]Running agent:[/bold] [#FF5C1F]{name}[/#FF5C1F]")
    if context_agent:
        for k, v in context_agent.items():
            console.print(f"  [dim]{k}=[/dim]{v}")
    console.print()

    # Execute
    if sync:
        with console.status("  Executing agent (sync)..."):
            result = client.post(f"agent/executor/{name}", body)
    else:
        result = client.post(f"agent/executor/{name}", body)

    data = result.get("data", result)

    if json_output:
        console.print_json(json_lib.dumps(data, default=str))
        return

    agent_run_id = data.get("agent_run_id", "")
    task_id = data.get("task_id", "")

    if sync:
        # Sync mode — show result directly
        response = data.get("response", {})
        status = "completed"
        console.print(Panel(
            f"[bold]Status:[/bold] [green]{status}[/green]\n"
            f"[bold]Agent Run ID:[/bold] {agent_run_id}",
            title="Execution Complete",
            border_style="#FF5C1F",
        ))
        if response:
            formatted = json_lib.dumps(response, indent=2, default=str, ensure_ascii=False)
            from rich.syntax import Syntax
            console.print(Panel(Syntax(formatted, "json", theme="monokai"), title="Response"))
    else:
        # Async mode — show run ID
        console.print(Panel(
            f"[bold]Agent Run ID:[/bold] {agent_run_id}\n"
            f"[bold]Task ID:[/bold] {task_id}\n"
            f"[bold]Status:[/bold] [yellow]scheduled[/yellow]",
            title="Agent Scheduled",
            border_style="#FF5C1F",
        ))
        console.print(f"  [dim]Track with:[/dim] [bold]machina execution get {agent_run_id}[/bold]")

    # Watch mode — poll for completion
    if watch and agent_run_id and not sync:
        console.print()
        elapsed = 0
        with console.status("  Watching execution...") as status_spinner:
            while elapsed < 300:
                time.sleep(3)
                elapsed += 3
                try:
                    run_result = client.get(f"execution/agent-run/{agent_run_id}?compact=true")
                    run_data = run_result.get("data", {})
                    run_status = run_data.get("status", "")

                    if run_status in ("agent-executed", "completed", "failed"):
                        console.print()
                        exec_time = run_data.get("execution_time")
                        time_str = f"{exec_time:.1f}s" if isinstance(exec_time, (int, float)) else "N/A"
                        color = "green" if "executed" in run_status or "completed" in run_status else "red"

                        console.print(Panel(
                            f"[bold]Status:[/bold] [{color}]{run_status}[/{color}]\n"
                            f"[bold]Time:[/bold] {time_str}\n"
                            f"[bold]Workflows:[/bold] {run_data.get('completed_workflows', 0)}/{run_data.get('total_workflows', 0)}",
                            title="Execution Complete",
                            border_style="#FF5C1F",
                        ))

                        response = run_data.get("response", {})
                        if response:
                            formatted = json_lib.dumps(response, indent=2, default=str, ensure_ascii=False)
                            from rich.syntax import Syntax
                            console.print(Panel(Syntax(formatted, "json", theme="monokai"), title="Response"))
                        break
                except Exception:
                    pass

            if elapsed >= 300:
                console.print("  [yellow]Timed out watching. Agent may still be running.[/yellow]")
                console.print(f"  [dim]Check with:[/dim] [bold]machina execution get {agent_run_id}[/bold]")


@app.command("executions")
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

    table = Table(title="Agent Executions")
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Time", style="dim")
    table.add_column("Workflows", justify="right", style="dim")
    table.add_column("Created", style="dim")
    table.add_column("ID", style="dim")

    for ex in executions:
        status = ex.get("status", "")
        color = "green" if status in ("agent-executed", "completed", "success") else "red" if "fail" in status else "yellow"
        exec_time = ex.get("execution_time")
        time_str = f"{exec_time:.1f}s" if isinstance(exec_time, (int, float)) else ""
        total_wf = ex.get("total_workflows")
        completed_wf = ex.get("completed_workflows")
        wf_str = f"{completed_wf}/{total_wf}" if total_wf else ""
        table.add_row(
            ex.get("name", ""),
            f"[{color}]{status}[/{color}]",
            time_str,
            wf_str,
            str(ex.get("date", ex.get("created", "")))[:19],
            ex.get("_id", ""),
        )

    console.print(table)

    pagination = result.get("pagination", {})
    total = pagination.get("total", pagination.get("total_documents", 0))
    if total:
        console.print(f"\n  [dim]Page {page} ({len(executions)} of {total} executions)[/dim]")
