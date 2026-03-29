"""Agent management commands."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

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
    table.add_column("Slug", style="dim")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("ID", style="dim")

    for agent in agents:
        status = agent.get("status", "")
        color = "green" if status == "active" else "yellow" if status == "draft" else "dim"
        table.add_row(
            agent.get("name", ""),
            agent.get("slug", ""),
            agent.get("type", agent.get("agent_type", "")),
            f"[{color}]{status}[/{color}]",
            agent.get("_id", ""),
        )

    console.print(table)

    pagination = result.get("pagination", {})
    total = pagination.get("total", pagination.get("total_documents", 0))
    if total:
        console.print(f"\n  [dim]Showing page {page} ({len(agents)} of {total} agents)[/dim]")


@app.command("get")
def get_agent(
    name: str = typer.Argument(..., help="Agent name or slug"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Get agent details by name."""
    client = ProjectClient(project_id)
    result = client.get(f"agent/{name}")

    data = result.get("data", result)

    if json_output:
        import json
        console.print_json(json.dumps(data, default=str))
        return

    agent = data if not isinstance(data, list) else data[0] if data else {}

    console.print(Panel.fit(
        f"[bold]Name:[/bold] {agent.get('name', 'N/A')}\n"
        f"[bold]Slug:[/bold] {agent.get('slug', 'N/A')}\n"
        f"[bold]Type:[/bold] {agent.get('type', agent.get('agent_type', 'N/A'))}\n"
        f"[bold]Status:[/bold] {agent.get('status', 'N/A')}\n"
        f"[bold]ID:[/bold] {agent.get('_id', 'N/A')}\n"
        f"[bold]Description:[/bold] {agent.get('description', 'N/A')}",
        title="Agent",
        border_style="#FF5C1F",
    ))


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
    table.add_column("Agent", style="bold")
    table.add_column("Status")
    table.add_column("Created", style="dim")
    table.add_column("ID", style="dim")

    for ex in executions:
        status = ex.get("status", "")
        color = "green" if status in ("completed", "success") else "red" if status in ("failed", "error") else "yellow"
        table.add_row(
            ex.get("agent_name", ex.get("agent_slug", "")),
            f"[{color}]{status}[/{color}]",
            str(ex.get("created", ex.get("created_at", "")))[:19],
            ex.get("_id", ""),
        )

    console.print(table)

    pagination = result.get("pagination", {})
    total = pagination.get("total", pagination.get("total_documents", 0))
    if total:
        console.print(f"\n  [dim]Showing page {page} ({len(executions)} of {total} executions)[/dim]")
