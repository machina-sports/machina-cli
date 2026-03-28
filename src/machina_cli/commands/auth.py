"""Authentication commands: login, logout, whoami."""

from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from machina_cli.client import MachinaClient
from machina_cli.config import (
    clear_credentials,
    resolve_auth_token,
    store_credential,
)

app = typer.Typer(help="Authentication commands")
console = Console()


def do_login(api_key: Optional[str] = None, username: Optional[str] = None, password: Optional[str] = None):
    """Core login logic, callable from both `machina login` and `machina auth login`."""
    if api_key:
        store_credential("api_key", api_key)
        console.print("[green]API key stored successfully.[/green]")

        client = MachinaClient()
        try:
            result = client.get("login/session")
            user_data = result.get("data", {})
            name = user_data.get("name", "Unknown")
            console.print(f"Authenticated as [bold]{name}[/bold]")
        except SystemExit:
            console.print("[yellow]Warning: Could not verify API key. It has been stored anyway.[/yellow]")
        return

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


@app.command()
def login(
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k", help="Authenticate with an API key"),
    username: Optional[str] = typer.Option(None, "--username", "-u", help="Username for login"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Password for login"),
):
    """Login to the Machina platform."""
    do_login(api_key=api_key, username=username, password=password)


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
