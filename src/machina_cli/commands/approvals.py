"""Human approvals — the workflow checkpoint door.

Workflows gate risky/publishable actions behind an `approval-request` document
(composed by the machina-nodes `compose_approval` node). This command group is
the human side of that door: list what's waiting, approve or reject. Resolution
runs IN-POD via the `machina-approval-resolve` workflow, so every surface (CLI,
Studio, MCP) shares the same logic — the CLI is deliberately thin.
"""

import getpass
import json as json_lib

import typer

from machina_cli.project_client import ProjectClient
from machina_cli.ui import (
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

app = typer.Typer(help="Human approvals (list / approve / reject workflow checkpoints)")


def _requests(
    client: ProjectClient, show_all: bool, page: int, page_size: int
) -> tuple[list, dict]:
    filters = {"name": "approval-request"}
    if not show_all:
        filters["value.status"] = "pending"
    r = client.post(
        "document/search",
        {
            "compact": False,
            "filters": filters,
            "page": page,
            "page_size": page_size,
            "sorters": ["created", -1],
        },
    )
    return extract_collection(r), r


@app.command("list")
def list_approvals(
    project_id: str | None = typer.Option(
        None, "--project", "-p", help="Project ID (default: selected project)"
    ),
    show_all: bool = typer.Option(False, "--all", "-a", help="Include already-resolved requests"),
    page: int = typer.Option(1, "--page", help="Page number"),
    page_size: int = typer.Option(50, "--limit", "-l", help="Items per page"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List approval requests waiting for a human (default: pending only)."""
    validate_pagination(page, page_size)
    client = ProjectClient(project_id)
    rows, result = _requests(client, show_all, page, page_size)

    if json_output:
        payload = [
            {
                "request_id": (r.get("value") or {}).get("request_id"),
                "title": (r.get("value") or {}).get("title"),
                "status": (r.get("value") or {}).get("status"),
                "action_workflow": ((r.get("value") or {}).get("action") or {}).get("workflow"),
                "requested_at": (r.get("value") or {}).get("requested_at"),
                "created": str(r.get("created") or ""),
            }
            for r in rows
        ]
        emit_json(payload)
        return

    if not rows:
        empty_state("pending approvals", positive=True) if not show_all else empty_state(
            "approval requests"
        )
        return
    table = make_table("Approval requests" + ("" if show_all else " — pending"), expand=True)
    table.add_column("Request", ratio=2, overflow="ellipsis")
    table.add_column("Title", ratio=3, overflow="fold")
    table.add_column("Status", no_wrap=True)
    table.add_column("On approve, runs", ratio=2, overflow="ellipsis")
    table.add_column("Requested", no_wrap=True)
    for r in rows:
        v = r.get("value") or {}
        status = v.get("status", "?")
        table.add_row(
            cell(v.get("request_id", "?"), style="bold"),
            cell(v.get("title", "")),
            status_cell(status),
            cell((v.get("action") or {}).get("workflow"), style="dim"),
            datetime_cell(v.get("requested_at") or r.get("created")),
        )
    console.print(table)
    console.print("  [dim]Resolve with[/] [bold]machina approvals approve|reject <request-id>[/]")
    render_pagination(
        result, page=page, page_size=page_size, count=len(rows), noun="approval requests"
    )


def _resolve(request_id: str, decision: str, project_id: str | None, json_output: bool) -> None:
    client = ProjectClient(project_id)
    try:
        resolver = getpass.getuser()
    except Exception:
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
    request_id: str = typer.Argument(
        ..., help="The approval request id (from `approvals list` or Slack)"
    ),
    project_id: str | None = typer.Option(
        None, "--project", "-p", help="Project ID (default: selected project)"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Approve a request — the stored action workflow runs in-pod."""
    _resolve(request_id, "approve", project_id, json_output)


@app.command("reject")
def reject(
    request_id: str = typer.Argument(
        ..., help="The approval request id (from `approvals list` or Slack)"
    ),
    project_id: str | None = typer.Option(
        None, "--project", "-p", help="Project ID (default: selected project)"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """Reject a request — recorded, nothing runs."""
    _resolve(request_id, "reject", project_id, json_output)
