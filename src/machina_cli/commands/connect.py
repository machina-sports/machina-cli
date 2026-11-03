"""`machina connect` — resolve a project's MCP connection for an external agent.

One-command bridge for tools like sportsclaw: resolves the per-project MCP
endpoint (via the same verified derivation as `machina mcp url`) and pairs it with
the caller's auth token so the agent can register the server without a hand-pasted
URL. The token is masked by default; pass --reveal (or --json --reveal) to emit it.
"""

import json
import re

from rich.console import Console

# Single source of truth for the MCP connection contract and its JSON schema
# (see mcp.py / mcp_session.py).
from machina_cli import mcp_session
from machina_cli.client import MachinaClient
from machina_cli.commands.credentials import _mask_key
from machina_cli.commands.mcp import connection_payload, probe_or_fail, resolve_base_url
from machina_cli.config import get_config, resolve_auth_token
from machina_cli.mcp_session import MCPConnectError

console = Console()

# sportsclaw server names must match ^[a-zA-Z0-9_-]+$.
_NAME_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


def _safe_name(value: str) -> str:
    """Coerce a value into a sportsclaw-acceptable server name."""
    cleaned = _NAME_UNSAFE.sub("-", value).strip("-")
    return cleaned or "machina"


def _fail(message: str, json_output: bool, code: str = "credential_mint_failed"):
    """Emit a typed error (shared schema-v1 envelope) and exit non-zero."""
    from machina_cli.commands.mcp import fail

    fail(MCPConnectError(code, message), json_output)


def _ensure_project_api_key(project_id: str, org_id: str, json_output: bool) -> str:
    """Return a durable project API key (X-Api-Token), reusing the dedicated
    `sportsclaw-<project>` key if it already exists, otherwise minting one.

    Filters server-side by name so the lookup is page-independent, and refuses to
    mint a duplicate when the named key already exists but its value is unavailable.
    Reuses the same Core API endpoints as `machina credentials`. May raise SystemExit
    (via MachinaClient) on auth/API failure.
    """
    client = MachinaClient()
    key_name = f"sportsclaw-{project_id}"

    existing = client.post(
        "system/api/search-key",
        {"filters": {"project_id": project_id, "name": key_name}, "page": 1, "page_size": 10},
    ).get("data", [])
    if existing:
        value = existing[0].get("key")
        if value:
            return value
        # Named key exists but its value isn't retrievable — minting again would
        # sprawl duplicates, so stop and let the user resolve it explicitly.
        _fail(
            f"a '{key_name}' api key already exists but its value is unavailable; "
            "revoke it with `machina credentials` or pass an existing token",
            json_output,
        )

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
    project_id: str | None,
    json_output: bool,
    reveal: bool,
    probe: bool,
    name: str | None,
    mint: bool = False,
    org: str | None = None,
    timeout: float = mcp_session.DEFAULT_TIMEOUT,
):
    """Resolve and present a project's MCP connection bundle."""
    project_id = project_id or get_config("default_project_id")
    if not project_id:
        _fail("no project specified", json_output, "wrong_project")

    header_name, token = resolve_auth_token()
    if not token:
        _fail("not authenticated", json_output, "missing_credentials")

    project_id, base_url = resolve_base_url(project_id, json_output)
    server_name = name or _safe_name(project_id)

    # --mint: ensure a durable, dedicated project API key (X-Api-Token) instead of
    # handing off whatever ambient credential the user happens to have. Done before
    # the probe so readiness is checked with the credential actually emitted.
    if mint:
        org_id = org or get_config("default_organization_id")
        if not org_id:
            _fail(
                "organization required to mint an api key (set a default org or pass --org)",
                json_output,
            )
        try:
            minted = _ensure_project_api_key(project_id, org_id, json_output)
        except SystemExit:
            _fail("could not mint api key", json_output)
        if not minted:
            _fail("api key minting returned no key", json_output)
        header_name, token = "X-Api-Token", minted

    probed = None
    if probe:
        probed = probe_or_fail(base_url, (header_name, token), json_output, timeout)

    durable = header_name == "X-Api-Token"

    payload = connection_payload(project_id, base_url, header_name, probed)
    if json_output:
        payload.update(
            {
                "name": server_name,
                # null (not the masked preview) unless --reveal, so a script can
                # never mistake a redacted string for a usable credential.
                "token": token if reveal else None,
                "masked": not reveal,
                "durable": durable,
            }
        )
        print(json.dumps(payload))
        return

    shown = token if reveal else _mask_key(token)
    hint = "" if reveal else "  [dim](masked — use --reveal)[/dim]"
    console.print(f"[bold]Name:[/bold]        {server_name}")
    console.print(f"[bold]MCP URL:[/bold]     {payload['url']}")
    console.print(f"[bold]Transport:[/bold]   {payload['transport']}")
    console.print(f"[bold]Auth header:[/bold] {header_name}")
    console.print(f"[bold]Token:[/bold]       {shown}{hint}")
    if probed:
        console.print(
            f"[bold]Protocol:[/bold]    {probed['protocol_version']}  [green]ready "
            f"({probed['tool_count']} tools, health_check ok)[/green]"
        )

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
        f"  [bold]sportsclaw mcp add[/bold] {payload['url']} --name {server_name} --token <token>"
    )
    console.print(
        "[dim]Get the token with[/dim] machina connect --reveal[dim], or[/dim] --json --reveal[dim] for a script.[/dim]"
    )
