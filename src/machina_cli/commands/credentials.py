"""API key and credentials management commands."""

import json

import typer
from rich.console import Console
from rich.table import Table

from machina_cli.client import MachinaClient
from machina_cli.config import get_config

app = typer.Typer(help="API key management")
console = Console()


@app.command()
def generate(
    name: str = typer.Option("client-api", "--name", "-n", help="Name for the API key"),
    org_id: str | None = typer.Option(None, "--org", "-o", help="Organization ID"),
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    level: str = typer.Option("SERVICE_ACCESS", "--level", "-l", help="Permission level"),
):
    """Generate a new API key."""
    client = MachinaClient()

    if not org_id:
        org_id = get_config("default_organization_id")
    if not project_id:
        project_id = get_config("default_project_id")

    if not org_id or not project_id:
        console.print(
            "[red]Organization and project are required. Set defaults or use --org/--project.[/red]"
        )
        raise typer.Exit(1)

    result = client.post(
        "system/api/generate-key",
        {
            "organization_id": org_id,
            "project_id": project_id,
            "name": name,
            "level": level,
        },
    )

    api_key = result.get("data", {}).get("api_key", "")
    console.print("\n[green]API key generated:[/green]\n")
    console.print(f"  [bold]{api_key}[/bold]\n")
    console.print("[dim]Save this key securely — it won't be shown again.[/dim]")


def _mask_key(value: str) -> str:
    """Mask an API key for display. Never returns a non-empty value unmasked."""
    if len(value) > 20:
        return f"{value[:12]}...{value[-6:]}"
    return "***" if value else value


@app.command("list")
def list_keys(
    project_id: str | None = typer.Option(None, "--project", "-p", help="Project ID"),
    show_keys: bool = typer.Option(
        False, "--show-keys", "-s", help="Show full API keys (not masked)"
    ),
    copy: str | None = typer.Option(
        None, "--copy", "-c", help="Copy a key by name (e.g. client-api) to clipboard"
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List API keys for a project."""
    client = MachinaClient()

    if not project_id:
        project_id = get_config("default_project_id")
    if not project_id:
        if json_output:
            print(json.dumps({"error": "project id required"}))
            raise typer.Exit(1)
        console.print("[red]Project ID required. Set default or use --project.[/red]")
        raise typer.Exit(1)

    try:
        result = client.post(
            "system/api/search-key",
            {
                "filters": {"project_id": project_id},
                "sorters": ["name", 1],
                "page": 1,
                "page_size": 50,
            },
        )
    except SystemExit:
        # MachinaClient raises SystemExit on HTTP/connection errors (detail on stderr).
        if json_output:
            print(json.dumps({"error": "api request failed"}))
            raise typer.Exit(1) from None
        raise

    keys = result.get("data", [])

    if json_output:
        # Masked by default; full keys only with --show-keys (matches table output).
        print(
            json.dumps(
                [
                    {
                        "name": k.get("name", ""),
                        "id": k.get("_id", ""),
                        "key": k.get("key", "") if show_keys else _mask_key(k.get("key", "")),
                        "masked": not show_keys,
                    }
                    for k in keys
                ]
            )
        )
        return

    if not keys:
        console.print("[yellow]No API keys found.[/yellow]")
        return

    # --copy mode: find key by name and copy to clipboard
    if copy:
        target = next((k for k in keys if k.get("name") == copy), None)
        if not target:
            console.print(f"[red]No key named '{copy}' found.[/red]")
            raise typer.Exit(1)
        key_value = target.get("key", "")
        try:
            import subprocess

            subprocess.run(["pbcopy"], input=key_value.encode(), check=True)
            console.print(f"[green]Copied '{copy}' key to clipboard.[/green]")
        except Exception:
            # Fallback: just print the key for manual copy
            console.print(f"\n  {key_value}\n")
            console.print(
                "[dim]Tip: pipe to clipboard with[/dim] machina credentials list --copy {copy} | pbcopy"
            )
        return

    table = Table(title="API Keys")
    table.add_column("Name", style="bold")
    table.add_column("Key")
    table.add_column("ID", style="dim")

    for key in keys:
        key_value = key.get("key", "")
        if show_keys:
            display_key = key_value
        else:
            display_key = f"[dim]{_mask_key(key_value)}[/dim]"

        table.add_row(
            key.get("name", ""),
            display_key,
            key.get("_id", ""),
        )

    console.print(table)

    if not show_keys:
        console.print()
        console.print(
            "  [dim]Use[/dim] --show-keys [dim]to reveal full keys, or[/dim] --copy client-api [dim]to copy to clipboard[/dim]"
        )


@app.command()
def revoke(
    key_id: str = typer.Argument(..., help="API key ID to revoke"),
):
    """Revoke an API key."""
    client = MachinaClient()

    client.post("system/api/revoke-key", {"api_key_id": key_id})

    console.print(f"[green]API key {key_id} revoked.[/green]")
