"""Deployment management commands."""

from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from machina_cli.client import MachinaClient
from machina_cli.config import get_config

app = typer.Typer(help="Deployment management")
console = Console()


@app.command("start")
def deploy_start(
    org_id: Optional[str] = typer.Option(None, "--org", "-o", help="Organization ID"),
    version: str = typer.Option("beta", "--version", "-v", help="Client API version"),
):
    """Deploy the Client API for an organization."""
    client = MachinaClient()

    if not org_id:
        org_id = get_config("default_organization_id")
    if not org_id:
        console.print("[red]No organization specified. Use --org or set default.[/red]")
        raise typer.Exit(1)

    console.print(f"Deploying Client API for organization {org_id}...")

    result = client.post(f"organization/{org_id}/deploy-client-api", {
        "client_api_version": version,
    })

    console.print("[green]Deployment started successfully.[/green]")
    data = result.get("data", {})
    if data:
        console.print(Panel.fit(str(data), title="Deployment Result"))


@app.command()
def status(
    org_id: Optional[str] = typer.Option(None, "--org", "-o", help="Organization ID"),
):
    """Check deployment status."""
    client = MachinaClient()

    if not org_id:
        org_id = get_config("default_organization_id")
    if not org_id:
        console.print("[red]No organization specified. Use --org or set default.[/red]")
        raise typer.Exit(1)

    result = client.get(f"organization/{org_id}/client-api-status")
    data = result.get("data", {})

    console.print(Panel.fit(
        f"[bold]Organization:[/bold] {org_id}\n"
        f"[bold]Status:[/bold] {data.get('status', 'unknown')}",
        title="Deployment Status",
    ))


@app.command()
def restart(
    org_id: Optional[str] = typer.Option(None, "--org", "-o", help="Organization ID"),
):
    """Restart the Client API deployment."""
    client = MachinaClient()

    if not org_id:
        org_id = get_config("default_organization_id")
    if not org_id:
        console.print("[red]No organization specified. Use --org or set default.[/red]")
        raise typer.Exit(1)

    console.print(f"Restarting API for organization {org_id}...")

    result = client.post(f"organization/{org_id}/restart-api", {})

    console.print("[green]API restarted successfully.[/green]")
