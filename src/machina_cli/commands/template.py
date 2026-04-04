"""Template management commands."""

import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.tree import Tree

from machina_cli.project_client import ProjectClient

app = typer.Typer(help="Template management")
console = Console()

DEFAULT_REPO = "https://github.com/machina-sports/machina-templates.git/"
DEFAULT_BRANCH = "main"


@app.command("list")
def list_templates(
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    repo: str = typer.Option(DEFAULT_REPO, "--repo", "-r", help="Git repository URL"),
    branch: str = typer.Option(DEFAULT_BRANCH, "--branch", "-b", help="Git branch"),
    private: bool = typer.Option(False, "--private", help="Private repository"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
):
    """List available templates from the template repository."""
    client = ProjectClient(project_id)
    result = client.post("templates/directories/git", {
        "repo_url": repo,
        "branch": branch,
        "private_repository": private,
    })

    data = result.get("data", result)

    if json_output:
        import json
        console.print_json(json.dumps(data, default=str))
        return

    directories = data.get("directories", []) if isinstance(data, dict) else data

    if not directories:
        console.print("[yellow]No templates found.[/yellow]")
        return

    # Build a tree from the directory paths
    # Filter: only entries with "path" (directories), skip entries with only "datasets"
    paths = []
    template_datasets = {}
    for item in directories:
        if isinstance(item, dict):
            path = item.get("path", "")
            datasets = item.get("datasets")
            if path:
                paths.append(path)
            if datasets:
                # Count files per type in this template
                for ds in datasets:
                    ds_type = ds.get("type", "unknown")
                    ds_path = ds.get("path", "")
                    # Get the template name (first segment of path)
                    parts = ds_path.split("/")
                    if parts:
                        template_datasets.setdefault(ds_type, 0)
                        template_datasets[ds_type] = template_datasets[ds_type] + 1

    # Group top-level template names
    top_level = set()
    for p in paths:
        parts = p.split("/")
        if len(parts) >= 2:
            top_level.add(parts[0])
        elif len(parts) == 1 and parts[0]:
            top_level.add(parts[0])

    # Build tree grouped by top-level
    tree = Tree(f"[bold]Templates[/bold] [dim]({repo.split('/')[-2] if '/' in repo else repo})[/dim]")

    # Group paths under their top-level parent
    children: dict[str, list[str]] = {}
    for p in sorted(paths):
        parts = p.split("/")
        if len(parts) >= 2:
            parent = parts[0]
            child = "/".join(parts[1:])
            children.setdefault(parent, []).append(child)
        elif parts[0]:
            children.setdefault(parts[0], [])

    for parent in sorted(children.keys()):
        subs = children[parent]
        # Get unique second-level names (actual template names)
        template_names = set()
        for sub in subs:
            first = sub.split("/")[0]
            if first:
                template_names.add(first)

        if template_names:
            branch_node = tree.add(f"[bold]{parent}[/bold] [dim]({len(template_names)} templates)[/dim]")
            for name in sorted(template_names):
                branch_node.add(f"[#FF5C1F]{name}[/#FF5C1F]")
        else:
            tree.add(f"[bold]{parent}[/bold]")

    console.print(tree)
    console.print(f"\n  [dim]{len(paths)} directories, {len(top_level)} categories[/dim]")
import os
from pathlib import Path

@app.command("install")
def install_template(
    template_name: str = typer.Argument(..., help="Name of the template/skill to install"),
    project_id: Optional[str] = typer.Option(None, "--project", "-p", help="Project ID"),
    repo: str = typer.Option(DEFAULT_REPO, "--repo", "-r", help="Git repository URL"),
    branch: str = typer.Option(DEFAULT_BRANCH, "--branch", "-b", help="Git branch"),
):
    """Install a premium agent template or skill payload into the local workspace."""
    client = ProjectClient(project_id)
    
    with console.status(f"[bold green]Fetching '{template_name}' payload from Machina Registry..."):
        # Hit the skills/install endpoint
        # For agent-first design, this endpoint would handle the 402 micro-transaction block.
        result = client.post("skills/install", {
            "template": template_name,
            "repo_url": repo,
            "branch": branch
        })
        
    response_data = result.get("data", result)
        
    # Check for payment required (HTTP 402 flow mapping)
    if response_data.get("accessRequirements", {}).get("payment", {}).get("statusCode") == 402:
        amount = response_data["accessRequirements"]["payment"]["amountUSD"]
        url = response_data.get("paymentUrl", f"https://billing.machina.gg/pay?template={template_name}")
        console.print(f"[bold red]HTTP 402 Payment Required[/bold red]")
        console.print(f"Template '{template_name}' requires a micro-transaction of ${amount:.2f} USD.")
        console.print(f"Please complete the payment here to unlock the payload:")
        console.print(f"[link={url}]{url}[/link]")
        console.print("\n[yellow]Agent Action:[/yellow] Present this link to the human, wait for confirmation of payment, then re-run the `machina templates install` command.")
        raise typer.Exit(1)
        
    # Process the JSON payload installation
    files = response_data.get("files", [])
    if not files:
        console.print(f"[red]Error: Invalid skill payload received for '{template_name}'. No files found.[/red]")
        raise typer.Exit(1)
        
    console.print(f"\n[bold blue]Installing Skill: {response_data.get('title', template_name)}[/bold blue]")
    console.print(f"{response_data.get('summary', '')}\n")
    
    # Run preflight checks if any
    preflight = response_data.get("preflightChecks", [])
    if preflight:
        console.print("[bold]Running Preflight Checks...[/bold]")
        for check in preflight:
            name = check.get("name", "Check")
            command = check.get("check", "")
            console.print(f" - {name}...")
            # Execute safely
            ret = os.system(command)
            if ret != 0 and check.get("required"):
                console.print(f"[bold red]Preflight check '{name}' failed. Installation aborted.[/bold red]")
                raise typer.Exit(1)
                
    # Write files to disk
    console.print("\n[bold]Writing Agent Toolkit...[/bold]")
    for file_obj in files:
        file_path = file_obj.get("path")
        content = file_obj.get("content", "")
        mode = file_obj.get("writeMode", "create")
        
        target_path = Path.cwd() / file_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        if mode == "append" and target_path.exists():
            with open(target_path, "a") as f:
                f.write("\n" + content)
            console.print(f" [green]Appended[/green] {file_path}")
        else:
            with open(target_path, "w") as f:
                f.write(content)
            console.print(f" [green]Created[/green] {file_path}")
            
    # Print next steps
    next_steps = response_data.get("nextSteps", [])
    if next_steps:
        console.print("\n[bold yellow]Next Steps for the Agent:[/bold yellow]")
        for i, step in enumerate(next_steps, 1):
            console.print(f"{i}. {step}")
            
    console.print(f"\n[bold green]Successfully installed {template_name}![/bold green]")
