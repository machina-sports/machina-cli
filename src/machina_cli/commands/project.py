"""Project management commands."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from machina_cli.client import MachinaClient
from machina_cli.config import get_config, set_config

app = typer.Typer(help="Project management")
console = Console()


@app.command("list")
def list_projects():
    """List your projects."""
    client = MachinaClient()
    result = client.post("user/projects/search", {
        "filters": {},
        "page": 1,
        "page_size": 50,
        "sorters": ["name", 1],
    })

    projects = result.get("data", [])
    default_project = get_config("default_project_id")

    if not projects:
        console.print("[yellow]No projects found.[/yellow]")
        return

    table = Table(title="Projects")
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Slug")
    table.add_column("Organization", style="dim")
    table.add_column("Status")
    table.add_column("Default", justify="center")

    for proj in projects:
        # API returns user_access_project records with project_ prefix from lookup
        proj_id = proj.get("project_id", proj.get("_id", ""))
        is_default = "✦" if proj_id == default_project else ""
        table.add_row(
            proj_id,
            proj.get("project_name", proj.get("name", "")),
            proj.get("project_slug", proj.get("slug", "")),
            proj.get("organization_id", ""),
            proj.get("status", ""),
            is_default,
        )

    console.print(table)


@app.command()
def create(
    name: str = typer.Argument(..., help="Project name"),
    org_id: Optional[str] = typer.Option(None, "--org", "-o", help="Organization ID (uses default if omitted)"),
    slug: Optional[str] = typer.Option(None, "--slug", "-s", help="Project slug (auto-generated if omitted)"),
):
    """Create a new project."""
    client = MachinaClient()

    if not org_id:
        org_id = get_config("default_organization_id")
    if not org_id:
        console.print("[red]No organization specified. Use --org or set default with `machina org use`.[/red]")
        raise typer.Exit(1)

    if not slug:
        slug_result = client.post("project/generate-slug", {"name": name})
        slug = slug_result.get("data", {}).get("slug", name.lower().replace(" ", "-"))

    result = client.post("project", {
        "name": name,
        "slug": slug,
        "organization_id": org_id,
        "status": "active",
    })

    proj_id = result.get("data", {}).get("id", "")
    console.print(f"[green]Project created:[/green] {name} (ID: {proj_id})")

    if not get_config("default_project_id"):
        set_config("default_project_id", proj_id)
        console.print("Set as default project.")


@app.command()
def use(
    project_id: str = typer.Argument(..., help="Project ID to set as default"),
):
    """Set default project."""
    set_config("default_project_id", project_id)

    # Try to resolve project name for display and shell prompt
    try:
        client = MachinaClient()
        result = client.post("user/projects/search", {
            "filters": {}, "page": 1, "page_size": 100, "sorters": ["name", 1],
        })
        for proj in result.get("data", []):
            if proj.get("project_id") == project_id:
                name = proj.get("project_name", "")
                if name:
                    set_config("default_project_name", name)
                console.print(f"Default project set to [bold]{name or project_id}[/bold]")
                return
    except Exception:
        pass

    console.print(f"Default project set to [bold]{project_id}[/bold]")


@app.command()
def status(
    org_id: Optional[str] = typer.Option(None, "--org", "-o", help="Organization ID"),
):
    """Show project deployment status."""
    client = MachinaClient()

    if not org_id:
        org_id = get_config("default_organization_id")
    if not org_id:
        console.print("[red]No organization specified. Use --org or set default with `machina org use`.[/red]")
        raise typer.Exit(1)

    result = client.get(f"organization/{org_id}/api-status")
    data = result.get("data", {})

    status_value = data.get("status", "unknown")
    color = "green" if status_value == "online" else "red" if status_value == "offline" else "yellow"

    console.print(Panel.fit(
        f"[bold]Status:[/bold] [{color}]{status_value}[/{color}]\n"
        f"[bold]Organization:[/bold] {org_id}",
        title="Deployment Status",
    ))
