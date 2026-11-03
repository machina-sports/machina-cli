"""MCP connection resolver commands.

Resolves a project's Model Context Protocol endpoint so external agents (e.g.
sportsclaw) can wire it in without a hand-pasted URL. The per-project Client-API
base comes from the project-token JWT `api` claim (see project_client.py); the
transport is decided by `mcp_session` (streamable HTTP at `/mcp`, legacy SSE at
`/mcp/sse` only when the deployment has no streamable endpoint).

`machina mcp url` and `machina connect` share one versioned JSON schema
(`mcp_session.SCHEMA`): success payloads come from `connection_payload`, failures
from `MCPConnectError.to_payload`.
"""

import json

import typer
from rich.console import Console
from rich.text import Text

from machina_cli import mcp_session, ui
from machina_cli.config import get_config, resolve_auth_token
from machina_cli.mcp_session import MCPConnectError
from machina_cli.project_client import ProjectClient

app = typer.Typer(help="Resolve Machina MCP connection details")
console = Console()

# Without --probe nothing was negotiated, so the payload reports the legacy SSE
# endpoint every released deployment serves (verified against machina-core-api +
# machina-client-api, issue #20 D1) and marks it `verified: false`. With --probe
# the url/transport are the ones the protocol handshake actually succeeded on.
_MCP_PATH = mcp_session.SSE_PATH
_MCP_TRANSPORT = mcp_session.TRANSPORT_SSE
_MCP_AUTH_HEADER = "X-Api-Token"


def connection_payload(project_id: str, base_url: str, auth_header: str, probed: dict | None):
    """The shared success payload for `mcp url` and `connect` (schema v1)."""
    payload = {
        "schema": mcp_session.SCHEMA,
        "project_id": project_id,
        "url": f"{base_url}{_MCP_PATH}",
        "transport": _MCP_TRANSPORT,
        "auth_header": auth_header,
        "verified": False,
    }
    if probed:
        payload.update(
            {
                "url": probed["url"],
                "transport": probed["transport"],
                "verified": True,
                "protocol_version": probed["protocol_version"],
                "server": probed["server"],
                "tool_count": probed["tool_count"],
                "health_check": probed["health_check"],
            }
        )
    return payload


def fail(error: MCPConnectError, json_output: bool):
    """Emit a typed error (JSON envelope or console) and exit non-zero."""
    if json_output:
        print(json.dumps(error.to_payload()))
    else:
        console.print(f"[red]{error.message}.[/red]")
        if error.url:
            console.print(f"[dim]Endpoint: {error.url}[/dim]")
        if error.hint:
            console.print(f"[yellow]{error.hint}[/yellow]")
    raise typer.Exit(1)


def resolve_base_url(project_id: str | None, json_output: bool) -> tuple[str, str]:
    """Return (project_id, client-api base) for the selected project, or fail typed."""
    project_id = project_id or get_config("default_project_id")
    if not project_id:
        fail(MCPConnectError("wrong_project", "no project specified"), json_output)

    try:
        client = ProjectClient(project_id)
    except SystemExit:
        # ProjectClient raises SystemExit on auth/lookup failure (detail on stderr).
        fail(MCPConnectError("wrong_project", "could not resolve project session"), json_output)

    if not client.api_url:
        # A stored project token without an `api` claim yields an empty base;
        # emitting "/mcp/sse" would hand out a silently broken URL.
        fail(MCPConnectError("wrong_project", "project has no client-api address"), json_output)
    return project_id, client.api_url


def probe_or_fail(base_url: str, auth: tuple[str, str], json_output: bool, timeout: float):
    try:
        return mcp_session.probe(base_url, auth, timeout=timeout)
    except MCPConnectError as error:
        fail(error, json_output)


@app.command()
def url(
    project_id: str | None = typer.Argument(
        None, help="Project ID (defaults to the selected project)"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    probe: bool = typer.Option(
        False,
        "--probe",
        help="Verify readiness: MCP handshake, tools/list and a health_check read",
    ),
    timeout: float = typer.Option(
        mcp_session.DEFAULT_TIMEOUT, "--timeout", help="Probe timeout in seconds"
    ),
):
    """Resolve a project's MCP endpoint (URL, transport, auth header).

    Without --probe the legacy SSE endpoint is reported unverified. With --probe
    the CLI connects (streamable HTTP first, SSE only if the deployment has no
    streamable endpoint) and reports the transport and protocol it negotiated.
    """
    project_id, base_url = resolve_base_url(project_id, json_output)

    probed = None
    if probe:
        probed = probe_or_fail(base_url, resolve_auth_token(), json_output, timeout)

    payload = connection_payload(project_id, base_url, _MCP_AUTH_HEADER, probed)
    if json_output:
        print(json.dumps(payload))
        return

    console.print(f"[bold]MCP URL:[/bold] {payload['url']}")
    console.print(f"[bold]Transport:[/bold] {payload['transport']}")
    console.print(f"[bold]Auth header:[/bold] {payload['auth_header']}")
    if probed:
        server = probed["server"]
        console.print(f"[bold]Protocol:[/bold] {probed['protocol_version']}")
        console.print(f"[bold]Server:[/bold] {server.get('name')} {server.get('version') or ''}")
        console.print(
            f"[green]Ready: handshake ok, {probed['tool_count']} tools, health_check ok.[/green]"
        )
    else:
        console.print("[dim]Unverified — pass --probe to connect and check readiness.[/dim]")


TOOLS_SCHEMA = "machina.mcp.tools/v1"


def _summary(description: str | None) -> str:
    """First non-empty line of a served description (display only, not rewritten)."""
    for line in (description or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _compact(tool) -> dict:
    """Compact view of one served tool. Only fields the server supplied — no
    inferred "executable"/prerequisite flags; `required` is read from inputSchema."""
    schema = tool.inputSchema or {}
    return {
        "name": tool.name,
        "title": tool.title,
        "summary": _summary(tool.description),
        "required": list(schema.get("required") or []),
    }


def _matches(tool, query: str) -> bool:
    haystack = " ".join(filter(None, [tool.name, tool.title, tool.description])).lower()
    return query.lower() in haystack


@app.command()
def tools(
    project_id: str | None = typer.Argument(
        None, help="Project ID (defaults to the selected project)"
    ),
    search: str | None = typer.Option(
        None, "--search", "-s", help="Case-insensitive match on tool name/title/description"
    ),
    describe: str | None = typer.Option(
        None, "--describe", "-d", help="Show one tool exactly as served (incl. input schema)"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    timeout: float = typer.Option(
        mcp_session.DEFAULT_TIMEOUT, "--timeout", help="Connection timeout in seconds"
    ),
):
    """Discover the project's MCP tools (read-only: lists, never calls a tool).

    Walks the server's full tools/list pagination, then filters with --search.
    --describe prints one tool's name, description and input/output schema
    exactly as the server serves them.
    """
    project_id, base_url = resolve_base_url(project_id, json_output)
    try:
        meta, served = mcp_session.run(
            base_url, resolve_auth_token(), mcp_session.list_all_tools, timeout
        )
    except MCPConnectError as error:
        fail(error, json_output)

    connection = {
        "project_id": project_id,
        "url": meta["url"],
        "transport": meta["transport"],
        "protocol_version": meta["protocol_version"],
    }

    if describe:
        match = next((tool for tool in served if tool.name == describe), None)
        if match is None:
            fail(
                MCPConnectError("tool_not_found", f"no tool named '{describe}' on this server"),
                json_output,
            )
        detail = match.model_dump(by_alias=True, exclude_none=True, mode="json")
        if json_output:
            print(json.dumps({"schema": TOOLS_SCHEMA, **connection, "tool": detail}))
            return
        console.print(f"[bold]{match.name}[/bold]" + (f"  {match.title}" if match.title else ""))
        if match.description:
            console.print(Text(match.description))
        console.print("\n[bold]Input schema[/bold]")
        console.print_json(json.dumps(match.inputSchema or {}))
        if match.outputSchema:
            console.print("\n[bold]Output schema[/bold]")
            console.print_json(json.dumps(match.outputSchema))
        return

    selected = [tool for tool in served if not search or _matches(tool, search)]
    if json_output:
        print(
            json.dumps(
                {
                    "schema": TOOLS_SCHEMA,
                    **connection,
                    "search": search,
                    "total": len(served),
                    "count": len(selected),
                    "tools": [_compact(tool) for tool in selected],
                }
            )
        )
        return

    if not selected:
        ui.empty_state("tools matching the search" if search else "tools")
        return
    table = ui.make_table(f"MCP tools · {project_id} ({meta['transport']})")
    table.add_column("Name", no_wrap=True)
    table.add_column("Summary")
    table.add_column("Required")
    for tool in selected:
        row = _compact(tool)
        table.add_row(
            ui.cell(row["name"]), ui.cell(row["summary"]), ui.cell(", ".join(row["required"]))
        )
    console.print(table)
    console.print(
        Text(
            f"{len(selected)} of {len(served)} tools · --describe <name> for the input schema",
            style=ui.MUTED,
        )
    )
