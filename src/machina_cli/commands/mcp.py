"""MCP connection resolver commands.

Resolves a project's Model Context Protocol endpoint so external agents (e.g.
sportsclaw) can wire it in without a hand-pasted URL. The per-project Client-API
base comes from the project-token JWT `api` claim (see project_client.py); the
MCP endpoint is that base plus a fixed path.
"""

import json

import typer
from rich.console import Console

from machina_cli.config import get_config, resolve_auth_token
from machina_cli.project_client import ProjectClient

app = typer.Typer(help="Resolve Machina MCP connection details")
console = Console()

# The MCP server is provisioned at the Client-API base (the project-token JWT `api`
# claim) + this path, served over SSE, authenticated with X-Api-Token or
# X-Session-Token (X-Project-Token is NOT required).
# Verified against machina-core-api + machina-client-api (issue #20, D1): the host
# comes from the `api` claim (standard host or a custom address_client_domain), and
# the "/mcp/sse" path is identical across both tenant-project and org-client
# deployments. It matches the backend's own SPORTSCLAW_MCP_SERVERS derivation
# (core-api tenant_project/deployment.py). Residual: an org-client-deployed project
# whose `api` claim host differs from its MCP host — `--probe` catches that.
_MCP_PATH = "/mcp/sse"
_MCP_TRANSPORT = "sse"
_MCP_AUTH_HEADER = "X-Api-Token"


def _probe(mcp_url: str, auth: tuple | None = None) -> bool:
    """Best-effort reachability check for the MCP SSE endpoint.

    Opens the SSE stream and accepts only a 200 with an event-stream content type.
    This confirms a reachable SSE endpoint, not full MCP protocol conformance. Any
    failure (non-200, wrong content type, auth error, connection error) returns
    False so callers fail loud rather than handing out an unverified URL.

    `auth` is an optional (header_name, token) pair to test the exact credential a
    caller will hand off; when omitted the ambient resolve_auth_token() is used.
    """
    import httpx

    headers = {"Accept": "text/event-stream"}
    header_name, token = auth if auth is not None else resolve_auth_token()
    if header_name and token:
        headers[header_name] = token
    try:
        with httpx.Client(timeout=5.0) as client:  # noqa: SIM117 — separate contexts keep the teardown order explicit
            with client.stream("GET", mcp_url, headers=headers) as resp:
                content_type = resp.headers.get("content-type", "")
                return resp.status_code == 200 and "event-stream" in content_type
    except Exception:
        return False


@app.command()
def url(
    project_id: str | None = typer.Argument(
        None, help="Project ID (defaults to the selected project)"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    probe: bool = typer.Option(False, "--probe", help="Verify the SSE endpoint is reachable"),
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

    if not client.api_url:
        # A stored project token without an `api` claim yields an empty base; emitting
        # "/mcp/sse" would hand out a silently broken URL.
        if json_output:
            print(json.dumps({"error": "project has no client-api address"}))
            raise typer.Exit(1)
        console.print("[red]Project has no Client-API address; cannot resolve MCP endpoint.[/red]")
        raise typer.Exit(1)

    mcp_url = f"{client.api_url}{_MCP_PATH}"

    if probe and not _probe(mcp_url):
        # Failure uses the same {"error": ...} envelope + non-zero exit as the rest of
        # the CLI; success is signalled by the normal payload and exit 0.
        if json_output:
            print(json.dumps({"error": "endpoint not reachable", "url": mcp_url}))
        else:
            console.print(f"[red]MCP endpoint not reachable: {mcp_url}[/red]")
        raise typer.Exit(1)

    if json_output:
        print(
            json.dumps(
                {
                    "project_id": project_id,
                    "url": mcp_url,
                    "transport": _MCP_TRANSPORT,
                    "auth_header": _MCP_AUTH_HEADER,
                }
            )
        )
        return

    console.print(f"[bold]MCP URL:[/bold] {mcp_url}")
    console.print(f"[bold]Transport:[/bold] {_MCP_TRANSPORT}")
    console.print(f"[bold]Auth header:[/bold] {_MCP_AUTH_HEADER}")
    if probe:
        console.print("[green]Endpoint reachable.[/green]")
