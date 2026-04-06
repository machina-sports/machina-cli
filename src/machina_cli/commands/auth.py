"""Authentication commands: login, logout, whoami."""

from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from machina_cli.client import MachinaClient
from machina_cli.config import (
    clear_credentials,
    get_config,
    resolve_auth_token,
    store_credential,
)

app = typer.Typer(help="Authentication commands")
console = Console()

DEFAULT_SESSION_URL = "https://session.machina.gg"


def do_login(
    api_key: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    with_credentials: bool = False,
):
    """
    Core login logic with 3 modes:
    1. --api-key: store API key directly (for CI/CD and scripts)
    2. Default: browser-based Clerk auth (magic link / SSO)
    3. --with-credentials: username/password fallback (dev/internal)
    """
    # Mode 1: API key
    if api_key:
        store_credential("api_key", api_key)
        console.print("[green]API key stored successfully.[/green]")

        # Verify the key works — try login/session first, fall back to org search
        client = MachinaClient()
        try:
            result = client.get("login/session")
            user_data = result.get("data", {})
            name = user_data.get("name", "Unknown")
            console.print(f"Authenticated as [bold]{name}[/bold]")
        except SystemExit:
            # login/session may not support API key auth — try listing orgs instead
            try:
                result = client.post("user/organizations/search", {
                    "filters": {}, "page": 1, "page_size": 1, "sorters": ["name", 1],
                })
                orgs = result.get("data", [])
                if orgs:
                    org_name = orgs[0].get("organization_name", orgs[0].get("name", ""))
                    console.print(f"Authenticated — org: [bold]{org_name}[/bold]")
                else:
                    console.print("[green]API key verified.[/green]")
            except SystemExit:
                console.print("[yellow]API key stored but could not verify. Check the key is valid.[/yellow]")
        return

    # Mode 3: Username/password (explicit flag)
    if with_credentials:
        if not username:
            username = typer.prompt("Username")
        if not password:
            password = typer.prompt("Password", hide_input=True)

        client = MachinaClient()
        result = client.post("login", {"username": username, "password": password}, skip_auth=True)

        token = result.get("data", {}).get("token")
        if not token:
            console.print("[red]Login failed: no token received.[/red]")
            raise typer.Exit(1)

        store_credential("session_token", token)
        console.print("[green]Login successful.[/green]")
        return

    # Mode 2: Browser-based Clerk auth (default)
    from machina_cli.browser_auth import browser_login

    session_url = get_config("session_url") or DEFAULT_SESSION_URL

    token = browser_login(session_url)
    if token:
        store_credential("session_token", token)
        console.print("[green]Login successful.[/green]")

        # Try to show who logged in
        client = MachinaClient()
        try:
            result = client.get("login/session")
            user_data = result.get("data", {})
            name = user_data.get("name", "")
            email = user_data.get("email", "")
            if name or email:
                console.print(f"Authenticated as [bold]{name or email}[/bold]")
        except SystemExit:
            pass
    else:
        raise typer.Exit(1)


@app.command()
def login(
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k", help="Authenticate with an API key"),
    with_credentials: bool = typer.Option(False, "--with-credentials", help="Use username/password instead of browser"),
    username: Optional[str] = typer.Option(None, "--username", "-u", help="Username (requires --with-credentials)"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Password (requires --with-credentials)"),
):
    """Login to the Machina platform.

    Default: opens browser for Clerk authentication (magic link / SSO).
    Use --api-key for CI/CD, or --with-credentials for username/password.
    """
    do_login(api_key=api_key, username=username, password=password, with_credentials=with_credentials)


@app.command()
def logout():
    """Clear stored credentials."""
    clear_credentials()
    console.print("Logged out. Credentials cleared.")


@app.command()
def whoami():
    """Show current authenticated user info."""
    header_name, token = resolve_auth_token()

    if not token:
        console.print("[yellow]Not authenticated. Run `machina login` first.[/yellow]")
        raise typer.Exit(1)

    client = MachinaClient()
    result = client.get("login/session")
    user_data = result.get("data", {})

    auth_method = "API Key" if header_name == "X-Api-Token" else "Session Token"

    console.print(Panel.fit(
        f"[bold]Name:[/bold] {user_data.get('name', 'N/A')}\n"
        f"[bold]Email:[/bold] {user_data.get('email', 'N/A')}\n"
        f"[bold]User ID:[/bold] {user_data.get('_id', user_data.get('id', 'N/A'))}\n"
        f"[bold]Auth:[/bold] {auth_method}",
        title="Current User",
    ))
