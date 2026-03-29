"""Template management commands."""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
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
