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
from machina_cli.client import MachinaClient
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


def _ensure_project_api_key(project_id: str, org_id: str) -> str:
    """Return a durable project API key (X-Api-Token), reusing the dedicated
    `sportsclaw-<project>` key if it already exists, otherwise minting one.

    Reuses the same Core API endpoints as `machina credentials`. May raise
    SystemExit (via MachinaClient) on auth/API failure.
    """
    client = MachinaClient()
    key_name = f"sportsclaw-{project_id}"

    existing = client.post(
        "system/api/search-key",
        {"filters": {"project_id": project_id}, "sorters": ["name", 1], "page": 1, "page_size": 50},
    ).get("data", [])
    for key in existing:
        if key.get("name") == key_name and key.get("key"):
            return key["key"]

    result = client.post(
        "system/api/generate-key",
        {
            "organization_id": org_id,
            "project_id": project_id,
            "name": key_name,
            "level": "SERVICE_ACCESS",
        },
    )
    return result.get("data", {}).get("api_key", "")


def run(
    project_id: Optional[str],
    json_output: bool,
    reveal: bool,
    probe: bool,
    name: Optional[str],
    mint: bool = False,
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

    # --mint: ensure a durable, dedicated project API key (X-Api-Token) instead of
    # handing off whatever ambient credential the user happens to have.
    if mint:
        org_id = get_config("default_organization_id")
        if not org_id:
            _fail("organization required to mint an api key (set a default org)", json_output)
        try:
            minted = _ensure_project_api_key(project_id, org_id)
        except SystemExit:
            if json_output:
                print(json.dumps({"error": "could not mint api key"}))
                raise typer.Exit(1) from None
            raise
        if not minted:
            _fail("api key minting returned no key", json_output)
        header_name, token = "X-Api-Token", minted

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
            "connection re-run with [bold]--mint[/bold] to use a dedicated project API key "
            "(or set [bold]MACHINA_API_KEY[/bold])."
        )

    console.print("\n[dim]Register with sportsclaw:[/dim]")
    console.print(
        f"  [bold]sportsclaw mcp add[/bold] {mcp_url} --name {server_name} --token <token>"
    )
    console.print(
        "[dim]Get the token with[/dim] machina connect --reveal[dim], or[/dim] --json --reveal[dim] for a script.[/dim]"
    )
