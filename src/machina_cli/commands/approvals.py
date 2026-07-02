"""Human approvals — the workflow checkpoint door.

Workflows gate risky/publishable actions behind an `approval-request` document
(composed by the machina-nodes `compose_approval` node). This command group is
the human side of that door: list what's waiting, approve or reject. Resolution
runs IN-POD via the `machina-approval-resolve` workflow, so every surface (CLI,
Studio, MCP) shares the same logic — the CLI is deliberately thin.
"""

import getpass
import json as json_lib
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from machina_cli.project_client import ProjectClient

app = typer.Typer(help="Human approvals (list / approve / reject workflow checkpoints)")
console = Console()


def _requests(client: ProjectClient, show_all: bool) -> list:
    filters = {"name": "approval-request"}
    if not show_all:
        filters["value.status"] = "pending"
    r = client.post(
        "document/search",
        {"compact": False, "filters": filters, "page": 1, "page_size": 50, "sorters": ["created", -1]},
    )
    d = r.get("data")
    return (d.get("data") if isinstance(d, dict) else d) or []


@app.command("list")
def list_approvals(
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID (default: selected project)"),
    show_all: bool = typer.Option(False, "--all", "-a", help="Include already-resolved requests"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List approval requests waiting for a human (default: pending only)."""
    client = ProjectClient(project_id)
    rows = _requests(client, show_all)

    if json_output:
        payload = [{"request_id": (r.get("value") or {}).get("request_id"),
                    "title": (r.get("value") or {}).get("title"),
                    "status": (r.get("value") or {}).get("status"),
                    "action_workflow": ((r.get("value") or {}).get("action") or {}).get("workflow"),
                    "requested_at": (r.get("value") or {}).get("requested_at"),
                    "created": str(r.get("created") or "")} for r in rows]
        console.print_json(json_lib.dumps(payload, default=str))
        return

    if not rows:
        console.print("[green]No pending approvals.[/green]" if not show_all else "[yellow]No approval requests found.[/yellow]")
        return
    table = Table(title="Approval requests" + ("" if show_all else " — pending"))
    table.add_column("Request", style="bold")
    table.add_column("Title", overflow="fold")
    table.add_column("Status")
    table.add_column("On approve, runs", style="dim")
    table.add_column("Requested", style="dim", no_wrap=True)
    for r in rows:
        v = r.get("value") or {}
        status = v.get("status", "?")
        color = {"pending": "yellow", "approved": "green", "rejected": "red"}.get(status, "dim")
        table.add_row(v.get("request_id", "?"), v.get("title", ""),
                      f"[{color}]{status}[/]", (v.get("action") or {}).get("workflow") or "—",
                      str(v.get("requested_at") or r.get("created") or "")[:16])
    console.print(table)
    console.print("  [dim]Resolve with[/] [bold]machina approvals approve|reject <request-id>[/]")


def _resolve(request_id: str, decision: str, project_id: Optional[str], json_output: bool) -> None:
    client = ProjectClient(project_id)
    try:
        resolver = getpass.getuser()
    except Exception:  # noqa: BLE001
        resolver = "cli"
    result = client.post(
        "workflow/execute/machina-approval-resolve",
        {"request_id": request_id, "decision": decision, "resolver": resolver},
    )
    data = result.get("data") or {}
    if json_output:
        console.print_json(json_lib.dumps(data, default=str))
        return
    resolved = data.get("resolved")
    dispatch = data.get("dispatch") or {}
    error = data.get("error") or ""
    if resolved is True or (resolved is None and result.get("status")):
        verb = "approved" if decision == "approve" else "rejected"
        console.print(f"[green]Request {request_id} {verb}.[/green]")
        if dispatch.get("dispatched"):
            console.print(f"  [dim]action dispatched:[/] [bold]{dispatch.get('workflow')}[/]")
        elif decision == "approve" and dispatch.get("workflow"):
            console.print(f"  [red]action dispatch failed:[/] {dispatch.get('error')}")
    else:
        console.print(f"[red]Could not resolve {request_id}:[/red] {error or 'unknown error'}")
        raise typer.Exit(1)


@app.command("approve")
def approve(
    request_id: str = typer.Argument(..., help="The approval request id (from `approvals list` or Slack)"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID (default: selected project)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Approve a request — the stored action workflow runs in-pod."""
    _resolve(request_id, "approve", project_id, json_output)


@app.command("reject")
def reject(
    request_id: str = typer.Argument(..., help="The approval request id (from `approvals list` or Slack)"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID (default: selected project)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Reject a request — recorded, nothing runs."""
    _resolve(request_id, "reject", project_id, json_output)
