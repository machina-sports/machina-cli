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
def list_orgs(
    page: int = typer.Option(1, "--page", help="Page number"),
    page_size: int = typer.Option(20, "--limit", "-l", help="Items per page"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List your organizations."""
    client = MachinaClient()
    result = client.post("user/organizations/search", {
        "filters": {},
        "page": page,
        "page_size": page_size,
        "sorters": ["name", 1],
    })

    orgs = result.get("data", [])
    default_org = get_config("default_organization_id")

    if json_output:
        import json
        console.print_json(json.dumps(orgs, default=str))
        return

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

    pagination = result.get("pagination", {})
    total = pagination.get("total", pagination.get("total_documents", 0))
    if total:
        console.print(f"\n  [dim]Page {page} ({len(orgs)} of {total} organizations)[/dim]")


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

    # Try to resolve org name for display and shell prompt
    try:
        client = MachinaClient()
        result = client.post("user/organizations/search", {
            "filters": {}, "page": 1, "page_size": 100, "sorters": ["name", 1],
        })
        for org in result.get("data", []):
            if org.get("organization_id") == org_id:
                name = org.get("organization_name", "")
                if name:
                    set_config("default_organization_name", name)
                console.print(f"Default organization set to [bold]{name or org_id}[/bold]")
                return
    except Exception:
        pass

    console.print(f"Default organization set to [bold]{org_id}[/bold]")
