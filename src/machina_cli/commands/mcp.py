"""MCP connection resolver commands.

Resolves a project's Model Context Protocol endpoint so external agents (e.g.
sportsclaw) can wire it in without a hand-pasted URL. The per-project Client-API
base comes from the project-token JWT `api` claim (see project_client.py); the
MCP endpoint is that base plus a fixed path.
"""

import json
from typing import Optional

import typer
from rich.console import Console

from machina_cli.config import get_config, resolve_auth_token
from machina_cli.project_client import ProjectClient

app = typer.Typer(help="Resolve Machina MCP connection details")
console = Console()

# The MCP server is provisioned per project at the Client-API base + this path,
# served over SSE and authenticated with the same token as the Client API.
# NOTE (issue #20, D1): confirm with the platform whether the premium endpoint is
# the tenant-project pod ({api_claim}/mcp/sse) or the org-client deployment
# ({org_domain}/mcp/sse) before treating these as a frozen contract. Both paths
# exist in machina-core-api; this resolver assumes the project pod. Changing it is
# a one-line edit here.
_MCP_PATH = "/mcp/sse"
_MCP_TRANSPORT = "sse"
_MCP_AUTH_HEADER = "X-Api-Token"


def _probe(mcp_url: str) -> bool:
    """Best-effort check that the URL is a reachable MCP SSE endpoint.

    Opens the SSE stream with the current auth token and accepts only a 200 with
    an event-stream content type. Any failure returns False so callers fail loud
    rather than handing out an unverified URL.
    """
    import httpx

    headers = {"Accept": "text/event-stream"}
    header_name, token = resolve_auth_token()
    if header_name and token:
        headers[header_name] = token
    try:
        with httpx.Client(timeout=5.0) as client:
            with client.stream("GET", mcp_url, headers=headers) as resp:
                content_type = resp.headers.get("content-type", "")
                return resp.status_code == 200 and "event-stream" in content_type
    except Exception:
        return False


@app.command()
def url(
    project_id: Optional[str] = typer.Argument(
        None, help="Project ID (defaults to the selected project)"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    probe: bool = typer.Option(
        False, "--probe", help="Verify the endpoint is reachable and speaks MCP"
    ),
):
    """Resolve a project's MCP endpoint (URL, transport, auth header)."""
    project_id = project_id or get_config("default_project_id")
    if not project_id:
        if json_output:
            print(json.dumps({"error": "no project specified"}))
            raise typer.Exit(1)
        console.print(
            "[red]No project specified. Pass a project id or run `machina project use <id>`.[/red]"
        )
        raise typer.Exit(1)

    try:
        client = ProjectClient(project_id)
    except SystemExit:
        # ProjectClient raises SystemExit on auth/lookup failure (detail on stderr).
        if json_output:
            print(json.dumps({"error": "could not resolve project session"}))
            raise typer.Exit(1) from None
        raise

    mcp_url = f"{client.api_url}{_MCP_PATH}"
    reachable = _probe(mcp_url) if probe else None

    if json_output:
        payload = {
            "project_id": project_id,
            "url": mcp_url,
            "transport": _MCP_TRANSPORT,
            "auth_header": _MCP_AUTH_HEADER,
        }
        if probe:
            payload["reachable"] = reachable
        print(json.dumps(payload))
        if probe and not reachable:
            raise typer.Exit(1)
        return

    console.print(f"[bold]MCP URL:[/bold] {mcp_url}")
    console.print(f"[bold]Transport:[/bold] {_MCP_TRANSPORT}")
    console.print(f"[bold]Auth header:[/bold] {_MCP_AUTH_HEADER}")
    if probe:
        if reachable:
            console.print("[green]Endpoint reachable.[/green]")
        else:
            console.print("[red]Endpoint not reachable or not an MCP server.[/red]")
            raise typer.Exit(1)
