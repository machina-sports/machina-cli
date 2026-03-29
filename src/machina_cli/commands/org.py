"""Organization management commands."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from machina_cli.client import MachinaClient
from machina_cli.config import get_config, set_config

app = typer.Typer(help="Organization management")
console = Console()


@app.command("list")
def list_orgs():
    """List your organizations."""
    client = MachinaClient()
    result = client.post("user/organizations/search", {
        "filters": {},
        "page": 1,
        "page_size": 50,
        "sorters": ["name", 1],
    })

    orgs = result.get("data", [])
    default_org = get_config("default_organization_id")

    if not orgs:
        console.print("[yellow]No organizations found.[/yellow]")
        return

    table = Table(title="Organizations")
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Slug")
    table.add_column("Status")
    table.add_column("Default", justify="center")

    for org in orgs:
        # API returns user_access_organization records with organization_ prefix
        org_id = org.get("organization_id", org.get("_id", ""))
        is_default = "✦" if org_id == default_org else ""
        table.add_row(
            org_id,
            org.get("organization_name", org.get("name", "")),
            org.get("organization_slug", org.get("slug", "")),
            org.get("status", ""),
            is_default,
        )

    console.print(table)


@app.command()
def create(
    name: str = typer.Argument(..., help="Organization name"),
    slug: Optional[str] = typer.Option(None, "--slug", "-s", help="Organization slug (auto-generated if omitted)"),
):
    """Create a new organization."""
    client = MachinaClient()

    # Generate slug if not provided
    if not slug:
        slug_result = client.post("organization/generate-slug", {"name": name})
        slug = slug_result.get("data", {}).get("slug", name.lower().replace(" ", "-"))

    result = client.post("organization", {
        "name": name,
        "slug": slug,
        "status": "active",
    })

    org_id = result.get("data", {}).get("id", "")
    console.print(f"[green]Organization created:[/green] {name} (ID: {org_id})")

    # Set as default if no default exists
    if not get_config("default_organization_id"):
        set_config("default_organization_id", org_id)
        console.print(f"Set as default organization.")


@app.command()
def use(
    org_id: str = typer.Argument(..., help="Organization ID to set as default"),
):
    """Set default organization."""
    set_config("default_organization_id", org_id)
    console.print(f"Default organization set to [bold]{org_id}[/bold]")
