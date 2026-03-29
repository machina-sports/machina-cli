"""Agent management commands."""

from typing import Optional

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
