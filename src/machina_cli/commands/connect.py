"""`machina connect` — resolve a project's MCP connection for an external agent.

One-command bridge for tools like sportsclaw: resolves the per-project MCP
endpoint (via the same verified derivation as `machina mcp url`) and pairs it with
the caller's auth token so the agent can register the server without a hand-pasted
URL. The token is masked by default; pass --reveal (or --json --reveal) to emit it.
"""

import json
from typing import Optional

import typer
from rich.console import Console

# Single source of truth for the MCP connection contract (verified against
# machina-core-api + machina-client-api — see mcp.py).
from machina_cli.commands.credentials import _mask_key
from machina_cli.commands.mcp import _MCP_PATH, _MCP_TRANSPORT, _probe
from machina_cli.config import get_config, resolve_auth_token
from machina_cli.project_client import ProjectClient

console = Console()


def _fail(message: str, json_output: bool, extra: Optional[dict] = None):
    """Emit an error (JSON envelope or console) and exit non-zero."""
    if json_output:
        print(json.dumps({"error": message, **(extra or {})}))
    else:
        console.print(f"[red]{message}.[/red]")
    raise typer.Exit(1)


def run(
    project_id: Optional[str],
    json_output: bool,
    reveal: bool,
    probe: bool,
    name: Optional[str],
):
    """Resolve and present a project's MCP connection bundle."""
    project_id = project_id or get_config("default_project_id")
    if not project_id:
        _fail("no project specified", json_output)

    header_name, token = resolve_auth_token()
    if not token:
        _fail("not authenticated", json_output)

    try:
        client = ProjectClient(project_id)
    except SystemExit:
        # ProjectClient raises SystemExit on auth/lookup failure (detail on stderr).
        if json_output:
            print(json.dumps({"error": "could not resolve project session"}))
            raise typer.Exit(1) from None
        raise

    if not client.api_url:
        _fail("project has no client-api address", json_output)

    mcp_url = f"{client.api_url}{_MCP_PATH}"
    server_name = name or project_id

    if probe and not _probe(mcp_url):
        _fail("endpoint not reachable", json_output, {"url": mcp_url})

    if json_output:
        print(
            json.dumps(
                {
                    "name": server_name,
                    "url": mcp_url,
                    "transport": _MCP_TRANSPORT,
                    "auth_header": header_name,
                    "token": token if reveal else _mask_key(token),
                    "masked": not reveal,
                }
            )
        )
        return

    shown = token if reveal else _mask_key(token)
    hint = "" if reveal else "  [dim](masked — use --reveal)[/dim]"
    console.print(f"[bold]Name:[/bold]        {server_name}")
    console.print(f"[bold]MCP URL:[/bold]     {mcp_url}")
    console.print(f"[bold]Transport:[/bold]   {_MCP_TRANSPORT}")
    console.print(f"[bold]Auth header:[/bold] {header_name}")
    console.print(f"[bold]Token:[/bold]       {shown}{hint}")

    # sportsclaw injects --token as X-Api-Token; a session token may expire and
    # may not validate there. Nudge toward a durable project API key.
    if header_name != "X-Api-Token":
        console.print(
            "\n[yellow]Note:[/yellow] this is a session token (expires). For a durable "
            "connection use an API key: set [bold]MACHINA_API_KEY[/bold] or run "
            "[bold]machina credentials generate[/bold]."
        )

    console.print("\n[dim]Register with sportsclaw:[/dim]")
    console.print(
        f"  [bold]sportsclaw mcp add[/bold] {mcp_url} --name {server_name} --token <token>"
    )
    console.print(
        "[dim]Get the token with[/dim] machina connect --reveal[dim], or[/dim] --json --reveal[dim] for a script.[/dim]"
    )
